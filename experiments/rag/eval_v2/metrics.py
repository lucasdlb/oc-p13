"""Eval V2 metrics (issue 07).

Pure functions over retrieval results so they can be unit-tested without Milvus
or Ollama. Unlike eval v1 (``experiments/rag/scoring.py``), these metrics judge
whether retrieved context *helps the coach answer without making it lie*, not
just ranking quality. Ranking metrics (nDCG, MRR, Hit@k, Recall@k) remain
available as secondary diagnostics via ``scoring.evaluate_query`` and are never
the sole success signal.

Document shape
--------------

A retrieved document is a ``dict`` carrying the chunk metadata needed to
classify it against a case's ``expected_context``. It is a superset of eval v1's
``_to_document`` output; the extra fields are already stored on Milvus chunks
(``opening_node_id``, ``intent``, ``is_history``, ``is_misc``,
``license_or_terms``) and must be included when a runner emits results::

    {
        "page_id": "wikibooks-chess-opening-theory::Chess Opening Theory/...",
        "section_title": "3. Bb5 · Ruy López or Spanish game",
        "opening_name": "Ruy Lopez: Berlin Defense",   # may be None
        "eco_code": "C65",                             # may be None
        "opening_node_id": "<sha256>",                 # may be None
        "intent": "intro",                             # chunk-level intent
        "is_history": false,
        "is_misc": false,
        "source_url": "https://en.wikibooks.org/wiki/...",
        "license_or_terms": "CC BY-SA 4.0",
    }

Classification labels (see ``document_labels``) are independent, not mutually
exclusive: a single chunk can be both a deep descendant and history prose. The
pollution metrics are therefore measured separately, each as a rate over the
retrieved top-k.

``parent_prose`` and ``current_node_other_prose`` are fidelity labels, not
pollution labels: they distinguish deliberately retrieved parent context and
same-node prose outside the frozen expected section from true wrong-line prose.

Run::

    python -m experiments.rag.eval_v2.metrics \
        --run experiments/rag/eval_v2/runs/<name>/retrieved.json \
        --dataset experiments/rag/eval_v2/dataset.json \
        --opening-tree-dir .scratch/rag/corpus/opening-tree \
        --out experiments/rag/eval_v2/runs/<name>/report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from experiments.rag.eval_v2.eval_dataset import load_dataset
from typing import Any

from experiments.rag.scoring import evaluate_query, percentile

# Chunk-level intents that read like an explanation of a specific line. A chunk
# with one of these intents that belongs to a *different* line would make the
# coach describe the wrong line: that is a "false current line".
_PROSE_INTENTS = {"intro", "plan", "variation", "candidate_move"}

# Case-level intents that conditionally allow direct-child continuation prose.
_CHILD_ALLOWED_INTENTS = {"ask_next_moves", "ask_specific_candidate"}

# Classification label vocabulary.
CURRENT_PROSE = "current_prose"
PARENT_PROSE = "parent_prose"
CURRENT_NODE_OTHER_PROSE = "current_node_other_prose"
ALLOWED_CHILD_PROSE = "allowed_child_prose"
DEEP_DESCENDANT = "deep_descendant"
HISTORY = "history"
MISC = "misc"
FALSE_CURRENT_LINE = "false_current_line"
UNRELATED = "unrelated"

_ALL_LABELS = (
    CURRENT_PROSE,
    PARENT_PROSE,
    CURRENT_NODE_OTHER_PROSE,
    ALLOWED_CHILD_PROSE,
    DEEP_DESCENDANT,
    HISTORY,
    MISC,
    FALSE_CURRENT_LINE,
    UNRELATED,
)


def is_current_prose(case: dict, document: dict) -> bool:
    """True when the document is the expected current-line prose for the case.

    Matches the case's ``page_id`` (when set) and the cleaner's actual section
    title against ``expected_context.current_prose``.
    """
    page_id = case.get("page_id")
    if page_id and document.get("page_id") != page_id:
        return False
    section_title = document.get("section_title")
    current_prose = (case.get("expected_context") or {}).get("current_prose") or []
    return section_title is not None and section_title in current_prose


def child_prose_allowed_for_case(case: dict) -> bool:
    """Whether the case conditionally allows direct-child continuation prose."""
    if case.get("intent") not in _CHILD_ALLOWED_INTENTS:
        return False
    return bool((case.get("expected_context") or {}).get("child_prose_allowed"))


def _child_node_ids(tree: Any, node_id: str) -> tuple[str, ...]:
    try:
        return tuple(tree.retrieval_constraints(node_id, include_child_prose=True).child_node_ids)
    except Exception:
        return ()


def _parent_node_ids(tree: Any, node_id: str) -> tuple[str, ...]:
    try:
        return tuple(tree.retrieval_constraints(node_id).parent_node_ids)
    except Exception:
        return ()


def _deep_descendant_node_ids(tree: Any, node_id: str) -> tuple[str, ...]:
    try:
        return tuple(tree.retrieval_constraints(node_id).excluded_descendant_node_ids)
    except Exception:
        return ()


def is_allowed_child_prose(case: dict, document: dict, tree: Any = None) -> bool:
    """True when the document is a conditionally-allowed direct-child continuation."""
    if not child_prose_allowed_for_case(case):
        return False
    child_allowed = (case.get("expected_context") or {}).get("child_prose_allowed") or []

    opening_name = document.get("opening_name")
    if opening_name and opening_name in child_allowed:
        return True

    node_id = document.get("opening_node_id")
    current = case.get("opening_node_id")
    if tree is not None and node_id and current and node_id in _child_node_ids(tree, current):
        return True
    return False


def is_parent_prose(case: dict, document: dict, tree: Any = None) -> bool:
    """True when the document belongs to the case's immediate parent node."""
    node_id = document.get("opening_node_id")
    current = case.get("opening_node_id")
    if tree is None or not node_id or not current:
        return False
    return node_id in _parent_node_ids(tree, current)


