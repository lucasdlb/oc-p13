"""Retrieve Eval V2 cases from a Milvus collection and score them.

This runner is intentionally experiment-scoped. It validates the frozen snapshot,
opens an immutable collection read-only, emits the document shape expected by
``metrics.py``, and writes both retrieval artifacts and the scored report.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.app.core.settings import get_settings
from backend.app.ingestion.cli import _collection_provenance
from backend.app.ingestion.snapshot import SnapshotError, verify_snapshot
from backend.app.services.embeddings import (
    EmbeddingProvider,
    EmbeddingProviderError,
    FakeEmbeddingProvider,
    OllamaEmbeddingProvider,
)
from backend.app.services.intent_router import CandidateMove, IntentDecision, IntentRouter, IntentRouterContext
from backend.app.services.milvus import MilvusStore, MilvusStoreError
from backend.app.services.opening_tree import OpeningTree
from backend.app.services.coach import CoachFallbackError, CoachService
from backend.app.services.rag import RagService
from backend.app.services.retrieval_contracts import (
    OpeningTreeContext,
    RetrievedContext,
    build_coach_context,
)
from backend.app.services.retrieval_plan_builder import build_retrieval_plan
from experiments.rag.eval_v2.metrics import score_run


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CORPUS_DIR = REPO_ROOT / ".scratch" / "rag" / "corpus"
DEFAULT_SNAPSHOT_DIR = DEFAULT_CORPUS_DIR / "wikibooks-snapshot"
DEFAULT_OPENING_TREE_DIR = DEFAULT_CORPUS_DIR / "opening-tree"
DEFAULT_DATASET = Path(__file__).with_name("dataset.json")
DEFAULT_RUNS_DIR = Path(__file__).with_name("runs")


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    provider = _build_provider(args.provider, settings.embeddings)
    store: MilvusStore | None = None
    try:
        snapshot = verify_snapshot(
            args.snapshot_dir,
            opening_tree_dir=args.opening_tree_dir,
            eval_dataset_path=args.dataset,
        )
        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        tree = OpeningTree.from_snapshot_dir(args.opening_tree_dir)
        digest = provider.model_digest()
        if not digest:
            raise RuntimeError("immutable embedding model digest could not be resolved")
        signature = f"{settings.embeddings.model}@{digest}"
        milvus_settings = settings.milvus.model_copy(
            update={
                "uri": args.milvus_uri or settings.milvus.uri,
                "collection": args.collection,
            }
        )
        store = MilvusStore(
            milvus_settings,
            embedding_signature=signature,
            collection_provenance=_collection_provenance(snapshot),
            create_if_missing=False,
        )
        retrieved, latency, pipeline = retrieve_cases(
            dataset["cases"],
            store,
            provider,
            tree,
            k=args.k,
            min_score=settings.rag.min_score or None,
        )
        _reject_incomplete_retrieval(retrieved, pipeline)
        report = score_run(dataset, retrieved, tree, k=args.k, latency=latency)
    except (EmbeddingProviderError, MilvusStoreError, SnapshotError, RuntimeError) as exc:
        print(f"eval v2 retrieval failed: {exc}", file=sys.stderr)
        return 2
    finally:
        if store is not None:
            store.close()
        provider.close()

    run_dir = _write_run(
        args.runs_dir,
        collection=args.collection,
        snapshot=snapshot.manifest,
        model=settings.embeddings.model,
        model_digest=digest,
        k=args.k,
        retrieved=retrieved,
        latency=latency,
        pipeline=pipeline,
        report=report,
    )
    print(f"wrote {run_dir}")
    return 0


def _reject_incomplete_retrieval(
    retrieved: dict[str, list[dict]],
    pipeline: dict[str, dict],
) -> None:
    """Fail the run when retrieval degraded, instead of scoring a hollow report.

    ``RagService`` swallows store errors into ``fallback_reasons``; without this
    guard a broken store produces an all-empty run whose pollution metrics read
    as perfect.
    """
    store_failures = sorted(
        case_id
        for case_id, artifact in pipeline.items()
        if "rag_store_unavailable"
        in ((artifact.get("rag_result") or {}).get("fallback_reasons") or ())
    )
    if store_failures:
        preview = ", ".join(store_failures[:5])
        raise RuntimeError(
            f"rag store unavailable for {len(store_failures)}/{len(pipeline)} cases ({preview})"
        )

    empty = sorted(case_id for case_id, docs in retrieved.items() if not docs)
    if empty and len(empty) == len(retrieved):
        raise RuntimeError(f"every case retrieved zero documents ({len(empty)} cases)")
    if empty:
        print(
            f"warning: {len(empty)} cases retrieved no documents: {', '.join(empty)}",
            file=sys.stderr,
        )


def retrieve_cases(
    cases: list[dict],
    store: MilvusStore,
    provider: EmbeddingProvider,
    tree: OpeningTree,
    *,
    k: int,
    min_score: float | None,
    router: IntentRouter | None = None,
    coach_service: CoachService | None = None,
) -> tuple[dict[str, list[dict]], dict[str, list[float]], dict[str, dict]]:
    retrieved: dict[str, list[dict]] = {}
    pipeline: dict[str, dict] = {}
    latency = {"embed": [], "search": [], "total": []}
    router = router or IntentRouter()
    rag = RagService(embedding_provider=provider, store=store, min_score=min_score)
    for case in cases:
        query = _query_text(case)
        tree_context = tree.context_for_position(
            moves=case.get("moves") or (),
            fen=case.get("fen"),
        )
        decision = router.classify(_intent_context(case, tree_context))
        plan = build_retrieval_plan(tree_context, decision)
        started = time.perf_counter()
        result = rag.retrieve(plan, query)
        finished = time.perf_counter()
        latency["total"].append((finished - started) * 1000.0)
        documents = [_context_to_document(context) for context in result.contexts[:k]]
        retrieved[case["id"]] = documents
        pipeline[case["id"]] = {
            "tree_context": tree_context.to_artifact(),
            "intent_decision": _decision_artifact(decision),
            "retrieval_plan": plan.to_artifact(),
            "rag_result": result.to_artifact(),
        }
        if coach_service is not None:
            pipeline[case["id"]]["coach_explanation"] = _coach_explanation(
                coach_service,
                case,
                tree_context,
                result.contexts,
            )
    return retrieved, latency, pipeline


def _intent_context(case: dict, tree_context: OpeningTreeContext) -> IntentRouterContext:
    current = tree_context.current
    return IntentRouterContext(
        question=case.get("question"),
        level=case.get("level") or "intermediaire",
        moves=tuple(case.get("moves") or ()),
        fen=case.get("fen"),
        current_opening_name=current.opening_name if current else None,
        current_eco=current.eco_code if current else None,
        current_node_id=current.node_id if current else None,
        legal_child_moves=tuple(_candidate_move(child) for child in tree_context.children),
    )


def _candidate_move(child) -> CandidateMove:  # type: ignore[no-untyped-def]
    return CandidateMove(
        san=child.entry_move or (child.san[-1] if child.san else ""),
        uci=child.uci[-1] if child.uci else None,
        opening_name=child.opening_name,
        eco_code=child.eco_code,
        opening_node_id=child.node_id,
    )


def _decision_artifact(decision: IntentDecision) -> dict:
    return {
        "intent": decision.intent,
        "confidence": decision.confidence,
        "probabilities": dict(decision.probabilities) if decision.probabilities is not None else None,
        "matched_candidate_move": _candidate_artifact(decision.matched_candidate_move),
        "reason_codes": list(decision.reason_codes),
        "source": decision.source,
        "provider_model": decision.provider_model,
    }


def _candidate_artifact(candidate: CandidateMove | None) -> dict | None:
    if candidate is None:
        return None
    return {
        "san": candidate.san,
        "uci": candidate.uci,
        "opening_name": candidate.opening_name,
        "eco_code": candidate.eco_code,
        "opening_node_id": candidate.opening_node_id,
    }


def _query_text(case: dict) -> str:
    parts = [str(case.get("question") or "")]
    if case.get("current_opening"):
        parts.append(f"Opening: {case['current_opening']}")
    if case.get("position"):
        parts.append(f"Position: {case['position']}")
    if case.get("intent"):
        parts.append(f"Intent: {case['intent']}")
    return "\n".join(part for part in parts if part)


def _to_document(result) -> dict:  # type: ignore[no-untyped-def]
    chunk = result.chunk
    return {
        "id": chunk.id,
        "score": round(result.score, 4),
        "source": chunk.source,
        "source_url": chunk.source_url,
        "license_or_terms": chunk.license_or_terms,
        "page_id": chunk.page_id,
        "section_title": chunk.section_title,
        "section_index": chunk.section_index,
        "part_index": chunk.part_index,
        "opening_name": chunk.opening_name,
        "eco_code": chunk.eco_code,
        "opening_node_id": chunk.opening_node_id,
        "intent": chunk.intent,
        "is_history": chunk.is_history,
        "is_misc": chunk.is_misc,
        "text": chunk.text,
    }


def _context_to_document(context: RetrievedContext) -> dict:
    return {
        "id": context.chunk_id,
        "score": round(context.score, 4),
        "source": context.source,
        "source_url": context.source_url,
        "license_or_terms": context.license_or_terms,
        "page_id": context.page_id,
        "section_title": context.section_title,
        "section_index": context.section_index,
        "part_index": context.part_index,
        "opening_name": context.opening_name,
        "eco_code": context.eco_code,
        "opening_node_id": context.opening_node_id,
        "intent": context.intent,
        "is_history": context.is_history,
        "is_misc": context.is_misc,
        "relation_to_position": context.relation_to_position,
        "entry_move": context.entry_move,
        "text": context.text,
    }


def _write_run(
    runs_dir: Path,
    *,
    collection: str,
    snapshot: dict,
    model: str,
    model_digest: str,
    k: int,
    retrieved: dict,
    latency: dict,
    pipeline: dict,
    report: dict,
) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = runs_dir / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "retrieved.json").write_text(
        json.dumps(retrieved, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "pipeline.json").write_text(
        json.dumps(pipeline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "runner": {
                    "type": "pipeline",
                    "pipeline": "OpeningTreeContext -> IntentRouter -> RetrievalPlan -> RagService",
                },
                "collection": collection,
                "snapshot": {
                    "snapshot_id": snapshot.get("snapshot_id"),
                    "snapshot_hash": snapshot.get("snapshot_hash"),
                    "counts": snapshot.get("counts"),
                    "inputs": snapshot.get("inputs"),
                },
                "model": model,
                "model_digest": model_digest,
                "k": k,
                "latency_ms": latency,
                "pipeline_artifact": "pipeline.json",
                "retrieved": retrieved,
                "report": report,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return run_dir


def _coach_explanation(
    coach_service: CoachService,
    case: dict,
    tree_context: OpeningTreeContext,
    contexts: tuple[RetrievedContext, ...],
) -> dict:
    # Child prose must carry an entry_move for conditional framing; drop any
    # retrieved child context that is missing it so coach-context building does
    # not crash the experiment runner.
    usable_contexts = tuple(
        ctx
        for ctx in contexts
        if ctx.relation_to_position != "child" or ctx.entry_move
    )
    context = build_coach_context(
        tree_context=tree_context,
        retrieved_contexts=usable_contexts,
        fallbacks=(),
    )
    try:
        result = coach_service.explain(context, level=case.get("level") or "intermediaire")
    except CoachFallbackError as exc:
        return {"text": exc.text, "fallback_label": exc.fallback_label}
    return {"text": result.text, "fallback_label": result.fallback}


def _build_provider(name: str, settings) -> EmbeddingProvider:  # type: ignore[no-untyped-def]
    if name == "fake":
        return FakeEmbeddingProvider(settings.dimension)
    return OllamaEmbeddingProvider(settings)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--provider", choices=["ollama", "fake"], default="ollama")
    parser.add_argument("--milvus-uri", default=None)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--opening-tree-dir", type=Path, default=DEFAULT_OPENING_TREE_DIR)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--k", type=int, default=5)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
