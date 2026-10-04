"""Offline CLI for full, incremental, resumable knowledge ingestion."""

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

from backend.app.core.settings import MilvusSettings, get_settings
from backend.app.ingestion.adapters import WIKIBOOKS_CLEANER_VERSION, WikibooksAdapter, WikibooksPage
from backend.app.ingestion.chunker import ChunkSection, ChunkSource, chunk_source
from backend.app.ingestion.classifier import classify_page
from backend.app.ingestion.opening_mapper import map_page, refine_section
from backend.app.ingestion.pipeline import IngestionError, snapshot_hash, sync_collection
from backend.app.ingestion.snapshot import Snapshot, SnapshotError, verify_snapshot
from backend.app.models.knowledge import KnowledgeChunk
from backend.app.services.embeddings import EmbeddingProviderError, FakeEmbeddingProvider, OllamaEmbeddingProvider
from backend.app.services.milvus import SCHEMA_VERSION, MilvusStore, MilvusStoreError
from backend.app.services.opening_tree import OpeningTree


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CORPUS_DIR = REPO_ROOT / ".scratch" / "rag" / "corpus"
DEFAULT_OPENING_TREE_DIR = DEFAULT_CORPUS_DIR / "opening-tree"
DEFAULT_EVAL_DATASET = REPO_ROOT / "experiments" / "rag" / "eval_v2" / "dataset.json"


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    granularity = args.granularity or settings.rag.granularity
    provider = (
        FakeEmbeddingProvider(settings.embeddings.dimension)
        if args.provider == "fake"
        else OllamaEmbeddingProvider(settings.embeddings)
    )
    stores: list[MilvusStore] = []
    try:
        snapshot = None
        if args.snapshot_dir is not None:
            if args.wikibooks_limit is not None:
                raise IngestionError("--wikibooks-limit cannot be used with --snapshot-dir")
            snapshot = verify_snapshot(
                args.snapshot_dir,
                opening_tree_dir=args.opening_tree_dir,
                eval_dataset_path=args.eval_dataset,
            )
            chunks = chunks_from_snapshot(snapshot)
        else:
            chunks = _load_chunks(
                args.corpus_dir,
                opening_tree_dir=args.opening_tree_dir,
                granularity=granularity,
                max_bytes=settings.milvus.max_text_length,
                limit=args.wikibooks_limit,
            )
        if not chunks:
            raise IngestionError("corpus produced no chunks")
        digest = provider.model_digest()
        if not digest:
            raise IngestionError("immutable embedding model digest could not be resolved")
        signature = f"{settings.embeddings.model}@{digest}"
        collection = _target_collection_name(
            settings.milvus,
            corpus_snapshot_hash=snapshot_hash(chunks),
            embedding_signature=signature,
            granularity=granularity,
            explicit_collection=args.collection,
            no_ingest=args.no_ingest,
        )
        target_settings = settings.milvus.model_copy(
            update={"uri": args.milvus_uri or settings.milvus.uri, "collection": collection}
        )
        if _is_remote(target_settings.uri) and not args.allow_remote:
            raise IngestionError("remote Milvus requires --allow-remote")
        mode = _ingest_mode(args)
        target = MilvusStore(
            target_settings,
            embedding_signature=signature,
            collection_provenance=_collection_provenance(snapshot),
            create_if_missing=mode != "no-ingest",
            allow_legacy_source=mode == "no-ingest",
        )
        stores.append(target)

        if mode == "no-ingest":
            expected = {chunk.id for chunk in chunks}
            actual = target.list_ids()
            if actual != expected:
                raise IngestionError(
                    f"collection is not the requested complete snapshot ({len(actual)} IDs, expected {len(expected)})"
                )
            print(json.dumps({"collection": collection, "mode": mode, "final_count": len(actual)}))
            return 0
        if mode == "full" and target.list_ids():
            raise IngestionError("full ingestion requires an empty target; use incremental or --resume")

        predecessor = None
        if args.reuse_from_collection:
            predecessor = MilvusStore(
                target_settings.model_copy(update={"collection": args.reuse_from_collection}),
                embedding_signature=signature,
                create_if_missing=False,
                allow_legacy_source=True,
            )
            stores.append(predecessor)
        report = sync_collection(
            chunks,
            target,
            provider,
            predecessor,
            batch_size=settings.embeddings.batch_size,
        )
        print(json.dumps({"collection": collection, "mode": mode, **asdict(report)}, indent=2))
        return 0
    except (EmbeddingProviderError, IngestionError, MilvusStoreError, SnapshotError, ValueError) as exc:
        print(f"ingestion failed: {exc}", file=sys.stderr)
        return 2
    finally:
        for store in stores:
            store.close()
        provider.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--snapshot-dir", type=Path, default=None)
    parser.add_argument("--opening-tree-dir", type=Path, default=DEFAULT_OPENING_TREE_DIR)
    parser.add_argument("--eval-dataset", type=Path, default=DEFAULT_EVAL_DATASET)
    parser.add_argument("--granularity", choices=["page", "section"], default=None)
    parser.add_argument("--wikibooks-limit", type=_nonnegative_int, default=None)
    parser.add_argument("--provider", choices=["ollama", "fake"], default="ollama")
    parser.add_argument("--milvus-uri", default=None)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--ingest-mode", choices=["full", "incremental"], default="full")
    parser.add_argument("--reuse-from-collection", default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-ingest", action="store_true")
    parser.add_argument("--allow-remote", action="store_true")
    return parser.parse_args()


def chunks_from_snapshot(snapshot: Snapshot) -> list[KnowledgeChunk]:
    return [_chunk_from_snapshot_row(row) for row in snapshot.chunks]


def _chunk_from_snapshot_row(row: dict) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=row["id"],
        text=row["text"],
        source=row["source"],
        page_id=row["page_id"],
        canonical_title=row["canonical_title"],
        section_index=row.get("section_index"),
        part_index=row.get("part_index", 0),
        section_title=row.get("section_title"),
        source_url=row.get("source_url"),
        license_or_terms=row.get("license_or_terms"),
        opening_name=row.get("opening_name"),
        eco_code=row.get("eco_code"),
        opening_node_id=row.get("opening_node_id"),
        line_pgn=row.get("line_pgn"),
        intent=row.get("intent") or "misc",
        side=row.get("side"),
        is_history=bool(row.get("is_history")),
        is_misc=bool(row.get("is_misc", True)),
        created_at=row.get("created_at") or "",
    )


