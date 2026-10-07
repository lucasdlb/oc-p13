"""Live coach evaluation and deterministic output checks.

The live mode calls the running API for every case. Replay mode validates a
JSON response file, which keeps the checks independently testable and makes
failed cases inspectable without another model call.

Examples::

    uv run python -m experiments.rag.eval_v2.coach_eval --live \
      --base-url http://localhost:8000 --out /tmp/coach-baseline.json
    uv run python -m experiments.rag.eval_v2.coach_eval \
      --responses /tmp/coach-baseline.json --out /tmp/coach-report.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

import chess
import httpx

ROOT = Path(__file__).resolve().parents[3]
BASE_DATASET = ROOT / "experiments/rag/eval_v2/retrieval.json"
GENERATION_DATASET = ROOT / "experiments/rag/eval_v2/generation.json"
TACTICAL_TERMS = (
    "attaque",
    "attaquer",
    "menace",
    "menacer",
    "defie",
    "defier",
    "sacrifie",
    "sacrifier",
    "fourchette",
    "cloue",
    "clouer",
    "mat",
)
_MOVE_MARKER = re.compile(r"\[\[move:uci=([^,\]]+)", re.IGNORECASE)
_CONCLUSION = re.compile(r"(?im)^\s*(?:#+\s*)?(?:conclusion|en conclusion|pour finir|en resume)\b")


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def load_cases() -> list[dict[str, Any]]:
    generation = json.loads(GENERATION_DATASET.read_text())
    cases_path = GENERATION_DATASET.with_name(generation.get("source_cases_file", "coach_eval_cases.json"))
    base = {case["id"]: case for case in json.loads(BASE_DATASET.read_text())["cases"]}
    cases = []
    for definition in json.loads(cases_path.read_text())["cases"]:
        source = base[definition["base_id"]]
        case = {**source, **definition}
        case["id"] = definition["id"]
        if not case.get("fen"):
            board = chess.Board()
            moves = case.get("moves") or ["e2e4"]
            for uci in moves:
                board.push_uci(uci)
            case["fen"] = board.fen()
            case["moves"] = moves
        cases.append(case)
    if len(cases) != 40:
        raise ValueError(f"coach evaluation must contain 40 cases, got {len(cases)}")
    return cases


def _legal_marker_errors(text: str, fen: str | None) -> list[str]:
    board = chess.Board(fen) if fen else chess.Board()
    errors = []
    for raw_uci in _MOVE_MARKER.findall(text):
        try:
            move = chess.Move.from_uci(raw_uci)
        except ValueError:
            errors.append(f"malformed UCI: {raw_uci}")
            continue
        if not board.is_legal(move):
            errors.append(f"illegal UCI: {raw_uci}")
    return errors


def _unsupported_tactical_terms(text: str, sources: list[str]) -> list[str]:
    source_text = _normalize(" ".join(sources))
    output_text = _normalize(text)
    return [term for term in TACTICAL_TERMS if term in output_text and term not in source_text]


def validate_response(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    text = str(response.get("text") or "")
    sources = [str(source) for source in response.get("sources", [])]
    normalized = _normalize(text)
    issues = _legal_marker_errors(text, case.get("fen"))
    issues.extend(f"unsourced tactical term: {term}" for term in _unsupported_tactical_terms(text, sources))

    criterion = case.get("criterion")
    if criterion and _normalize(str(criterion)) not in normalized:
        issues.append(f"criterion not named: {criterion}")

    conclusion_count = len(_CONCLUSION.findall(text))
    if conclusion_count != 1:
        issues.append(f"conclusion count: {conclusion_count}")

    word_count = len(re.findall(r"\b[\w']+\b", text, re.UNICODE))
    if not 100 <= word_count <= 220:
        issues.append(f"word count outside range: {word_count}")

    return {
        "id": case["id"],
        "passed": not issues,
        "issues": issues,
        "word_count": word_count,
        "conclusion_count": conclusion_count,
    }


def _live_responses(cases: list[dict[str, Any]], base_url: str, timeout: float) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        for case in cases:
            fen = case.get("fen") or chess.Board().fen()
            moves = case.get("moves") or ["e2e4"]
            request = {
                "fen": fen,
                "pgn": case.get("position") or "1. e4",
                "moves": moves,
                "level": "intermediaire",
                "question": case["question"],
            }
            try:
                analysis = client.post("/api/analyze-position", json=request)
                analysis.raise_for_status()
                run_id = analysis.json()["run_id"]
                rag = client.post("/api/rag-context", json={"run_id": run_id})
                rag.raise_for_status()
                client.post("/api/stockfish/analyze-run", json={"run_id": run_id}).raise_for_status()
                coach = client.post(
                    "/api/coach-explanation",
                    json={"run_id": run_id, "level": "intermediaire"},
                )
                coach.raise_for_status()
                rag_context = rag.json().get("rag_context", [])
                responses.append(
                    {
                        "id": case["id"],
                        "text": coach.json().get("explanation", ""),
                        "sources": [item.get("text", "") for item in rag_context],
                    }
                )
            except (httpx.HTTPError, KeyError) as exc:
                responses.append({"id": case["id"], "text": "", "sources": [], "error": str(exc)})
    return responses


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--base-url", default=os.getenv("COACH_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--responses", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    if args.live == bool(args.responses):
        parser.error("choose exactly one of --live or --responses")

    cases = load_cases()
    if args.live:
        responses = _live_responses(cases, args.base_url, args.timeout)
    else:
        responses = json.loads(args.responses.read_text())
    by_id = {response["id"]: response for response in responses}
    checks = [validate_response(case, by_id.get(case["id"], {})) for case in cases]
    report = {
        "case_count": len(cases),
        "passed": sum(check["passed"] for check in checks),
        "failed": sum(not check["passed"] for check in checks),
        "checks": checks,
        "responses": responses,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("case_count", "passed", "failed")}))


if __name__ == "__main__":
    main()
