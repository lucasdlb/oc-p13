"""Deterministic retrieval-plan policy.

JEV or the local router may classify intent, but this module owns the final
constraints and budgets before any vector store is queried.
"""

from backend.app.services.intent_router import IntentDecision
from backend.app.services.retrieval_contracts import OpeningTreeContext, RetrievalBucket, RetrievalIntent, RetrievalPlan


LOW_CONFIDENCE = 0.5
HIGH_CONFIDENCE = 0.75
ROOT_OPENING_PAGE_ID = "wikibooks-chess-opening-theory::Chess Opening Theory"


def build_retrieval_plan(tree_context: OpeningTreeContext, decision: IntentDecision) -> RetrievalPlan:
    if tree_context.state != "matched":
        if decision.intent in {"ask_out_of_theory", "ask_unsupported"}:
            return _no_book_context(tree_context, decision.intent, "no_supported_theory_context")
        if decision.intent == "general_principle":
            return _root_general_principle(tree_context)
        return RetrievalPlan.out_of_theory(tree_context=tree_context)

    if decision.confidence < LOW_CONFIDENCE:
        return _current_only(tree_context, decision.intent, "low_confidence_conservative")

    if decision.intent == "unclear":
        return _current_only(tree_context, decision.intent, "unclear_conservative")
    if decision.intent == "explain_current_position":
        return _explain_current_position(tree_context)
    if decision.intent == "ask_next_moves":
        return _ask_next_moves(tree_context, decision.confidence)
    if decision.intent == "ask_specific_candidate":
        return _ask_specific_candidate(tree_context, decision)
    if decision.intent == "evaluate_move_quality":
        return _evaluate_move_quality(tree_context)
    if decision.intent == "compare_moves":
        return _compare_moves(tree_context)
    if decision.intent == "ask_trap":
        return _current_only(tree_context, decision.intent, "trap_current_line")
    if decision.intent == "ask_mistake":
        return _current_only(tree_context, decision.intent, "mistake_current_line")
    if decision.intent == "ask_history":
        return RetrievalPlan.history_only(tree_context=tree_context)
    if decision.intent in {"ask_out_of_theory", "ask_unsupported"}:
        return _no_book_context(tree_context, decision.intent, "no_supported_theory_context")
    if decision.intent == "general_principle":
        return _general_principle(tree_context)

    return _current_only(tree_context, decision.intent, "unsupported_intent_conservative")


def _explain_current_position(tree_context: OpeningTreeContext) -> RetrievalPlan:
    buckets = [_current_bucket(tree_context, limit=4)]
    if tree_context.parent is not None:
        buckets.append(
            RetrievalBucket(
                name="parent",
                relation_to_position="parent",
                node_ids=(tree_context.parent.node_id,),
                eco_code=tree_context.parent.eco_code,
                limit=1,
                query_hint="sparse parent context",
            )
        )
    return RetrievalPlan(
        intent="explain_current_position",
        state=tree_context.state,
        reason="current_position",
        buckets=tuple(buckets),
        excluded_node_ids=tree_context.excluded_descendant_node_ids,
    )


def _ask_next_moves(tree_context: OpeningTreeContext, confidence: float) -> RetrievalPlan:
    child_limit = 3 if confidence >= HIGH_CONFIDENCE else 1
    return RetrievalPlan(
        intent="ask_next_moves",
        state=tree_context.state,
        reason="child_allowed" if confidence >= HIGH_CONFIDENCE else "child_allowed_medium_confidence",
        buckets=(
            _current_bucket(tree_context, limit=3),
            RetrievalBucket(
                name="children",
                relation_to_position="child",
                node_ids=tuple(child.node_id for child in tree_context.children),
                eco_code=tree_context.children[0].eco_code if len(tree_context.children) == 1 else None,
                limit=child_limit,
                query_hint="conditional continuations",
            ),
        ),
        excluded_node_ids=tree_context.excluded_descendant_node_ids,
    )