def _collection_provenance(snapshot: Snapshot | None) -> dict | None:
    if snapshot is None:
        return None
    return {
        "source": snapshot.manifest.get("source"),
        "snapshot_id": snapshot.manifest.get("snapshot_id"),
        "snapshot_hash": snapshot.snapshot_hash,
        "versions": snapshot.manifest.get("versions", {}),
        "inputs": snapshot.manifest.get("inputs", {}),
        "components": snapshot.manifest.get("components", {}),
        "counts": snapshot.manifest.get("counts", {}),
    }


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


def _load_chunks(
    corpus_dir: Path,
    *,
    opening_tree_dir: Path,
    granularity: str,
    max_bytes: int,
    limit: int | None,
) -> list[KnowledgeChunk]:
    wikibooks_dir = corpus_dir / "wikibooks"
    if not wikibooks_dir.exists():
        return []
    paths = sorted(wikibooks_dir.glob("*.json"))
    if limit is not None:
        paths = paths[:limit]
    if opening_tree_dir.exists():
        return _load_mapped_wikibooks_chunks(
            paths,
            opening_tree_dir=opening_tree_dir,
            granularity=granularity,
            max_bytes=max_bytes,
        )
    adapter = WikibooksAdapter()
    sources: list[ChunkSource] = []
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        sources.append(
            adapter.parse(
                WikibooksPage(title=document["title"], wikitext=document["wikitext"]),
                eco_code=document.get("eco"),
                opening_name=document.get("opening_name"),
                url=document.get("url"),
            )
        )
    return [
        chunk
        for source in sources
        for chunk in chunk_source(source, granularity=granularity, max_bytes=max_bytes)  # type: ignore[arg-type]
    ]


def _load_mapped_wikibooks_chunks(
    paths: list[Path],
    *,
    opening_tree_dir: Path,
    granularity: str,
    max_bytes: int,
) -> list[KnowledgeChunk]:
    tree = OpeningTree.from_snapshot_dir(opening_tree_dir)
    chunks: list[KnowledgeChunk] = []
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        result = classify_page(document["title"], document["wikitext"])
        if result.status == "rejected":
            continue
        page_mapping = map_page(result.title, tree)
        section_mappings = [
            refine_section(page_mapping, section.title, tree) or page_mapping
            for section in result.sections
            if section.text.strip()
        ]
        source = ChunkSource(
            source="wikibooks-chess-opening-theory",
            page_title=result.title,
            page_text=result.page_text,
            source_url=document.get("url"),
            license_or_terms="CC BY-SA 4.0",
            sections=tuple(
                ChunkSection(
                    title=section.title,
                    text=section.text,
                    intent=section.intent,
                    side=section.side,
                    is_history=section.is_history,
                    is_misc=section.is_misc,
                )
                for section in result.sections
                if section.text.strip()
            ),
        )
        for chunk in chunk_source(source, granularity=granularity, max_bytes=max_bytes):  # type: ignore[arg-type]
            mapping = page_mapping
            if chunk.section_index is not None:
                mapping = section_mappings[chunk.section_index]
            chunks.append(
                replace(
                    chunk,
                    opening_name=mapping.opening_name,
                    eco_code=mapping.eco_code,
                    opening_node_id=mapping.node_id,
                    line_pgn=mapping.line_pgn,
                )
            )
    return chunks


def _collection_name(
    settings: MilvusSettings,
    corpus_snapshot_hash: str,
    embedding_signature: str,
    granularity: str,
) -> str:
    identity = {
        "schema_version": SCHEMA_VERSION,
        "embedding": embedding_signature,
        "dimension": settings.dimension,
        "metric": settings.metric_type,
        "granularity": granularity,
        "max_text_length": settings.max_text_length,
        "index_type": settings.index_type,
        "index_m": settings.index_m,
        "index_ef_construction": settings.index_ef_construction,
        "corpus": corpus_snapshot_hash,
        "wikibooks_cleaner_version": WIKIBOOKS_CLEANER_VERSION,
    }
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
    return f"{settings.collection}_{fingerprint[:12]}"


def _target_collection_name(
    settings: MilvusSettings,
    *,
    corpus_snapshot_hash: str,
    embedding_signature: str,
    granularity: str,
    explicit_collection: str | None,
    no_ingest: bool,
) -> str:
    if explicit_collection:
        return explicit_collection
    if no_ingest:
        return settings.collection
    return _collection_name(settings, corpus_snapshot_hash, embedding_signature, granularity)


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


if __name__ == "__main__":
    raise SystemExit(main())
