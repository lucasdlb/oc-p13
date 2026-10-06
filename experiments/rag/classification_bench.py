"""Run the temporary rule-vs-JEV Wikibooks section classification bench.

The output is diagnostic only. It is written under ``.scratch`` by default and
must not be used to update snapshots, Milvus metadata, or runtime config without
a later deterministic rule change.

Run: ``uv run python -m experiments.rag.classification_bench``
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import httpx

from backend.app.core.settings import TypeSafeSettings, get_settings
from backend.app.ingestion.classification_bench import (
    BenchClassifierResult,
    run_classification_bench,
    write_classification_bench_report,
)
from backend.app.ingestion.classifier import INTENT_VOCABULARY


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHUNKS = REPO_ROOT / ".scratch" / "rag" / "corpus" / "wikibooks-clean" / "chunks.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / ".scratch" / "rag" / "classification-bench" / "report.json"


class JevSectionClassifier:
    def __init__(self, settings: TypeSafeSettings, *, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.Client(timeout=settings.timeout_seconds)
        self._config_id = _config_id(settings)

    def classify(self, row: dict) -> BenchClassifierResult:
        if not self._settings.enabled:
            raise RuntimeError("JEV section classifier is disabled")
        if not self._settings.api_key:
            raise RuntimeError("TYPESAFE_API_KEY is required when JEV is enabled")

        response = self._client.post(
            _join_url(self._settings.base_url, "/v1/systemone"),
            headers={"Authorization": f"Bearer {self._settings.api_key}"},
            json={
                "model": self._settings.model,
                "state": {
                    "page_id": row.get("page_id"),
                    "canonical_title": row.get("canonical_title"),
                    "section_title": row.get("section_title"),
                    "text": row.get("text"),
                    "rule_label": row.get("intent"),
                    "opening_name": row.get("opening_name"),
                    "eco_code": row.get("eco_code"),
                    "opening_node_id": row.get("opening_node_id"),
                },
                "questions": {
                    "label": {
                        "type": "choice",
                        "instructions": "Classify this chess-opening prose section. Choose exactly one label.",
                        "criteria": {label: label for label in INTENT_VOCABULARY},
                    }
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("TypeSafe response must be an object")
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            raise ValueError("TypeSafe response must contain an answers object")
        answer = answers.get("label")
        if not isinstance(answer, dict):
            raise ValueError("TypeSafe response must contain an answer named 'label'")
        if answer.get("type") != "choice":
            raise ValueError("TypeSafe answer for 'label' must be a choice")
        label = answer.get("choice")
        confidence = answer.get("confidence")
        if not isinstance(label, str):
            raise ValueError("TypeSafe choice must be a string")
        if not isinstance(confidence, int | float):
            raise ValueError("TypeSafe confidence must be numeric")
        model = payload.get("model", self._settings.model)
        if model is not None and not isinstance(model, str):
            raise ValueError("TypeSafe model must be a string")
        return BenchClassifierResult(
            label=label,
            confidence=float(confidence),
            reason_codes=("jev_label",),
            provider="typesafe",
            model=model,
            config_id=self._config_id,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--confidence-threshold", type=float, default=None)
    parser.add_argument("--max-chunks", type=int, default=None)
    args = parser.parse_args()

    settings = get_settings().typesafe
    threshold = args.confidence_threshold
    if threshold is None:
        threshold = settings.medium_confidence

    try:
        rows = _load_rows(args.chunks, max_chunks=args.max_chunks)
        report = run_classification_bench(
            rows,
            classifier=JevSectionClassifier(settings),
            confidence_threshold=threshold,
        )
        write_classification_bench_report(report, args.output)
    except (OSError, ValueError) as exc:
        print(f"classification bench failed: {exc}", file=sys.stderr)
        return 2

    counts = report["counts"]
    print(f"chunks                 : {counts['chunks']}")
    print(f"disagreements          : {counts['disagreements']}")
    print(f"misc reduction         : {counts['misc_reduction_candidates']}")
    print(f"pollution risk increase: {counts['pollution_risk_increases']}")
    print(f"fallbacks              : {counts['fallbacks']}")
    print(f"report                 : {args.output}")
    return 0


def _load_rows(path: Path, *, max_chunks: int | None = None) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if max_chunks is not None:
        rows = rows[:max_chunks]
    return rows


def _config_id(settings: TypeSafeSettings) -> str:
    public_config = {
        "provider": "typesafe",
        "base_url": settings.base_url,
        "model": settings.model,
        "timeout_seconds": settings.timeout_seconds,
        "medium_confidence": settings.medium_confidence,
        "high_confidence": settings.high_confidence,
    }
    raw = json.dumps(public_config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


if __name__ == "__main__":
    raise SystemExit(main())
