"""Corpus-independent A/B evaluation for intent routing."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.app.core.settings import get_settings
from backend.app.services.intent_router import (
    CandidateMove,
    IntentRouter,
    IntentRouterContext,
    JevIntentClassifier,
    _INTENTS,
    _ROUTABLE_INTENTS,
)
from experiments.rag.eval_v2.eval_dataset import load_router_dataset


DEFAULT_DATASET = Path(__file__).with_name("router.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    dataset = load_router_dataset(args.dataset)
    cases = dataset["cases"][: args.limit] if args.limit else dataset["cases"]
    settings = get_settings()
    jev_settings = settings.typesafe.model_copy(update={"enabled": True})
    arms = {
        "deterministic": IntentRouter(),
        "jev_restricted": IntentRouter(
            primary=JevIntentClassifier(settings=jev_settings, allowed_intents=_ROUTABLE_INTENTS),
            medium_confidence=jev_settings.medium_confidence,
        ),
        "jev_full": IntentRouter(
            primary=JevIntentClassifier(settings=jev_settings, allowed_intents=_INTENTS),
            medium_confidence=jev_settings.medium_confidence,
        ),
    }
    results: dict[str, dict] = {}
    for name, router in arms.items():
        decisions = {}
        latencies = []
        for case in cases:
            started = time.perf_counter()
            decision = router.classify(_context(case))
            latencies.append((time.perf_counter() - started) * 1000)
            decisions[case["id"]] = {
                "expected": case["expected_intent"],
                "intent": decision.intent,
                "source": decision.source,
                "reason_codes": list(decision.reason_codes),
                "latency_ms": latencies[-1],
            }
        results[name] = {
            "intent_accuracy": sum(d["intent"] == d["expected"] for d in decisions.values()) / (len(decisions) or 1),
            "mean_latency_ms": sum(latencies) / (len(latencies) or 1),
            "decisions": decisions,
        }
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(args.dataset),
        "case_count": len(cases),
        "arms": results,
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _context(case: dict) -> IntentRouterContext:
    candidates = (
        CandidateMove(san="Nf6", uci="g8f6", opening_name="Berlin Defense", eco_code="C65", opening_node_id="berlin"),
        CandidateMove(san="a6", uci="a7a6", opening_name="Morphy Defense", eco_code="C70", opening_node_id="morphy"),
        CandidateMove(san="dxc4", uci="d5c4", opening_name="Queen's Gambit Accepted", eco_code="D20", opening_node_id="qga"),
    )
    return IntentRouterContext(
        question=case.get("question"),
        level=case.get("level", "intermediaire"),
        moves=tuple(case.get("moves") or ()),
        fen=case.get("fen"),
        current_opening_name=None,
        current_eco=None,
        current_node_id=None,
        legal_child_moves=candidates,
    )


if __name__ == "__main__":
    raise SystemExit(main())
