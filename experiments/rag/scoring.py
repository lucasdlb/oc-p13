"""Golden-set scoring for the RAG harness.

Pure functions over retrieval results so they can be unit-tested without Milvus
or Ollama.

Relevance is a **passage-level** judgment frozen in `judgments.json`: a retrieved
document is relevant only when it comes from a judged source page (and, at
`section` granularity, a judged section) that actually contains the explanation
the query needs. Opening identity alone is not enough: a name lookup should not
score as a pedagogical answer.
"""

import math
from dataclasses import asdict, dataclass


PROSE = "prose"
OUT_OF_THEORY = "out_of_theory"
COVERAGE_GAP = "coverage_gap"


@dataclass(frozen=True)
class QueryMetrics:
    recall: float
    reciprocal_rank: float
    ndcg: float
    hit: bool
    precision_at_1: float = 0.0
    precision_at_3: float = 0.0
    precision_at_5: float = 0.0


def is_judged(judgment: dict | None) -> bool:
    return bool(judgment) and judgment.get("kind", PROSE) == PROSE


def is_relevant(document: dict, judgment: dict) -> bool:
    if not is_judged(judgment):
        return False

    page_id = document.get("page_id")
    section_title = document.get("section_title")

    for target in judgment.get("relevant") or []:
        if not page_id or page_id != target.get("page_id"):
            continue

        sections = target.get("sections")
        if sections is None:
            return True

        page_title = page_id.split("::", 1)[1] if "::" in page_id else None
        if section_title == page_title:
            return True  # a page-granularity chunk covers the whole judged page
        if section_title in sections:
            return True
    return False


def ranked_relevance(documents: list[dict], judgment: dict) -> list[bool]:
    return [is_relevant(document, judgment) for document in documents]


def evaluate_query(relevances: list[bool], relevant_count: int, k: int) -> QueryMetrics:
    top = relevances[:k]
    found = sum(1 for relevant in top if relevant)

    def precision_at(cutoff: int) -> float:
        return sum(1 for relevant in relevances[:cutoff] if relevant) / cutoff

    recall = found / relevant_count if relevant_count else 0.0

    reciprocal_rank = 0.0
    for rank, relevant in enumerate(top, start=1):
        if relevant:
            reciprocal_rank = 1.0 / rank
            break

    dcg = sum(1.0 / math.log2(rank + 1) for rank, relevant in enumerate(top, start=1) if relevant)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(relevant_count, k) + 1))
    ndcg = dcg / idcg if idcg else 0.0

    return QueryMetrics(
        recall=recall,
        reciprocal_rank=reciprocal_rank,
        ndcg=ndcg,
        hit=found > 0,
        precision_at_1=precision_at(1),
        precision_at_3=precision_at(3),
        precision_at_5=precision_at(5),
    )


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])

    rank = (p / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[low])
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarize(per_query: dict[str, QueryMetrics], latency: dict[str, list[float]]) -> dict:
    metrics = list(per_query.values())

    def mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    def latency_stats(samples: list[float]) -> dict[str, float]:
        return {
            "p50": percentile(samples, 50),
            "p95": percentile(samples, 95),
            "mean": mean(samples),
        }

    return {
        "evaluated_query_count": len(metrics),
        "recall_at_k": mean([metric.recall for metric in metrics]),
        "precision_at_1": mean([metric.precision_at_1 for metric in metrics]),
        "precision_at_3": mean([metric.precision_at_3 for metric in metrics]),
        "precision_at_5": mean([metric.precision_at_5 for metric in metrics]),
        "mrr": mean([metric.reciprocal_rank for metric in metrics]),
        "ndcg_at_k": mean([metric.ndcg for metric in metrics]),
        "hit_rate": mean([1.0 if metric.hit else 0.0 for metric in metrics]),
        "latency_ms": {
            "embed": latency_stats(latency.get("embed", [])),
            "search": latency_stats(latency.get("search", [])),
            "total": latency_stats(latency.get("total", [])),
        },
        "per_query": {query_id: asdict(metric) for query_id, metric in per_query.items()},
    }
