"""Temporary rule-vs-JEV classification benchmark support.

This module is deliberately report-only: it compares the deterministic section
label already present on a chunk row with a challenger classifier result, but it
does not write corpus snapshots, Milvus metadata, or runtime configuration.
"""

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from backend.app.ingestion.classifier import INTENT_VOCABULARY


class ClassificationBenchError(RuntimeError):
    """Raised when the bench input is not comparable."""


@dataclass(frozen=True)
class BenchClassifierResult:
    label: str
    confidence: float
    reason_codes: tuple[str, ...] = ()
    provider: str | None = None
    model: str | None = None
    config_id: str | None = None


class BenchClassifier(Protocol):
    def classify(self, row: dict) -> BenchClassifierResult: ...


def run_classification_bench(
    rows: Iterable[dict],
    *,
    classifier: BenchClassifier,
    confidence_threshold: float = 0.5,
    generated_at: str | None = None,
) -> dict:
    if not 0.0 <= confidence_threshold <= 1.0:
        raise ValueError("confidence_threshold must be between 0 and 1")

    comparisons: list[dict] = []
    disagreements: list[dict] = []
    rule_counts: Counter[str] = Counter()
    jev_counts: Counter[str] = Counter()
    effective_counts: Counter[str] = Counter()
    fallback_counts: Counter[str] = Counter()
    misc_reduction_candidates = 0
    pollution_risk_increases = 0

    for row in rows:
        rule_label = _rule_label(row)
        rule_counts[rule_label] += 1
        result, fallback_reason = _classify_safely(classifier, row, confidence_threshold)
        if result.label in INTENT_VOCABULARY:
            jev_counts[result.label] += 1
        if fallback_reason:
            fallback_counts[fallback_reason] += 1
        effective_label = rule_label if fallback_reason else result.label
        effective_counts[effective_label] += 1

        comparison = {
            "chunk_id": row.get("id"),
            "page_id": row.get("page_id"),
            "section_title": row.get("section_title"),
            "text_preview": _preview(row.get("text", "")),
            "rule_label": rule_label,
            "jev_label": result.label,
            "effective_label": effective_label,
            "jev_confidence": result.confidence,
            "fallback_reason": fallback_reason,
            "reason_codes": list(result.reason_codes),
            "provider": result.provider,
            "model": result.model,
            "config_id": result.config_id,
        }
        comparisons.append(comparison)

        if result.label != rule_label or fallback_reason:
            disagreements.append(comparison)
        if rule_label == "misc" and effective_label not in {"misc", "history"}:
            misc_reduction_candidates += 1
        if rule_label not in {"misc", "history"} and effective_label in {"misc", "history"}:
            pollution_risk_increases += 1

    return {
        "schema_version": 1,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "label_vocabulary": list(INTENT_VOCABULARY),
        "confidence_threshold": confidence_threshold,
        "counts": {
            "chunks": len(comparisons),
            "disagreements": len(disagreements),
            "misc_reduction_candidates": misc_reduction_candidates,
            "pollution_risk_increases": pollution_risk_increases,
            "fallbacks": dict(fallback_counts),
            "rule_labels": dict(rule_counts),
            "jev_labels": dict(jev_counts),
            "effective_labels": dict(effective_counts),
        },
        "disagreements": disagreements,
        "comparisons": comparisons,
    }


def write_classification_bench_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _rule_label(row: dict) -> str:
    label = row.get("intent") or "misc"
    if label not in INTENT_VOCABULARY:
        raise ClassificationBenchError(f"chunk {row.get('id')!r} has unknown rule label {label!r}")
    return label


def _classify_safely(
    classifier: BenchClassifier,
    row: dict,
    confidence_threshold: float,
) -> tuple[BenchClassifierResult, str | None]:
    try:
        result = classifier.classify(row)
    except Exception:
        return BenchClassifierResult(label=_rule_label(row), confidence=0.0), "provider_unavailable"

    if result.label not in INTENT_VOCABULARY:
        return result, "invalid_label"
    if result.confidence < confidence_threshold:
        return result, "low_confidence"
    return result, None


def _preview(text: str, *, max_chars: int = 240) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "…"
