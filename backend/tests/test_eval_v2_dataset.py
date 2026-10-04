"""Validate the frozen Eval V2 dataset (issue 06)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

DATASET_PATH = (
    Path(__file__).resolve().parents[2] / "experiments" / "rag" / "eval_v2" / "dataset.json"
)

REQUIRED_FIELDS = {
    "id",
    "split",
    "category",
    "intent",
    "support",
    "position",
    "fen",
    "moves",
    "current_opening",
    "current_eco",
    "opening_node_id",
    "page_id",
    "question",
    "expected_context",
}
EXPECTED_CONTEXT_KEYS = {"current_prose", "child_prose_allowed", "forbidden"}


@pytest.fixture(scope="module")
def dataset() -> dict:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def _test_hash(cases: list[dict]) -> str:
    test_cases = sorted((c for c in cases if c["split"] == "test"), key=lambda c: c["id"])
    canonical = json.dumps(test_cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_dataset_loads(dataset: dict):
    assert dataset["schema_version"] == 1
    assert isinstance(dataset["cases"], list)
    assert len(dataset["cases"]) == dataset["counts"]["total"]


def test_every_case_has_required_fields(dataset: dict):
    for case in dataset["cases"]:
        missing = REQUIRED_FIELDS - set(case)
        assert not missing, f"{case['id']} missing {sorted(missing)}"
        assert set(case["expected_context"]) == EXPECTED_CONTEXT_KEYS, case["id"]
        assert case["split"] in {"dev", "test"}, case["id"]


def test_vocabularies_are_respected(dataset: dict):
    intents = set(dataset["intent_vocabulary"])
    categories = set(dataset["category_vocabulary"])
    supports = set(dataset["support_vocabulary"])
    for case in dataset["cases"]:
        assert case["intent"] in intents, case["id"]
        assert case["category"] in categories, case["id"]
        assert case["support"] in supports, case["id"]


def test_categories_covered(dataset: dict):
    present = {c["category"] for c in dataset["cases"]}
    assert present == set(dataset["category_vocabulary"])


def test_every_category_has_a_test_case(dataset: dict):
    test_categories = {c["category"] for c in dataset["cases"] if c["split"] == "test"}
    assert test_categories == set(dataset["category_vocabulary"])


def test_test_split_is_frozen(dataset: dict):
    assert _test_hash(dataset["cases"]) == dataset["test_split_sha256"]


def test_support_shapes(dataset: dict):
    for case in dataset["cases"]:
        if case["support"] == "in_theory":
            assert case["expected_context"]["current_prose"], case["id"]
            if case["position"] is not None:
                assert case["opening_node_id"], case["id"]
        elif case["support"] in {"out_of_theory", "unsupported"}:
            assert case["expected_context"]["current_prose"] == [], case["id"]
        if case["support"] == "unsupported":
            assert any("fabricat" in f for f in case["expected_context"]["forbidden"]), case["id"]