def is_current_node_other_prose(case: dict, document: dict) -> bool:
    """True for same-node prose that is not one of the frozen expected sections."""
    if is_current_prose(case, document):
        return False
    node_id = document.get("opening_node_id")
    current = case.get("opening_node_id")
    return bool(node_id and current and node_id == current and document.get("intent") in _PROSE_INTENTS)


def is_deep_descendant(case: dict, document: dict, tree: Any = None) -> bool:
    """True when the document belongs to a descendant beyond the direct children."""
    node_id = document.get("opening_node_id")
    current = case.get("opening_node_id")
    if tree is None or not node_id or not current:
        return False
    return node_id in _deep_descendant_node_ids(tree, current)


def _is_history_chunk(document: dict) -> bool:
    return bool(document.get("is_history")) or document.get("intent") == "history"


def _is_misc_chunk(document: dict) -> bool:
    return bool(document.get("is_misc")) or document.get("intent") == "misc"


def is_history_pollution(case: dict, document: dict) -> bool:
    """True when the document is history prose the user did not ask for."""
    if is_current_prose(case, document):
        return False  # an ask_history case's "History" section is desired
    return _is_history_chunk(document)


def is_misc_pollution(case: dict, document: dict) -> bool:
    """True when the document is misc/utility prose, not pedagogical context."""
    if is_current_prose(case, document):
        return False
    return _is_misc_chunk(document)


def _has_opening_identity(document: dict) -> bool:
    return bool(
        document.get("opening_node_id")
        or document.get("opening_name")
        or document.get("eco_code")
    )


def is_false_current_line(case: dict, document: dict, tree: Any = None) -> bool:
    """True when the document reads like the current line but belongs to another.

    Structural definition: a chunk with intro/plan/candidate prose whose
    ``opening_node_id`` is neither the current node nor an allowed child (a
    sibling or unrelated line). Deep descendants are a separate pollution
    category, so they are excluded here.

    For ``out_of_theory``/``unsupported`` cases any surfaced opening prose is a
    fabrication risk and counts as a false current line.
    """
    if is_current_prose(case, document):
        return False
    if case.get("support") in {"out_of_theory", "unsupported"}:
        return _has_opening_identity(document)

    node_id = document.get("opening_node_id")
    current = case.get("opening_node_id")
    if not node_id or not current or node_id == current:
        return False
    if is_parent_prose(case, document, tree):
        return False
    if is_allowed_child_prose(case, document, tree):
        return False
    if is_deep_descendant(case, document, tree):
        return False
    return document.get("intent") in _PROSE_INTENTS


def has_source_attribution(document: dict) -> bool:
    """True when the document carries the attribution the coach needs to cite."""
    return bool(
        document.get("source_url")
        and document.get("license_or_terms")
        and document.get("page_id")
    )


