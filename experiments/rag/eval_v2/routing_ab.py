"""JEV vs deterministic intent routing A/B harness.

Runs the Eval V2 dataset twice: once with deterministic rule-based routing and once
with TypeSafe JEV routing. Records intent decisions, fallback reasons, retrieval
metrics, and coach prose for each arm. Produces a JSON comparison report.

Run:
    uv run python -m experiments.rag.eval_v2.routing_ab \
        --collection chess_knowledge_fdfff4354c1c_33d349ba87d3_a608853c1518
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.app.core.settings import Settings, get_settings
from backend.app.ingestion.cli import _collection_provenance
from backend.app.ingestion.snapshot import SnapshotError, verify_snapshot
from backend.app.services.coach import CoachService, ConservativeCoachService, LlmCoachService
from backend.app.services.embeddings import (
    EmbeddingProvider,
    EmbeddingProviderError,
    OllamaEmbeddingProvider,
)
from backend.app.services.intent_router import IntentRouter, JevIntentClassifier
from backend.app.services.llm import OllamaLLMProvider
from backend.app.services.milvus import MilvusStore, MilvusStoreError
from backend.app.services.opening_tree import OpeningTree
from experiments.rag.eval_v2.metrics import score_run
from experiments.rag.eval_v2.retrieve import retrieve_cases


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CORPUS_DIR = REPO_ROOT / ".scratch" / "rag" / "corpus"
DEFAULT_SNAPSHOT_DIR = DEFAULT_CORPUS_DIR / "wikibooks-snapshot"
DEFAULT_OPENING_TREE_DIR = DEFAULT_CORPUS_DIR / "opening-tree"
DEFAULT_DATASET = Path(__file__).with_name("dataset.json")
DEFAULT_RUNS_DIR = Path(__file__).with_name("runs")


FALLBACK_SOURCES = {
    "fallback_after_provider_error",
    "fallback_after_low_confidence",
    "fallback_after_invalid_response",
}


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    provider = _build_provider(settings.embeddings)
    coach_provider: OllamaLLMProvider | None = None
    store: MilvusStore | None = None
    try:
        snapshot = verify_snapshot(
            args.snapshot_dir,
            opening_tree_dir=args.opening_tree_dir,
            eval_dataset_path=args.dataset,
        )
        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        cases = dataset["cases"]
        if args.limit:
            cases = cases[: args.limit]
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

        if args.coach == "llm":
            coach_provider = OllamaLLMProvider(settings.llm)
            coach_service: CoachService = LlmCoachService(provider=coach_provider)
        else:
            coach_service = ConservativeCoachService()

        deterministic_router = IntentRouter()
        jev_settings = settings.typesafe.model_copy(update={"enabled": True})
        jev_router = IntentRouter(
            primary=JevIntentClassifier(settings=jev_settings),
            medium_confidence=jev_settings.medium_confidence,
        )

        started_at = datetime.now(timezone.utc).isoformat()
        deterministic = _run_arm(
            "deterministic",
            cases,
            store,
            provider,
            tree,
            deterministic_router,
            coach_service,
            args,
        )
        jev = _run_arm(
            "jev",
            cases,
            store,
            provider,
            tree,
            jev_router,
            coach_service,
            args,
        )

        comparison = _compare(cases, deterministic, jev)
        report = {
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "collection": args.collection,
            "embedding_model": settings.embeddings.model,
            "embedding_model_digest": digest,
            "coach": args.coach,
            "config_hash": _config_hash(args, settings, digest),
            "case_count": len(cases),
            "deterministic": deterministic["summary"],
            "jev": jev["summary"],
            "comparison": comparison,
            "per_case": _per_case_report(cases, deterministic, jev),
        }
    except (EmbeddingProviderError, MilvusStoreError, SnapshotError, RuntimeError) as exc:
        print(f"routing ab failed: {exc}", file=sys.stderr)
        return 2
    finally:
        if store is not None:
            store.close()
        provider.close()
        if coach_provider is not None:
            coach_provider.close()

    run_dir = _write_run(args.runs_dir, report)
    print(f"wrote {run_dir}")
    return 0


def _run_arm(
    name: str,
    cases: list[dict],
    store: MilvusStore,
    provider: EmbeddingProvider,
    tree: OpeningTree,
    router: IntentRouter,
    coach_service: CoachService,
    args: argparse.Namespace,
) -> dict:
    started = time.perf_counter()
    retrieved, latency, pipeline = retrieve_cases(
        cases,
        store,
        provider,
        tree,
        k=args.k,
        min_score=args.min_score,
        router=router,
        coach_service=coach_service,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    report = score_run({"cases": cases}, retrieved, tree, k=args.k, latency=latency)
    return {
        "name": name,
        "retrieved": retrieved,
        "latency": latency,
        "pipeline": pipeline,
        "report": report,
        "elapsed_ms": elapsed_ms,
        "summary": _summarize(cases, report, pipeline),
    }


def _summarize(cases: list[dict], report: dict, pipeline: dict[str, dict]) -> dict:
    overall = report["overall"]
    intents: dict[str, int] = {}
    fallback_count = 0
    for case in cases:
        decision = pipeline[case["id"]]["intent_decision"]
        intent = decision["intent"]
        intents[intent] = intents.get(intent, 0) + 1
        if decision["source"] in FALLBACK_SOURCES:
            fallback_count += 1
    return {
        "intent_distribution": intents,
        "fallback_rate": fallback_count / len(cases) if cases else 0.0,
        "coach_usable_context_rate": overall["coach_usable_context_rate"],
        "false_current_line_rate": overall["false_current_line_rate"],
        "false_context_rate": overall["false_context_rate"],
        "child_context_hit_rate": overall["child_context_hit_rate"],
    }


def _compare(cases: list[dict], deterministic: dict, jev: dict) -> dict:
    det_pipeline = deterministic["pipeline"]
    jev_pipeline = jev["pipeline"]

    intent_agreements = 0
    intent_vs_ground_truth = {"deterministic": 0, "jev": 0}
    jev_fallbacks = 0
    latency_ms = {"deterministic": 0.0, "jev": 0.0}
    coach_text_agreements = 0
    coach_fallbacks = {"deterministic": 0, "jev": 0}

    for case in cases:
        det_decision = det_pipeline[case["id"]]["intent_decision"]
        jev_decision = jev_pipeline[case["id"]]["intent_decision"]
        ground_truth = case.get("intent")

        if det_decision["intent"] == jev_decision["intent"]:
            intent_agreements += 1
        if det_decision["intent"] == ground_truth:
            intent_vs_ground_truth["deterministic"] += 1
        if jev_decision["intent"] == ground_truth:
            intent_vs_ground_truth["jev"] += 1
        if jev_decision["source"] in FALLBACK_SOURCES:
            jev_fallbacks += 1

        det_total = deterministic["latency"]["total"][cases.index(case)]
        jev_total = jev["latency"]["total"][cases.index(case)]
        latency_ms["deterministic"] += det_total
        latency_ms["jev"] += jev_total

        det_coach = det_pipeline[case["id"]].get("coach_explanation", {})
        jev_coach = jev_pipeline[case["id"]].get("coach_explanation", {})
        if det_coach.get("text") == jev_coach.get("text"):
            coach_text_agreements += 1
        if det_coach.get("fallback_label"):
            coach_fallbacks["deterministic"] += 1
        if jev_coach.get("fallback_label"):
            coach_fallbacks["jev"] += 1

    n = len(cases) or 1
    return {
        "intent_agreement_rate": intent_agreements / n,
        "intent_accuracy": {
            "deterministic": intent_vs_ground_truth["deterministic"] / n,
            "jev": intent_vs_ground_truth["jev"] / n,
        },
        "jev_fallback_rate": jev_fallbacks / n,
        "coach_text_agreement_rate": coach_text_agreements / n,
        "coach_fallback_counts": coach_fallbacks,
        "mean_latency_ms": {
            "deterministic": latency_ms["deterministic"] / n,
            "jev": latency_ms["jev"] / n,
        },
        "coach_usable_context_rate_delta": (
            jev["summary"]["coach_usable_context_rate"]
            - deterministic["summary"]["coach_usable_context_rate"]
        ),
        "false_current_line_rate_delta": (
            jev["summary"]["false_current_line_rate"]
            - deterministic["summary"]["false_current_line_rate"]
        ),
        "false_context_rate_delta": (
            jev["summary"]["false_context_rate"]
            - deterministic["summary"]["false_context_rate"]
        ),
    }


def _per_case_report(cases: list[dict], deterministic: dict, jev: dict) -> dict:
    report: dict[str, dict] = {}
    det_pipeline = deterministic["pipeline"]
    jev_pipeline = jev["pipeline"]
    for index, case in enumerate(cases):
        case_id = case["id"]
        det_decision = det_pipeline[case_id]["intent_decision"]
        jev_decision = jev_pipeline[case_id]["intent_decision"]
        det_coach = det_pipeline[case_id].get("coach_explanation", {})
        jev_coach = jev_pipeline[case_id].get("coach_explanation", {})
        report[case_id] = {
            "ground_truth_intent": case.get("intent"),
            "deterministic": {
                "intent": det_decision["intent"],
                "source": det_decision["source"],
                "reason_codes": det_decision["reason_codes"],
                "latency_ms": deterministic["latency"]["total"][index],
                "coach_explanation": {
                    "text": det_coach.get("text"),
                    "fallback_label": det_coach.get("fallback_label"),
                },
            },
            "jev": {
                "intent": jev_decision["intent"],
                "source": jev_decision["source"],
                "reason_codes": jev_decision["reason_codes"],
                "latency_ms": jev["latency"]["total"][index],
                "coach_explanation": {
                    "text": jev_coach.get("text"),
                    "fallback_label": jev_coach.get("fallback_label"),
                },
            },
        }
    return report


def _config_hash(args: argparse.Namespace, settings: Settings, digest: str) -> str:
    config = {
        "collection": args.collection,
        "embedding_model": settings.embeddings.model,
        "embedding_digest": digest,
        "k": args.k,
        "min_score": args.min_score,
        "coach": args.coach,
        "typesafe_enabled": settings.typesafe.enabled,
        "typesafe_model": settings.typesafe.model,
        "typesafe_medium_confidence": settings.typesafe.medium_confidence,
    }
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _build_provider(settings) -> EmbeddingProvider:  # type: ignore[no-untyped-def]
    return OllamaEmbeddingProvider(settings)


def _write_run(runs_dir: Path, report: dict) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = runs_dir / "ab" / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return run_dir


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--milvus-uri", default=None)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--opening-tree-dir", type=Path, default=DEFAULT_OPENING_TREE_DIR)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument("--coach", choices=["conservative", "llm"], default="llm")
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
