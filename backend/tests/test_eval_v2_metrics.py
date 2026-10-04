"""Tests for Eval V2 metrics (issue 07)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.services.opening_tree import OpeningTree, build_opening_tree_snapshot
from experiments.rag.eval_v2 import metrics

DATASET_PATH = (
    Path(__file__).resolve().parents[2] / "experiments" / "rag" / "eval_v2" / "dataset.json"
)

RUY_LOPEZ_UCI = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"]
OPEN_GAME_UCI = ["e2e4", "e7e5"]
BERLIN_UCI = RUY_LOPEZ_UCI + ["g8f6"]
RIO_GAMBIT_UCI = BERLIN_UCI + ["e1g1", "f6e4"]
ITALIAN_UCI = ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4"]

PAGE = "wikibooks-chess-opening-theory::Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5"


@pytest.fixture(scope="module")
def dataset() -> dict:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tree(tmp_path_factory) -> OpeningTree:
    source_dir = tmp_path_factory.mktemp("chess-openings")
    output_dir = tmp_path_factory.mktemp("opening-tree")
    (source_dir / "a.tsv").write_text(
        "\n".join(
            [
                "eco\tname\tpgn",
                "B00\tKing's Pawn Game\t1. e4",
                "C20\tOpen Game\t1. e4 e5",
                "C50\tItalian Game\t1. e4 e5 2. Nf3 Nc6 3. Bc4",
                "C60\tRuy Lopez\t1. e4 e5 2. Nf3 Nc6 3. Bb5",
                "C65\tRuy Lopez: Berlin Defense\t1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6",
                "C67\tRuy Lopez: Berlin Defense, Rio Gambit\t1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6 4. O-O Nxe4",
            ]
        ),
        encoding="utf-8",
    )
    build_opening_tree_snapshot(source_dir, output_dir)
    return OpeningTree.from_snapshot_dir(output_dir)


def _node_id(tree: OpeningTree, uci: list[str]) -> str:
    node = tree.identify_by_uci(uci)
    assert node is not None
    return node.node_id


def _case(**overrides) -> dict:
    base = {
        "id": "c1",
        "split": "dev",
        "category": "current_opening_explanation",
        "intent": "explain_current_position",
        "support": "in_theory",
        "opening_node_id": None,
        "page_id": PAGE,
        "expected_context": {
            "current_prose": ["3. Bb5 · Ruy López or Spanish game"],
            "child_prose_allowed": [],
            "forbidden": ["History", "deep descendant prose"],
        },
    }
    base.update(overrides)
    return base


def _doc(**overrides) -> dict:
    base = {
        "id": "chunk-1",
        "page_id": PAGE,
        "section_title": "3. Bb5 · Ruy López or Spanish game",
        "opening_name": "Ruy Lopez",
        "eco_code": "C60",
        "opening_node_id": None,
        "intent": "intro",
        "is_history": False,
        "is_misc": False,
        "source_url": "https://en.wikibooks.org/wiki/Example",
        "license_or_terms": "CC BY-SA 4.0",
    }
    base.update(overrides)
    return base


def test_is_current_prose_matches_page_and_section() -> None:
    case = _case()
    assert metrics.is_current_prose(case, _doc())
    assert not metrics.is_current_prose(case, _doc(section_title="History"))
    assert not metrics.is_current_prose(case, _doc(page_id="other::Page"))


def test_history_and_misc_pollution_measured_separately() -> None:
    case = _case()
    history = _doc(section_title="History", is_history=True, intent="history")
    misc = _doc(section_title="Navigation", is_misc=True, intent="misc")
    assert metrics.is_history_pollution(case, history)
    assert not metrics.is_misc_pollution(case, history)
    assert not metrics.is_history_pollution(case, misc)
    assert metrics.is_misc_pollution(case, misc)


def test_history_current_prose_is_not_pollution() -> None:
    case = _case(
        intent="ask_history",
        category="history",
        expected_context={"current_prose": ["History"], "child_prose_allowed": [], "forbidden": []},
    )
    doc = _doc(section_title="History", is_history=True, intent="history")
    assert metrics.is_current_prose(case, doc)
    assert not metrics.is_history_pollution(case, doc)


def test_allowed_child_prose_by_name_and_node(tree) -> None:
    case = _case(
        id="next",
        intent="ask_next_moves",
        category="next_moves",
        opening_node_id=_node_id(tree, RUY_LOPEZ_UCI),
        expected_context={
            "current_prose": ["3. Bb5 · Ruy López or Spanish game"],
            "child_prose_allowed": ["Ruy Lopez: Berlin Defense"],
            "forbidden": ["deep descendant prose"],
        },
    )
    assert metrics.child_prose_allowed_for_case(case)

    by_name = _doc(
        opening_name="Ruy Lopez: Berlin Defense",
        opening_node_id=_node_id(tree, BERLIN_UCI),
        section_title="3...Nf6 · Berlin defence",
    )
    assert metrics.is_allowed_child_prose(case, by_name, tree)

    by_node = _doc(opening_name="Some other name", opening_node_id=_node_id(tree, BERLIN_UCI))
    assert metrics.is_allowed_child_prose(case, by_node, tree)

    unrelated = _doc(opening_name="Italian Game", opening_node_id=_node_id(tree, ITALIAN_UCI))
    assert not metrics.is_allowed_child_prose(case, unrelated, tree)


def test_child_prose_only_when_conditionally_allowed(tree) -> None:
    explain = _case(opening_node_id=_node_id(tree, RUY_LOPEZ_UCI))
    doc = _doc(opening_name="Ruy Lopez: Berlin Defense", opening_node_id=_node_id(tree, BERLIN_UCI))
    assert not metrics.is_allowed_child_prose(explain, doc, tree)


def test_deep_descendant_is_detected(tree) -> None:
    case = _case(opening_node_id=_node_id(tree, RUY_LOPEZ_UCI))
    deep = _doc(
        opening_name="Ruy Lopez: Berlin Defense, Rio Gambit",
        opening_node_id=_node_id(tree, RIO_GAMBIT_UCI),
    )
    assert metrics.is_deep_descendant(case, deep, tree)

    child = _doc(opening_node_id=_node_id(tree, BERLIN_UCI))
    assert not metrics.is_deep_descendant(case, child, tree)


def test_false_current_line_is_sibling_prose_not_deep_descendant(tree) -> None:
    case = _case(opening_node_id=_node_id(tree, RUY_LOPEZ_UCI))

    sibling = _doc(
        opening_name="Italian Game",
        opening_node_id=_node_id(tree, ITALIAN_UCI),
        page_id="wikibooks-chess-opening-theory::Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bc4",
        section_title="3. Bc4 · Italian game",
        intent="intro",
    )
    assert metrics.is_false_current_line(case, sibling, tree)

    deep = _doc(
        opening_name="Ruy Lopez: Berlin Defense, Rio Gambit",
        opening_node_id=_node_id(tree, RIO_GAMBIT_UCI),
        intent="candidate_move",
    )
    assert not metrics.is_false_current_line(case, deep, tree)


def test_current_prose_is_not_false_current_line_even_with_node_alias(tree) -> None:
    case = _case(opening_node_id=_node_id(tree, RUY_LOPEZ_UCI))
    current = _doc(
        opening_name="Ruy Lopez transposition",
        opening_node_id=_node_id(tree, BERLIN_UCI),
        section_title="3. Bb5 · Ruy López or Spanish game",
        intent="intro",
    )

    assert metrics.is_current_prose(case, current)
    assert not metrics.is_false_current_line(case, current, tree)


def test_parent_prose_has_own_label_and_is_not_false_current_line(tree) -> None:
    case = _case(opening_node_id=_node_id(tree, RUY_LOPEZ_UCI))
    parent = _doc(
        opening_name="Open Game",
        opening_node_id=_node_id(tree, OPEN_GAME_UCI),
        page_id="wikibooks-chess-opening-theory::Chess Opening Theory/1. e4/1...e5",
        section_title="1...e5 · Open Game",
        intent="intro",
    )

    assert metrics.document_labels(case, parent, tree) == [metrics.PARENT_PROSE]
    assert not metrics.is_false_current_line(case, parent, tree)
    result = metrics.score_case(case, [parent], tree)
    assert result.classification_counts[metrics.PARENT_PROSE] == 1
    assert result.false_current_line == 0.0


def test_current_node_other_prose_has_own_label(tree) -> None:
    current_id = _node_id(tree, RUY_LOPEZ_UCI)
    case = _case(opening_node_id=current_id)
    other_current = _doc(
        opening_node_id=current_id,
        section_title="Plans",
        intent="plan",
    )

    assert metrics.document_labels(case, other_current, tree) == [metrics.CURRENT_NODE_OTHER_PROSE]
    result = metrics.score_case(case, [other_current], tree)
    assert result.classification_counts[metrics.CURRENT_NODE_OTHER_PROSE] == 1
    assert not result.current_context_hit
    assert result.false_context_rate == 1.0


def test_false_current_line_out_of_theory_flags_any_theory_prose(tree) -> None:
    case = _case(
        support="out_of_theory",
        intent="ask_out_of_theory",
        category="out_of_theory",
        page_id=None,
        opening_node_id=None,
        expected_context={"current_prose": [], "child_prose_allowed": [], "forbidden": ["fabricated theory prose"]},
    )
    theory = _doc(opening_name="Ruy Lopez: Berlin Defense", opening_node_id=_node_id(tree, BERLIN_UCI))
    assert metrics.is_false_current_line(case, theory, tree)

    no_identity = _doc(opening_name=None, opening_node_id=None, eco_code=None)
    assert not metrics.is_false_current_line(case, no_identity, tree)


def test_source_attribution_requires_url_license_and_page() -> None:
    assert metrics.has_source_attribution(_doc())
    assert not metrics.has_source_attribution(_doc(source_url=None))
    assert not metrics.has_source_attribution(_doc(license_or_terms=None))
    assert not metrics.has_source_attribution(_doc(page_id=None))


def test_score_case_gate_truth_table(tree) -> None:
    current_id = _node_id(tree, RUY_LOPEZ_UCI)
    base = _case(opening_node_id=current_id)

    good = metrics.score_case(base, [_doc()])
    assert good.current_context_hit
    assert good.child_context_hit is None
    assert good.coach_usable_context

    polluted = metrics.score_case(base, [_doc(), _doc(section_title="History", is_history=True)])
    assert not polluted.coach_usable_context

    missing_current = metrics.score_case(base, [_doc(section_title="Other section", intent="misc", is_misc=True)])
    assert not missing_current.current_context_hit
    assert not missing_current.coach_usable_context

    out = _case(
        support="out_of_theory",
        intent="ask_out_of_theory",
        category="out_of_theory",
        page_id=None,
        opening_node_id=None,
        expected_context={"current_prose": [], "child_prose_allowed": [], "forbidden": ["fabricated theory prose"]},
    )
    empty = metrics.score_case(out, [])
    assert empty.coach_usable_context

    lied = metrics.score_case(out, [_doc(opening_node_id=_node_id(tree, BERLIN_UCI))])
    assert not lied.coach_usable_context


def test_score_case_child_hit(tree) -> None:
    case = _case(
        id="next",
        intent="ask_next_moves",
        category="next_moves",
        opening_node_id=_node_id(tree, RUY_LOPEZ_UCI),
        expected_context={
            "current_prose": ["3. Bb5 · Ruy López or Spanish game"],
            "child_prose_allowed": ["Ruy Lopez: Berlin Defense"],
            "forbidden": [],
        },
    )
    child = _doc(opening_name="Ruy Lopez: Berlin Defense", opening_node_id=_node_id(tree, BERLIN_UCI))
    result = metrics.score_case(case, [child], tree)
    assert result.child_context_hit is True
    assert result.classification_counts["allowed_child_prose"] == 1


def test_ranking_metrics_reuse_scoring() -> None:
    case = _case()
    current = _doc()
    result = metrics.ranking_metrics(case, [current], None, k=5)
    assert result is not None
    assert result["recall"] == pytest.approx(1.0)
    assert result["ndcg"] == pytest.approx(1.0)
    assert result["reciprocal_rank"] == pytest.approx(1.0)
    assert result["hit"] is True


def test_ranking_metrics_none_for_out_of_theory() -> None:
    case = _case(support="out_of_theory")
    assert metrics.ranking_metrics(case, [_doc()], None, k=5) is None


def test_score_run_stratifies_real_dataset(dataset) -> None:
    report = metrics.score_run(dataset, {}, tree=None)

    assert set(report) == {"overall", "by_intent", "by_support", "by_split", "per_case"}
    assert set(report["by_intent"]) == set(dataset["intent_vocabulary"])
    assert set(report["by_support"]) == set(dataset["support_vocabulary"])
    assert set(report["by_split"]) == {"dev", "test"}
    assert len(report["per_case"]) == dataset["counts"]["total"]

    overall = report["overall"]
    assert overall["case_count"] == 20
    assert overall["current_context_hit_rate"] == 0.0
    # No documents: out_of_theory/unsupported cases are usable, in_theory are not.
    assert overall["coach_usable_context_rate"] == pytest.approx(4 / 20)


def test_score_run_reports_latency_when_provided(dataset) -> None:
    report = metrics.score_run(dataset, {}, tree=None, latency={"total": [1.0, 2.0, 3.0, 4.0]})
    latency = report["overall"]["latency_ms"]["total"]
    assert latency["mean"] == pytest.approx(2.5)
    assert latency["p50"] == pytest.approx(2.5)
    assert latency["p95"] > latency["p50"]