def document_labels(case: dict, document: dict, tree: Any = None) -> list[str]:
    """Return every classification label that applies to the document.

    Labels are independent; a document can carry several. An empty result means
    ``UNRELATED``.
    """
    labels: list[str] = []
    if is_current_prose(case, document):
        labels.append(CURRENT_PROSE)
    if is_parent_prose(case, document, tree):
        labels.append(PARENT_PROSE)
    if is_current_node_other_prose(case, document):
        labels.append(CURRENT_NODE_OTHER_PROSE)
    if is_allowed_child_prose(case, document, tree):
        labels.append(ALLOWED_CHILD_PROSE)
    if is_deep_descendant(case, document, tree):
        labels.append(DEEP_DESCENDANT)
    if is_history_pollution(case, document):
        labels.append(HISTORY)
    if is_misc_pollution(case, document):
        labels.append(MISC)
    if is_false_current_line(case, document, tree):
        labels.append(FALSE_CURRENT_LINE)
    if not labels:
        labels.append(UNRELATED)
    return labels


def _is_relevant(case: dict, document: dict, tree: Any) -> bool:
    return is_current_prose(case, document) or is_allowed_child_prose(case, document, tree)


def false_context_rate(case: dict, documents: list[dict], tree: Any) -> float:
    """Fraction of retrieved documents that are not usable pedagogical context."""
    n = len(documents)
    if not n:
        return 0.0
    if case.get("support") == "in_theory":
        relevant = sum(1 for doc in documents if _is_relevant(case, doc, tree))
        return 1.0 - relevant / n
    return sum(1 for doc in documents if is_false_current_line(case, doc, tree)) / n


def _coach_usable(
    case: dict,
    labels_per_doc: list[list[str]],
    attribution_ok: bool,
) -> bool:
    if case.get("support") == "in_theory":
        current_hit = any(CURRENT_PROSE in labels for labels in labels_per_doc)
        pollution = any(
            tag in labels
            for labels in labels_per_doc
            for tag in (DEEP_DESCENDANT, HISTORY, MISC, FALSE_CURRENT_LINE)
        )
        return current_hit and not pollution and attribution_ok

    false_current = any(FALSE_CURRENT_LINE in labels for labels in labels_per_doc)
    return (not false_current) and attribution_ok


@dataclass(frozen=True)
class CaseMetrics:
    retrieved_count: int
    current_context_hit: bool
    child_context_hit: bool | None  # None when child prose isn't conditionally allowed
    deep_descendant_pollution: float
    history_pollution: float
    misc_pollution: float
    false_current_line: float
    false_context_rate: float
    source_attribution_ok: bool
    coach_usable_context: bool
    classification_counts: dict[str, int]


def score_case(case: dict, documents: list[dict], tree: Any = None, *, k: int | None = None) -> CaseMetrics:
    """Score a single case against its retrieved top-k documents."""
    docs = list(documents)
    if k is not None:
        docs = docs[:k]

    n = len(docs)
    labels_per_doc = [document_labels(case, doc, tree) for doc in docs]

    counts: dict[str, int] = {label: 0 for label in _ALL_LABELS}
    for labels in labels_per_doc:
        for label in labels:
            counts[label] += 1

    def rate(label: str) -> float:
        return counts.get(label, 0) / n if n else 0.0

    child_hit: bool | None = None
    if child_prose_allowed_for_case(case):
        child_hit = counts.get(ALLOWED_CHILD_PROSE, 0) > 0

    attribution_ok = all(has_source_attribution(doc) for doc in docs)

    return CaseMetrics(
        retrieved_count=n,
        current_context_hit=counts.get(CURRENT_PROSE, 0) > 0,
        child_context_hit=child_hit,
        deep_descendant_pollution=rate(DEEP_DESCENDANT),
        history_pollution=rate(HISTORY),
        misc_pollution=rate(MISC),
        false_current_line=rate(FALSE_CURRENT_LINE),
        false_context_rate=false_context_rate(case, docs, tree),
        source_attribution_ok=attribution_ok,
        coach_usable_context=_coach_usable(case, labels_per_doc, attribution_ok),
        classification_counts=counts,
    )


def ranking_metrics(case: dict, documents: list[dict], tree: Any, k: int) -> dict | None:
    """Secondary nDCG/MRR/Hit/Recall diagnostics over current + child relevance.

    Returns ``None`` for ``out_of_theory``/``unsupported`` cases, where there is
    no relevant set to rank against.
    """
    if case.get("support") != "in_theory":
        return None

    expected = case.get("expected_context") or {}
    relevant_count = len(expected.get("current_prose") or []) + len(expected.get("child_prose_allowed") or [])
    relevances = [bool(_is_relevant(case, doc, tree)) for doc in documents]
    return asdict(evaluate_query(relevances, relevant_count, k))