def _ask_specific_candidate(tree_context: OpeningTreeContext, decision: IntentDecision) -> RetrievalPlan:
    matched_node_id = decision.matched_candidate_move.opening_node_id if decision.matched_candidate_move else None
    child_by_id = {child.node_id: child for child in tree_context.children}
    child = child_by_id.get(matched_node_id or "")
    if child is None:
        return _current_only(tree_context, "ask_specific_candidate", "specific_candidate_not_in_direct_children")

    return RetrievalPlan(
        intent="ask_specific_candidate",
        state=tree_context.state,
        reason="specific_direct_child_allowed",
        buckets=(
            _current_bucket(tree_context, limit=3),
            RetrievalBucket(
                name="matched_child",
                relation_to_position="child",
                node_ids=(child.node_id,),
                eco_code=child.eco_code,
                limit=2,
                entry_move=child.entry_move,
                query_hint="specific conditional continuation",
            ),
        ),
        excluded_node_ids=tree_context.excluded_descendant_node_ids,
    )


def _evaluate_move_quality(tree_context: OpeningTreeContext) -> RetrievalPlan:
    return RetrievalPlan(
        intent="evaluate_move_quality",
        state=tree_context.state,
        reason="stockfish_required",
        buckets=(_current_bucket(tree_context, limit=3),),
        excluded_node_ids=tree_context.excluded_descendant_node_ids,
        requires_stockfish=True,
    )


def _compare_moves(tree_context: OpeningTreeContext) -> RetrievalPlan:
    return RetrievalPlan(
        intent="compare_moves",
        state=tree_context.state,
        reason="compare_children_with_stockfish",
        buckets=(
            _current_bucket(tree_context, limit=3),
            RetrievalBucket(
                name="children",
                relation_to_position="child",
                node_ids=tuple(child.node_id for child in tree_context.children),
                eco_code=tree_context.children[0].eco_code if len(tree_context.children) == 1 else None,
                limit=3,
                query_hint="candidate move comparison",
            ),
        ),
        excluded_node_ids=tree_context.excluded_descendant_node_ids,
        requires_stockfish=True,
    )


def _general_principle(tree_context: OpeningTreeContext) -> RetrievalPlan:
    return _current_only(tree_context, "general_principle", "general_principle_current_line")


def _root_general_principle(tree_context: OpeningTreeContext) -> RetrievalPlan:
    return RetrievalPlan(
        intent="general_principle",
        state=tree_context.state,
        reason="general_principle_root_page",
        buckets=(
            RetrievalBucket(
                name="root_general",
                relation_to_position="general",
                page_ids=(ROOT_OPENING_PAGE_ID,),
                limit=2,
                query_hint="Starting position opening principles",
            ),
        ),
        excluded_node_ids=tree_context.excluded_descendant_node_ids,
    )


def _current_only(tree_context: OpeningTreeContext, intent: RetrievalIntent, reason: str) -> RetrievalPlan:
    return RetrievalPlan(
        intent=intent,
        state=tree_context.state,
        reason=reason,
        buckets=(_current_bucket(tree_context, limit=4),),
        excluded_node_ids=tree_context.excluded_descendant_node_ids,
    )


def _no_book_context(tree_context: OpeningTreeContext, intent: RetrievalIntent, reason: str) -> RetrievalPlan:
    return RetrievalPlan(
        intent=intent,
        state=tree_context.state,
        reason=reason,
        buckets=(),
        excluded_node_ids=tree_context.excluded_descendant_node_ids,
        requires_stockfish=intent == "ask_out_of_theory",
    )


def _current_bucket(tree_context: OpeningTreeContext, *, limit: int) -> RetrievalBucket:
    return RetrievalBucket(
        name="current",
        relation_to_position="current",
        node_ids=(tree_context.current.node_id,) if tree_context.current else (),
        eco_code=tree_context.current.eco_code if tree_context.current else None,
        limit=limit,
    )
