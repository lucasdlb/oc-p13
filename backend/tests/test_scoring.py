import math

import pytest

from experiments.rag.scoring import (
    COVERAGE_GAP,
    OUT_OF_THEORY,
    QueryMetrics,
    evaluate_query,
    is_judged,
    is_relevant,
    percentile,
    ranked_relevance,
    summarize,
)


def _judgment(*, page_id: str, sections: list[str] | None = None, kind: str = "prose") -> dict:
    target: dict = {"page_id": page_id}
    if sections is not None:
        target["sections"] = sections
    return {"kind": kind, "relevant": [target]}


def test_is_relevant_matches_judged_section() -> None:
    document = {
        "page_id": "wikibooks::Page",
        "section_title": "Decline the gambit",
    }

    assert is_relevant(document, _judgment(page_id="wikibooks::Page", sections=["Decline the gambit"])) is True


def test_is_relevant_rejects_unjudged_section_of_same_page() -> None:
    document = {"page_id": "wikibooks::Page", "section_title": "Accept the gambit"}

    judgment = _judgment(page_id="wikibooks::Page", sections=["Decline the gambit"])
    assert is_relevant(document, judgment) is False


def test_is_relevant_rejects_other_page_even_with_matching_section_title() -> None:
    document = {"page_id": "wikibooks::Other", "section_title": "Decline the gambit"}

    judgment = _judgment(page_id="wikibooks::Page", sections=["Decline the gambit"])
    assert is_relevant(document, judgment) is False


def test_page_granularity_chunk_is_relevant_when_page_is_judged() -> None:
    document = {"page_id": "wikibooks::Page", "section_title": "Page"}

    judgment = _judgment(page_id="wikibooks::Page", sections=["Decline the gambit"])
    assert is_relevant(document, judgment) is True


def test_out_of_theory_and_coverage_gap_are_not_judged() -> None:
    assert is_judged({"kind": OUT_OF_THEORY, "relevant": []}) is False
    assert is_judged({"kind": COVERAGE_GAP, "relevant": []}) is False
    assert is_judged(None) is False


def test_ranked_relevance_preserves_order() -> None:
    documents = [{"page_id": "wikibooks::Other", "section_title": "X"}, {"page_id": "wikibooks::Page", "section_title": "Y"}]
    judgment = _judgment(page_id="wikibooks::Page", sections=["Y"])

    assert ranked_relevance(documents, judgment) == [False, True]


def test_evaluate_query_first_hit_is_perfect() -> None:
    metrics = evaluate_query([True, False, False], relevant_count=1, k=3)

    assert metrics == QueryMetrics(
        recall=1.0,
        reciprocal_rank=1.0,
        ndcg=1.0,
        hit=True,
        precision_at_1=1.0,
        precision_at_3=1 / 3,
        precision_at_5=1 / 5,
    )


def test_evaluate_query_second_hit_halves_reciprocal_rank() -> None:
    metrics = evaluate_query([False, True, False], relevant_count=1, k=3)

    assert metrics.reciprocal_rank == 0.5
    assert metrics.ndcg == pytest.approx(1.0 / math.log2(3))


def test_evaluate_query_partial_recall_uses_full_idcg() -> None:
    metrics = evaluate_query([True, True, False], relevant_count=3, k=3)

    assert metrics.recall == pytest.approx(2 / 3)
    idcg = 1 + 1 / math.log2(3) + 1 / math.log2(4)
    assert metrics.ndcg == pytest.approx((1 + 1 / math.log2(3)) / idcg)


def test_evaluate_query_reports_precision_at_fixed_cutoffs() -> None:
    metrics = evaluate_query([True, False, True, False, False], relevant_count=4, k=5)

    assert metrics.precision_at_1 == 1.0
    assert metrics.precision_at_3 == pytest.approx(2 / 3)
    assert metrics.precision_at_5 == pytest.approx(2 / 5)


def test_evaluate_query_without_relevant_documents_is_zero() -> None:
    metrics = evaluate_query([False, False, False], relevant_count=0, k=3)

    assert metrics == QueryMetrics(recall=0.0, reciprocal_rank=0.0, ndcg=0.0, hit=False)


def test_percentile_interpolates() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0]

    assert percentile(values, 50) == 30.0
    assert percentile(values, 95) == 48.0
    assert percentile([], 50) == 0.0


def test_summarize_averages_only_scored_queries_and_separates_latency() -> None:
    per_query = {
        "a": QueryMetrics(
            recall=1.0,
            reciprocal_rank=1.0,
            ndcg=1.0,
            hit=True,
            precision_at_1=1.0,
            precision_at_3=2 / 3,
            precision_at_5=2 / 5,
        ),
        "b": QueryMetrics(
            recall=0.0,
            reciprocal_rank=0.5,
            ndcg=0.5,
            hit=True,
            precision_at_1=0.0,
            precision_at_3=1 / 3,
            precision_at_5=1 / 5,
        ),
    }
    latency = {"embed": [10.0, 20.0], "search": [1.0, 2.0], "total": [11.0, 22.0]}

    summary = summarize(per_query, latency)

    assert summary["evaluated_query_count"] == 2
    assert summary["recall_at_k"] == 0.5
    assert summary["precision_at_1"] == 0.5
    assert summary["precision_at_3"] == 0.5
    assert summary["precision_at_5"] == pytest.approx(0.3)
    assert summary["mrr"] == 0.75
    assert summary["hit_rate"] == 1.0
    assert summary["latency_ms"]["embed"]["mean"] == 15.0
    assert summary["latency_ms"]["search"]["mean"] == 1.5
    assert summary["latency_ms"]["total"]["mean"] == 16.5
    assert summary["per_query"]["a"]["ndcg"] == 1.0
    assert summary["per_query"]["a"]["precision_at_5"] == pytest.approx(0.4)