def _mean_opt(values: list[float]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _latency_stats(samples: list[float]) -> dict[str, float]:
    return {
        "p50": percentile(samples, 50),
        "p95": percentile(samples, 95),
        "mean": _mean(samples),
    }


def _aggregate(
    case_metrics: list[CaseMetrics],
    ranking: list[dict | None],
    latency: dict[str, list[float]] | None,
) -> dict:
    n = len(case_metrics)

    def mean_bool(key: str) -> float:
        return _mean([1.0 if getattr(m, key) else 0.0 for m in case_metrics])

    def mean_rate(key: str) -> float:
        return _mean([getattr(m, key) for m in case_metrics])

    child_hits = [m.child_context_hit for m in case_metrics if m.child_context_hit is not None]

    present_ranking = [r for r in ranking if r is not None]

    def ranking_mean(key: str) -> float | None:
        return _mean_opt([r[key] for r in present_ranking])

    secondary = {
        "scored_count": len(present_ranking),
        "recall_at_k": ranking_mean("recall"),
        "mrr": ranking_mean("reciprocal_rank"),
        "ndcg_at_k": ranking_mean("ndcg"),
        "hit_rate": ranking_mean("hit"),
        "precision_at_1": ranking_mean("precision_at_1"),
        "precision_at_3": ranking_mean("precision_at_3"),
        "precision_at_5": ranking_mean("precision_at_5"),
    }

    report: dict[str, Any] = {
        "case_count": n,
        "current_context_hit_rate": mean_bool("current_context_hit"),
        "child_context_hit_rate": _mean([1.0 if h else 0.0 for h in child_hits]) if child_hits else None,
        "child_context_hit_cases": len(child_hits),
        "deep_descendant_pollution_rate": mean_rate("deep_descendant_pollution"),
        "history_pollution_rate": mean_rate("history_pollution"),
        "misc_pollution_rate": mean_rate("misc_pollution"),
        "false_current_line_rate": mean_rate("false_current_line"),
        "false_context_rate": mean_rate("false_context_rate"),
        "source_attribution_ok_rate": mean_bool("source_attribution_ok"),
        "coach_usable_context_rate": mean_bool("coach_usable_context"),
        "secondary": secondary,
    }
    if latency is not None:
        report["latency_ms"] = {
            phase: _latency_stats(samples)
            for phase, samples in latency.items()
        }
    return report


def score_run(
    dataset: dict,
    retrieved_by_case: dict[str, list[dict]],
    tree: Any = None,
    *,
    k: int = 5,
    latency: dict[str, list[float]] | None = None,
) -> dict:
    """Score a full run and stratify the report by intent, support, and split.

    ``retrieved_by_case`` maps ``case["id"]`` to its retrieved document list.
    ``latency`` is an optional global ``{phase: [ms...]}`` sample dict
    (``embed``/``search``/``total``), reported at the overall level only.
    """
    cases = dataset["cases"]

    case_metrics: dict[str, CaseMetrics] = {}
    ranking: dict[str, dict | None] = {}
    for case in cases:
        documents = retrieved_by_case.get(case["id"], [])
        case_metrics[case["id"]] = score_case(case, documents, tree, k=k)
        ranking[case["id"]] = ranking_metrics(case, documents, tree, k)

    def stratify(key: str, values: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for value in values:
            ids = [c["id"] for c in cases if c[key] == value]
            out[value] = _aggregate(
                [case_metrics[i] for i in ids],
                [ranking[i] for i in ids],
                None,
            )
        return out

    per_case = {
        case_id: {**asdict(metric), "secondary": ranking[case_id]}
        for case_id, metric in case_metrics.items()
    }

    return {
        "overall": _aggregate(list(case_metrics.values()), [ranking[c["id"]] for c in cases], latency),
        "by_intent": stratify("intent", list(dataset.get("intent_vocabulary", {}))),
        "by_support": stratify("support", list(dataset.get("support_vocabulary", {}))),
        "by_split": stratify("split", ["dev", "test"]),
        "per_case": per_case,
    }


def _load_run(path: Path) -> dict[str, list[dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "retrieved" in payload:
        return payload["retrieved"]
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Score an Eval V2 retrieval run and write a stratified report.")
    parser.add_argument("--run", type=Path, required=True, help="JSON of {case_id: [documents]} (or {\"retrieved\": {...}}).")
    parser.add_argument("--dataset", type=Path, required=True, help="Path to dataset.json.")
    parser.add_argument("--opening-tree-dir", type=Path, default=None, help="Optional OpeningTree snapshot dir for window classification.")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--out", type=Path, required=True, help="Where to write report.json.")
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    retrieved = _load_run(args.run)

    tree = None
    if args.opening_tree_dir is not None:
        from backend.app.services.opening_tree import OpeningTree

        tree = OpeningTree.from_snapshot_dir(args.opening_tree_dir)

    report = score_run(dataset, retrieved, tree, k=args.k)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
