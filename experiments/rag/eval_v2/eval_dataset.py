"""Load and validate the hand-authored Eval V2 datasets."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import chess


DEFAULT_DATASET = Path(__file__).with_name("retrieval.json")
REQUIRED_LEVELS = {"debutant", "intermediaire", "avance"}


class EvalDatasetError(ValueError):
    """Raised when an evaluation dataset violates its contract."""


def test_split_sha256(cases: list[dict[str, Any]]) -> str:
    frozen = sorted((case for case in cases if case.get("split") == "test"), key=lambda case: case["id"])
    payload = json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def computed_counts(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"dev": 0, "test": 0})
    by_split = {"dev": 0, "test": 0}
    for case in cases:
        split = case.get("split")
        category = case.get("category")
        if split not in by_split:
            raise EvalDatasetError(f"{case.get('id')}: invalid split {split!r}")
        by_split[split] += 1
        by_category[category][split] += 1
    return {"total": len(cases), "by_split": by_split, "by_category": dict(sorted(by_category.items()))}


def load_dataset(path: Path = DEFAULT_DATASET, *, validate: bool = True) -> dict[str, Any]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    if validate:
        validate_dataset(dataset, path=path)
    dataset["counts"] = computed_counts(dataset["cases"])
    return dataset


def load_router_dataset(path: Path) -> dict[str, Any]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    expected = set(dataset.get("intent_vocabulary", {}))
    for case in dataset.get("cases", []):
        if case.get("expected_intent") not in expected:
            raise EvalDatasetError(f"{case.get('id')}: unknown expected_intent")
        _validate_router_position(case)
    return dataset


def validate_dataset(dataset: dict[str, Any], *, path: Path | None = None) -> None:
    label = str(path or "dataset")
    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise EvalDatasetError(f"{label}: cases must be a non-empty list")
    intents = set(dataset.get("intent_vocabulary", {}))
    categories = set(dataset.get("category_vocabulary", {}))
    supports = set(dataset.get("support_vocabulary", {}))
    groups = {"standard", "adversarial_router"}
    ids: set[str] = set()
    for case in cases:
        case_id = case.get("id")
        if not case_id or case_id in ids:
            raise EvalDatasetError(f"{label}: duplicate or missing id {case_id!r}")
        ids.add(case_id)
        missing = {"id", "split", "category", "intent", "support", "moves", "fen", "question"} - set(case)
        if missing:
            raise EvalDatasetError(f"{case_id}: missing {sorted(missing)}")
        if case["intent"] not in intents:
            raise EvalDatasetError(f"{case_id}: unknown intent {case['intent']!r}")
        if case["category"] not in categories:
            raise EvalDatasetError(f"{case_id}: unknown category {case['category']!r}")
        if case["support"] not in supports:
            raise EvalDatasetError(f"{case_id}: unknown support {case['support']!r}")
        if case.get("eval_group", "standard") not in groups:
            raise EvalDatasetError(f"{case_id}: invalid eval_group")
        level = case.get("level", "intermediaire")
        if level not in REQUIRED_LEVELS:
            raise EvalDatasetError(f"{case_id}: invalid level {level!r}")
        _validate_position(case)
    expected_hash = dataset.get("test_split_sha256")
    if expected_hash != test_split_sha256(cases):
        raise EvalDatasetError(f"{label}: test split hash does not match the dataset")


def _validate_position(case: dict[str, Any]) -> None:
    moves = case.get("moves") or []
    fen = case.get("fen")
    if not moves:
        if fen is not None:
            raise EvalDatasetError(f"{case['id']}: empty moves require fen=null")
        return
    board = chess.Board()
    try:
        for move in moves:
            board.push_uci(move)
    except ValueError as exc:
        raise EvalDatasetError(f"{case['id']}: illegal UCI move sequence") from exc
    if fen is None or board.fen() != fen:
        raise EvalDatasetError(f"{case['id']}: moves and fen diverge")
    terminal = board.is_game_over()
    if terminal != bool(case.get("terminal", False)):
        raise EvalDatasetError(f"{case['id']}: terminal flag does not match board state")


def _validate_router_position(case: dict[str, Any]) -> None:
    if not case.get("moves"):
        return
    board = chess.Board()
    try:
        for move in case.get("moves") or []:
            board.push_uci(move)
    except ValueError as exc:
        raise EvalDatasetError(f"{case['id']}: illegal UCI move sequence") from exc
    if case.get("fen") is not None and board.fen() != case["fen"]:
        raise EvalDatasetError(f"{case['id']}: router moves and fen diverge")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an Eval V2 dataset.")
    parser.add_argument("dataset", type=Path, nargs="?", default=DEFAULT_DATASET)
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    print(f"valid: {args.dataset} ({dataset['counts']['total']} cases)")
    print(f"test split sha256: {dataset['test_split_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
