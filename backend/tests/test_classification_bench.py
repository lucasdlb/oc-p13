import json

import pytest

from backend.app.ingestion.classification_bench import (
    BenchClassifierResult,
    ClassificationBenchError,
    run_classification_bench,
    write_classification_bench_report,
)


class StaticClassifier:
    def __init__(self, results):
        self._results = list(results)

    def classify(self, row: dict) -> BenchClassifierResult:
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _row(**overrides) -> dict:
    row = {
        "id": "chunk-1",
        "page_id": "wikibooks::ruy-lopez",
        "section_title": "Plans",
        "text": "White puts pressure on e5 and prepares central development.",
        "intent": "misc",
    }
    row.update(overrides)
    return row


def test_bench_records_disagreements_and_misc_reduction() -> None:
    report = run_classification_bench(
        [_row()],
        classifier=StaticClassifier(
            [
                BenchClassifierResult(
                    label="plan",
                    confidence=0.82,
                    reason_codes=("teaching_plan",),
                    provider="typesafe",
                    model="jev-test",
                    config_id="cfg-1",
                )
            ]
        ),
        generated_at="2026-10-04T00:00:00+00:00",
    )

    assert report["counts"]["chunks"] == 1
    assert report["counts"]["disagreements"] == 1
    assert report["counts"]["misc_reduction_candidates"] == 1
    assert report["counts"]["pollution_risk_increases"] == 0
    assert report["disagreements"] == [
        {
            "chunk_id": "chunk-1",
            "page_id": "wikibooks::ruy-lopez",
            "section_title": "Plans",
            "text_preview": "White puts pressure on e5 and prepares central development.",
            "rule_label": "misc",
            "jev_label": "plan",
            "effective_label": "plan",
            "jev_confidence": 0.82,
            "fallback_reason": None,
            "reason_codes": ["teaching_plan"],
            "provider": "typesafe",
            "model": "jev-test",
            "config_id": "cfg-1",
        }
    ]


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (BenchClassifierResult(label="plan", confidence=0.2), "low_confidence"),
        (BenchClassifierResult(label="not-a-label", confidence=0.9), "invalid_label"),
        (RuntimeError("provider unavailable"), "provider_unavailable"),
    ],
)
def test_bench_falls_back_to_rule_label(result, reason: str) -> None:
    report = run_classification_bench(
        [_row(intent="candidate_move")],
        classifier=StaticClassifier([result]),
        confidence_threshold=0.5,
        generated_at="2026-10-04T00:00:00+00:00",
    )

    comparison = report["comparisons"][0]
    assert comparison["rule_label"] == "candidate_move"
    assert comparison["effective_label"] == "candidate_move"
    assert comparison["fallback_reason"] == reason


def test_bench_flags_history_or_misc_pollution_risk() -> None:
    report = run_classification_bench(
        [_row(intent="plan")],
        classifier=StaticClassifier([BenchClassifierResult(label="history", confidence=0.8)]),
        generated_at="2026-10-04T00:00:00+00:00",
    )

    assert report["counts"]["pollution_risk_increases"] == 1


def test_bench_rejects_invalid_rule_labels() -> None:
    with pytest.raises(ClassificationBenchError):
        run_classification_bench([_row(intent="unknown")], classifier=StaticClassifier([]))


def test_write_report_creates_parent_and_json(tmp_path) -> None:
    report = run_classification_bench(
        [_row()],
        classifier=StaticClassifier([BenchClassifierResult(label="misc", confidence=0.9)]),
        generated_at="2026-10-04T00:00:00+00:00",
    )

    path = tmp_path / "nested" / "report.json"
    write_classification_bench_report(report, path)

    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1
