"""Phase R harness: ingest the curated prose corpus, retrieve for the golden set, score.

The corpus is **prose only**. `lichess-org/chess-openings` is structured opening
metadata (ECO join, structured lookup) and is deliberately NOT vectorized here;
see ADR 0006 (revised). Wikibooks Chess Opening Theory is the pedagogical prose.

One JSON config per experiment (see `configs/`). Each run writes
`experiments/rag/runs/<timestamp>_<name>/{effective-config.json,metrics.json,run.json}`
with the effective validated config, corpus and judgment hashes, the embedding
model **digest**, git sha and dirty state, the retrieved hits, and the latency
protocol, so a result can be reproduced or compared. No MLflow (ADR 0006).

Safety: collections are **versioned by fingerprint** and never dropped before a
replacement is validated, so a provider failure cannot destroy prior data. A
remote Milvus host needs an explicit `--allow-remote`.

Run: `uv run python -m experiments.rag.run --config experiments/rag/configs/section.json`
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from backend.app.core.settings import MilvusSettings, Settings, get_settings
from backend.app.ingestion.adapters import (
    WIKIBOOKS_CLEANER_VERSION,
    WikibooksAdapter,
    WikibooksPage,
)
from backend.app.ingestion.chunker import (
    ChunkerError,
    ChunkSource,
    chunk_source,
)
from backend.app.ingestion.pipeline import IngestReport, IngestionError, snapshot_hash, sync_collection
from backend.app.models.knowledge import KnowledgeChunk
from backend.app.services.embeddings import (
    EmbeddingRuntime,
    EmbeddingProvider,
    EmbeddingProviderError,
    FakeEmbeddingProvider,
    OllamaEmbeddingProvider,
)
from backend.app.services.milvus import SCHEMA_VERSION, MilvusStore, MilvusStoreError
from experiments.rag.scoring import (
    evaluate_query,
    is_judged,
    is_relevant,
    ranked_relevance,
    summarize,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(__file__).with_name("configs")
GOLDEN_SET_PATH = Path(__file__).with_name("golden_set.json")
JUDGMENTS_PATH = Path(__file__).with_name("judgments.json")
RUNS_DIR = Path(__file__).with_name("runs")
DEFAULT_CORPUS_DIR = REPO_ROOT / ".scratch" / "rag" / "corpus"
DEFAULT_MILVUS_URI = MilvusSettings().uri


def main() -> int:
    args = _parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    name = config.get("name", args.config.stem)
    provider_name = args.provider or config.get("provider", "ollama")

    try:
        settings = _load_settings(config, args)
    except (ValidationError, ValueError) as exc:
        print(f"harness failed: invalid effective configuration:\n{exc}", file=sys.stderr)
        return 2

    provider = _build_provider(provider_name, settings.embeddings)

    wikibooks_limit = (
        args.wikibooks_limit
        if args.wikibooks_limit is not None
        else config.get("corpus", {}).get("wikibooks_limit")
    )
    try:
        _validate_limit("wikibooks_limit", wikibooks_limit)
    except ValueError as exc:
        print(f"harness failed: invalid effective configuration:\n{exc}", file=sys.stderr)
        return 2
    sources = _load_sources(args.corpus_dir, wikibooks_limit=wikibooks_limit)
    if not sources:
        print("harness failed: corpus is empty (run fetch_corpus.py first)", file=sys.stderr)
        return 2

    try:
        chunks = _chunk_sources(sources, settings.rag.granularity, settings.milvus.max_text_length)
    except ChunkerError as exc:
        print(f"harness failed: {exc}", file=sys.stderr)
        return 2
    if not chunks:
        print("harness failed: corpus produced no chunks", file=sys.stderr)
        return 2

    golden = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    judgments = json.loads(JUDGMENTS_PATH.read_text(encoding="utf-8"))["judgments"]

    uri = _resolve_uri(args, config)
    if _is_remote(uri) and not args.allow_remote:
        print(
            f"harness failed: {uri} is a remote Milvus host; re-run with --allow-remote",
            file=sys.stderr,
        )
        return 2
    settings = settings.model_copy(
        update={"milvus": settings.milvus.model_copy(update={"uri": uri})}
    )

    digest = _model_digest(provider)
    if not digest:
        print(
            "harness failed: immutable embedding model digest could not be resolved",
            file=sys.stderr,
        )
        return 2
    embedding_signature = f"{settings.embeddings.model}@{digest}"
    corpus_fingerprint = snapshot_hash(chunks)
    collection = _collection_name(name, settings, corpus_fingerprint, embedding_signature)

    milvus_settings = settings.milvus.model_copy(update={"uri": uri, "collection": collection})
    try:
        ingest_mode = _ingest_mode(args)
    except ValueError as exc:
        print(f"harness failed: {exc}", file=sys.stderr)
        return 2
    store = MilvusStore(
        milvus_settings,
        embedding_signature=embedding_signature,
        create_if_missing=ingest_mode != "no-ingest",
        allow_legacy_source=ingest_mode == "no-ingest",
    )
    ingest_report: IngestReport | None = None
    predecessor: MilvusStore | None = None

    try:
        expected_ids = {chunk.id for chunk in chunks}
        if ingest_mode == "no-ingest":
            print(f"reusing collection {collection} (no ingest)")
        else:
            if ingest_mode == "full" and store.list_ids():
                raise IngestionError(
                    "full ingestion requires an empty target; use --ingest-mode incremental or --resume"
                )
            if args.reuse_from_collection:
                predecessor = MilvusStore(
                    milvus_settings.model_copy(
                        update={"collection": args.reuse_from_collection}
                    ),
                    embedding_signature=embedding_signature,
                    create_if_missing=False,
                    allow_legacy_source=True,
                )
            ingest_report = sync_collection(
                chunks,
                store,
                provider,
                predecessor,
                batch_size=settings.embeddings.batch_size,
            )

        actual_ids = store.list_ids()
        stored = len(actual_ids)
        if actual_ids != expected_ids:
            print(
                f"harness failed: collection {collection} does not match the requested snapshot",
                file=sys.stderr,
            )
            return 2
        retrieved, latency = _retrieve(
            store,
            provider,
            golden["queries"],
            settings.rag,
            warmup=args.warmup,
            repeats=args.repeats,
        )
        collection_fingerprint = store.fingerprint()
        embedding_runtime = _runtime_info(provider, digest)
    except (EmbeddingProviderError, IngestionError, MilvusStoreError) as exc:
        print(f"harness failed: {exc}", file=sys.stderr)
        return 2
    finally:
        if predecessor is not None:
            predecessor.close()
        store.close()

    metrics, diagnostics, annotated = _evaluate(
        chunks, golden, judgments, retrieved, latency, settings.rag.k
    )
    run_dir = _write_run(
        name=name,
        provider_name=provider_name,
        settings=settings,
        digest=digest,
        collection=collection,
        collection_fingerprint=collection_fingerprint,
        stored=stored,
        ingest_mode=ingest_mode,
        ingest_report=ingest_report,
        embedding_runtime=embedding_runtime,
        corpus_fingerprint=corpus_fingerprint,
        chunks=chunks,
        metrics=metrics,
        diagnostics=diagnostics,
        retrieved=annotated,
        latency_protocol={"warmup": args.warmup, "repeats": args.repeats},
        run_config={
            "config_file": str(args.config),
            "provider": provider_name,
            "corpus_dir": str(args.corpus_dir),
            "wikibooks_limit": wikibooks_limit,
            "milvus_uri": uri,
            "warmup": args.warmup,
            "repeats": args.repeats,
            "reuse_from_collection": args.reuse_from_collection,
        },
    )
    _print_report(metrics, diagnostics, settings.rag.k, run_dir)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_DIR / "section.json")
    parser.add_argument("--provider", choices=["ollama", "fake"], default=None)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--granularity", choices=["page", "section"], default=None)
    parser.add_argument("--k", type=int, default=None)
    parser.add_argument("--wikibooks-limit", type=_nonnegative_int, default=None)
    parser.add_argument("--milvus-uri", default=None)
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="permit writing to a non-loopback Milvus host (never within this harness)",
    )
    parser.add_argument("--warmup", type=_nonnegative_int, default=2, help="unmeasured retrieval warm-up queries")
    parser.add_argument("--repeats", type=_positive_int, default=3, help="measured passes over the golden set")
    parser.add_argument("--no-ingest", action="store_true", help="re-score an existing collection without re-embedding")
    parser.add_argument("--ingest-mode", choices=["full", "incremental"], default="full")
    parser.add_argument("--reuse-from-collection", default=None)
    parser.add_argument("--resume", action="store_true", help="resume the target incrementally")
    return parser.parse_args()


def _load_settings(config: dict, args: argparse.Namespace) -> Settings:
    """Merge environment-aware base settings, the experiment config and CLI overrides.

    The merged mapping is fully re-validated, so an invalid override (`--k -1`)
    fails instead of reaching retrieval.
    """

    base = get_settings()
    for section, key in (
        ("embeddings", "base_url"),
        ("llm", "base_url"),
        ("milvus", "uri"),
    ):
        if key in config.get(section, {}):
            raise ValueError(
                f"{section}.{key} is environment-specific and must be supplied through settings/env"
            )

    merged = {
        "embeddings": {**base.embeddings.model_dump(), **config.get("embeddings", {})},
        "milvus": {**base.milvus.model_dump(), **config.get("milvus", {})},
        "rag": {**base.rag.model_dump(), **config.get("rag", {})},
        "llm": {**base.llm.model_dump(), **config.get("llm", {})},
    }
    merged["milvus"].pop("uri", None)

    if args.granularity is not None:
        merged["rag"]["granularity"] = args.granularity
    if args.k is not None:
        merged["rag"]["k"] = args.k

    return Settings.model_validate(merged)


def _resolve_uri(args: argparse.Namespace, config: dict) -> str:
    if args.milvus_uri:
        return args.milvus_uri
    base_uri = get_settings().milvus.uri
    if base_uri and base_uri != DEFAULT_MILVUS_URI:
        return base_uri  # explicitly set through .env / environment

    name = config.get("name", "run")
    return str(REPO_ROOT / ".scratch" / "rag" / f"milvus_{name}.db")


def _is_remote(uri: str) -> bool:
    if not uri.startswith(("http://", "https://")):
        return False
    host = uri.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0].strip("[]")
    return host not in {"localhost", "127.0.0.1", "::1"}


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _validate_limit(name: str, value: object) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be an integer greater than or equal to zero")


def _collection_name(
    name: str,
    settings: Settings,
    corpus_fingerprint: str,
    embedding_signature: str,
) -> str:
    fingerprint = _hash_json(
        {
            "schema_version": SCHEMA_VERSION,
            "model": embedding_signature,
            "dimension": settings.milvus.dimension,
            "metric": settings.milvus.metric_type,
            "granularity": settings.rag.granularity,
        "max_text_length": settings.milvus.max_text_length,
        "index_type": settings.milvus.index_type,
        "index_m": settings.milvus.index_m,
        "index_ef_construction": settings.milvus.index_ef_construction,
            "corpus": corpus_fingerprint,
            "wikibooks_cleaner_version": WIKIBOOKS_CLEANER_VERSION,
        }
    )
    return f"{settings.milvus.collection}_{name}_{fingerprint[:12]}"


def _build_provider(name: str, settings) -> EmbeddingProvider:  # type: ignore[no-untyped-def]
    if name == "fake":
        return FakeEmbeddingProvider(dimension=settings.dimension)
    return OllamaEmbeddingProvider(settings)


def _model_digest(provider: EmbeddingProvider) -> str | None:
    getter = getattr(provider, "model_digest", None)
    return getter() if callable(getter) else None


def _load_sources(corpus_dir: Path, *, wikibooks_limit: int | None) -> list[ChunkSource]:
    sources: list[ChunkSource] = []

    wikibooks_dir = corpus_dir / "wikibooks"
    if not wikibooks_dir.exists():
        return sources

    documents = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(wikibooks_dir.glob("*.json"))
    ]
    if wikibooks_limit is not None:
        documents = documents[:wikibooks_limit]

    adapter = WikibooksAdapter()
    for document in documents:
        sources.append(
            adapter.parse(
                WikibooksPage(title=document["title"], wikitext=document["wikitext"]),
                eco_code=document.get("eco"),
                opening_name=document.get("opening_name"),
                url=document.get("url"),
            )
        )
    return sources


def _chunk_sources(sources: list[ChunkSource], granularity: str, max_bytes: int) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for source in sources:
        chunks.extend(chunk_source(source, granularity=granularity, max_bytes=max_bytes))  # type: ignore[arg-type]
    return chunks


def _ingest_mode(args: argparse.Namespace) -> str:
    if args.no_ingest:
        if args.resume or args.reuse_from_collection:
            raise ValueError("--no-ingest cannot be combined with --resume or predecessor reuse")
        return "no-ingest"
    if args.resume:
        return "incremental"
    if args.ingest_mode == "full" and args.reuse_from_collection:
        raise ValueError("predecessor reuse requires --ingest-mode incremental")
    return str(args.ingest_mode)


def _runtime_info(provider: EmbeddingProvider, digest: str) -> EmbeddingRuntime:
    getter = getattr(provider, "runtime_info", None)
    if callable(getter):
        runtime = getter()
        if runtime.model_digest is not None and runtime.model_digest != digest:
            raise IngestionError("embedding model digest changed during the run")
        if runtime.model_digest is None:
            return EmbeddingRuntime(
                processor=runtime.processor,
                model_digest=digest,
                vram_bytes=runtime.vram_bytes,
                ollama_version=runtime.ollama_version,
            )
        return runtime
    return EmbeddingRuntime(
        processor="unknown",
        model_digest=digest,
        vram_bytes=None,
        ollama_version=None,
    )


def _retrieve(
    store: MilvusStore,
    provider: EmbeddingProvider,
    entries: list[dict],
    rag_settings,  # type: ignore[no-untyped-def]
    *,
    warmup: int,
    repeats: int,
) -> tuple[dict[str, list[dict]], dict[str, list[float]]]:
    min_score = rag_settings.min_score or None

    for entry in entries[: max(warmup, 0)]:
        try:
            vector = provider.embed_query(entry["query"])
            store.search(vector, rag_settings.k, min_score=min_score)
        except (EmbeddingProviderError, MilvusStoreError):
            break  # warm-up is best effort; measured passes surface real failures

    embed_ms: list[float] = []
    search_ms: list[float] = []
    total_ms: list[float] = []
    retrieved: dict[str, list[dict]] = {}

    for _ in range(max(repeats, 1)):
        for entry in entries:
            start = time.perf_counter()
            vector = provider.embed_query(entry["query"])
            embedded = time.perf_counter()
            results = store.search(vector, rag_settings.k, min_score=min_score)
            searched = time.perf_counter()

            embed_ms.append((embedded - start) * 1000.0)
            search_ms.append((searched - embedded) * 1000.0)
            total_ms.append((searched - start) * 1000.0)
            retrieved[entry["id"]] = [_to_document(result) for result in results]

    return retrieved, {"embed": embed_ms, "search": search_ms, "total": total_ms}


def _to_document(result) -> dict:  # type: ignore[no-untyped-def]
    chunk = result.chunk
    return {
        "id": chunk.id,
        "score": round(result.score, 4),
        "source": chunk.source,
        "source_url": chunk.source_url,
        "page_id": chunk.page_id,
        "section_title": chunk.section_title,
        "section_index": chunk.section_index,
        "part_index": chunk.part_index,
        "opening_name": chunk.opening_name,
        "eco_code": chunk.eco_code,
        "text": chunk.text,
    }


def _chunk_document(chunk: KnowledgeChunk) -> dict:
    return {"page_id": chunk.page_id, "section_title": chunk.section_title}


def _evaluate(
    chunks: list[KnowledgeChunk],
    golden: dict,
    judgments: dict,
    retrieved: dict[str, list[dict]],
    latency: dict[str, list[float]],
    k: int,
) -> tuple[dict, dict, dict]:
    relevant_counts = {
        entry["id"]: sum(
            1 for chunk in chunks if is_relevant(_chunk_document(chunk), judgments.get(entry["id"], {}))
        )
        for entry in golden["queries"]
    }

    per_query = {}
    diagnostics: dict[str, dict] = {}
    annotated: dict[str, list[dict]] = {}

    for entry in golden["queries"]:
        judgment = judgments.get(entry["id"], {})
        documents = retrieved[entry["id"]]
        annotated[entry["id"]] = [
            {**document, "relevant": is_relevant(document, judgment)} for document in documents
        ]
        if not is_judged(judgment):
            diagnostics[entry["id"]] = {
                "kind": judgment.get("kind", "unjudged"),
                "retrieved": len(documents),
                "top_score": documents[0]["score"] if documents else None,
            }
            continue
        per_query[entry["id"]] = evaluate_query(
            ranked_relevance(documents, judgment),
            relevant_counts[entry["id"]],
            k,
        )

    return summarize(per_query, latency), diagnostics, annotated


def _write_run(
    *,
    name: str,
    provider_name: str,
    settings: Settings,
    digest: str | None,
    collection: str,
    collection_fingerprint: str,
    stored: int,
    ingest_mode: str,
    ingest_report: IngestReport | None,
    embedding_runtime: EmbeddingRuntime,
    corpus_fingerprint: str,
    chunks: list[KnowledgeChunk],
    metrics: dict,
    diagnostics: dict,
    retrieved: dict,
    latency_protocol: dict,
    run_config: dict,
) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = RUNS_DIR / f"{stamp}_{name}"
    run_dir.mkdir(parents=True, exist_ok=False)

    unique_ids = {chunk.id for chunk in chunks}
    metadata = {
        "timestamp": stamp,
        "name": name,
        "git_sha": _git_sha(),
        "git_dirty": _git_dirty(),
        "provider": provider_name,
        "model": settings.embeddings.model,
        "model_digest": digest,
        "embedding_runtime": asdict(embedding_runtime),
        "embedding_runtime_scope": (
            "document_and_query_embeddings"
            if ingest_report is not None and ingest_report.embedded > 0
            else "query_embeddings_only"
        ),
        "embedding_dimension": settings.embeddings.dimension,
        "effective_config": run_config,
        "config_hash": _hash_json(
            {"settings": settings.model_dump(mode="json"), "run": run_config}
        ),
        "corpus_snapshot_hash": corpus_fingerprint,
        "wikibooks_cleaner_version": WIKIBOOKS_CLEANER_VERSION,
        "golden_set_hash": _hash_file(GOLDEN_SET_PATH),
        "judgments_hash": _hash_file(JUDGMENTS_PATH),
        "ingest_mode": ingest_mode,
        "ingest_report": asdict(ingest_report) if ingest_report is not None else None,
        "granularity": settings.rag.granularity,
        "k": settings.rag.k,
        "chunk_count": len(chunks),
        "unique_chunk_count": len(unique_ids),
        "collection": {
            "name": collection,
            "fingerprint": collection_fingerprint,
            "schema_version": SCHEMA_VERSION,
            "stored_count": stored,
        },
        "latency_protocol": latency_protocol,
        "metrics": metrics,
        "diagnostics": diagnostics,
        "retrieved": retrieved,
    }

    (run_dir / "effective-config.json").write_text(
        json.dumps(
            {"settings": settings.model_dump(mode="json"), "run": run_config}, indent=2
        ),
    )
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (run_dir / "run.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return run_dir


def _print_report(metrics: dict, diagnostics: dict, k: int, run_dir: Path) -> None:
    latency = metrics["latency_ms"]
    print(f"\nevaluated queries: {metrics['evaluated_query_count']}   k={k}")
    print(
        f"precision@1/3/5 {metrics['precision_at_1']:.3f}/"
        f"{metrics['precision_at_3']:.3f}/{metrics['precision_at_5']:.3f}  "
        f"recall@k {metrics['recall_at_k']:.3f}  mrr {metrics['mrr']:.3f}  "
        f"ndcg@k {metrics['ndcg_at_k']:.3f}  hit {metrics['hit_rate']:.3f}"
    )
    print(
        f"latency embed p50 {latency['embed']['p50']:.1f}ms  "
        f"search p50 {latency['search']['p50']:.1f}ms  "
        f"total p50 {latency['total']['p50']:.1f}ms / p95 {latency['total']['p95']:.1f}ms"
    )
    for query_id, query_metrics in metrics["per_query"].items():
        print(
            f"  {query_id:22s} recall {query_metrics['recall']:.3f}  "
            f"precision@1/3/5 {query_metrics['precision_at_1']:.3f}/"
            f"{query_metrics['precision_at_3']:.3f}/{query_metrics['precision_at_5']:.3f}  "
            f"ndcg {query_metrics['ndcg']:.3f}  rr {query_metrics['reciprocal_rank']:.3f}"
        )
    if diagnostics:
        print("  -- reported separately (not scored) --")
        for query_id, diag in diagnostics.items():
            print(f"  {query_id:22s} kind {diag['kind']}  retrieved {diag['retrieved']}  top {diag['top_score']}")
    print(f"\nrun written to {run_dir.relative_to(REPO_ROOT)}")


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def _git_dirty() -> bool:
    try:
        output = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return bool(output.strip())


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
