"""Stable service-domain contracts for the retrieval pipeline.

These contracts describe the seam between opening-tree context, intent routing,
retrieval planning, retrieved chunks, and coach-facing context. They deliberately
avoid Milvus, JEV, FastAPI, and LangGraph dependencies.
"""

from dataclasses import dataclass
from typing import Literal

from backend.app.services.intent_router import RetrievalIntent


RelationToPosition = Literal["current", "child", "parent", "general", "fallback"]
OpeningTreeState = Literal["matched", "out_of_theory", "unsupported"]


@dataclass(frozen=True)
class OpeningTreeNodeContext:
    node_id: str
    eco_code: str
    opening_name: str
    pgn: str
    uci: tuple[str, ...]
    san: tuple[str, ...]
    fen: str
    epd: str
    depth: int
    entry_move: str | None = None

    def to_artifact(self) -> dict:
        return {
            "node_id": self.node_id,
            "eco_code": self.eco_code,
            "opening_name": self.opening_name,
            "pgn": self.pgn,
            "uci": list(self.uci),
            "san": list(self.san),
            "fen": self.fen,
            "epd": self.epd,
            "depth": self.depth,
            "entry_move": self.entry_move,
        }


@dataclass(frozen=True)
class OpeningTreeContext:
    state: OpeningTreeState = "matched"
    current: OpeningTreeNodeContext | None = None
    parent: OpeningTreeNodeContext | None = None
    children: tuple[OpeningTreeNodeContext, ...] = ()
    excluded_descendant_node_ids: tuple[str, ...] = ()
    fallback_opening_name: str | None = None

    def to_artifact(self) -> dict:
        return {
            "state": self.state,
            "current": self.current.to_artifact() if self.current else None,
            "parent": self.parent.to_artifact() if self.parent else None,
            "children": [child.to_artifact() for child in self.children],
            "excluded_descendant_node_ids": list(self.excluded_descendant_node_ids),
            "fallback_opening_name": self.fallback_opening_name,
        }


@dataclass(frozen=True)
class RetrievalBucket:
    name: str
    relation_to_position: RelationToPosition
    node_ids: tuple[str, ...] = ()
    page_ids: tuple[str, ...] = ()
    eco_code: str | None = None
    limit: int = 4
    include_history: bool = False
    include_misc: bool = False
    entry_move: str | None = None
    query_hint: str | None = None

    def to_artifact(self) -> dict:
        return {
            "name": self.name,
            "relation_to_position": self.relation_to_position,
            "node_ids": list(self.node_ids),
            "page_ids": list(self.page_ids),
            "eco_code": self.eco_code,
            "limit": self.limit,
            "include_history": self.include_history,
            "include_misc": self.include_misc,
            "entry_move": self.entry_move,
            "query_hint": self.query_hint,
        }


@dataclass(frozen=True)
class RetrievalPlan:
    intent: RetrievalIntent
    state: OpeningTreeState
    buckets: tuple[RetrievalBucket, ...]
    excluded_node_ids: tuple[str, ...] = ()
    reason: str | None = None
    requires_stockfish: bool = False

    @classmethod
    def current_only(
        cls,
        *,
        tree_context: OpeningTreeContext,
        intent: RetrievalIntent = "explain_current_position",
        reason: str = "current_only",
    ) -> "RetrievalPlan":
        node_ids = (tree_context.current.node_id,) if tree_context.current else ()
        return cls(
            intent=intent,
            state=tree_context.state,
            reason=reason,
            excluded_node_ids=tree_context.excluded_descendant_node_ids,
            requires_stockfish=False,
            buckets=(
                RetrievalBucket(
                    name="current",
                    relation_to_position="current",
                    node_ids=node_ids,
                    eco_code=tree_context.current.eco_code if tree_context.current else None,
                    limit=4,
                ),
            ),
        )

    @classmethod
    def with_children(
        cls,
        *,
        tree_context: OpeningTreeContext,
        intent: RetrievalIntent = "ask_next_moves",
        reason: str = "child_allowed",
    ) -> "RetrievalPlan":
        current_ids = (tree_context.current.node_id,) if tree_context.current else ()
        child_ids = tuple(child.node_id for child in tree_context.children)
        entry_moves = tuple(child.entry_move for child in tree_context.children if child.entry_move)
        return cls(
            intent=intent,
            state=tree_context.state,
            reason=reason,
            excluded_node_ids=tree_context.excluded_descendant_node_ids,
            requires_stockfish=False,
            buckets=(
                RetrievalBucket(
                    name="current",
                    relation_to_position="current",
                    node_ids=current_ids,
                    eco_code=tree_context.current.eco_code if tree_context.current else None,
                    limit=4,
                ),
                RetrievalBucket(
                    name="children",
                    relation_to_position="child",
                    node_ids=child_ids,
                    eco_code=tree_context.children[0].eco_code if len(tree_context.children) == 1 else None,
                    limit=3,
                    entry_move=entry_moves[0] if len(entry_moves) == 1 else None,
                    query_hint="conditional continuations",
                ),
            ),
        )

    @classmethod
    def history_only(cls, *, tree_context: OpeningTreeContext) -> "RetrievalPlan":
        node_ids = (tree_context.current.node_id,) if tree_context.current else ()
        return cls(
            intent="ask_history",
            state=tree_context.state,
            reason="history_only",
            excluded_node_ids=tree_context.excluded_descendant_node_ids,
            requires_stockfish=False,
            buckets=(
                RetrievalBucket(
                    name="history",
                    relation_to_position="current",
                    node_ids=node_ids,
                    eco_code=tree_context.current.eco_code if tree_context.current else None,
                    limit=1,
                    include_history=True,
                    query_hint="history",
                ),
            ),
        )

    @classmethod
    def out_of_theory(cls, *, tree_context: OpeningTreeContext) -> "RetrievalPlan":
        return cls(
            intent="unclear",
            state=tree_context.state,
            reason="out_of_theory_conservative",
            excluded_node_ids=tree_context.excluded_descendant_node_ids,
            requires_stockfish=False,
            buckets=(
                RetrievalBucket(
                    name="fallback",
                    relation_to_position="fallback",
                    node_ids=(),
                    limit=2,
                    query_hint=tree_context.fallback_opening_name,
                ),
            ),
        )

    def to_artifact(self) -> dict:
        return {
            "intent": self.intent,
            "state": self.state,
            "reason": self.reason,
            "requires_stockfish": self.requires_stockfish,
            "buckets": [bucket.to_artifact() for bucket in self.buckets],
            "excluded_node_ids": list(self.excluded_node_ids),
        }


@dataclass(frozen=True)
class RetrievedContext:
    chunk_id: str
    text: str
    source: str
    source_url: str | None
    license_or_terms: str | None
    page_id: str
    canonical_title: str
    section_index: int | None
    part_index: int
    section_title: str | None
    score: float
    relation_to_position: RelationToPosition
    entry_move: str | None = None
    opening_node_id: str | None = None
    eco_code: str | None = None
    opening_name: str | None = None
    intent: str | None = None
    is_history: bool = False
    is_misc: bool = False

    def to_artifact(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "source": self.source,
            "source_url": self.source_url,
            "license_or_terms": self.license_or_terms,
            "page_id": self.page_id,
            "canonical_title": self.canonical_title,
            "section_index": self.section_index,
            "part_index": self.part_index,
            "section_title": self.section_title,
            "score": self.score,
            "relation_to_position": self.relation_to_position,
            "entry_move": self.entry_move,
            "opening_node_id": self.opening_node_id,
            "eco_code": self.eco_code,
            "opening_name": self.opening_name,
            "intent": self.intent,
            "is_history": self.is_history,
            "is_misc": self.is_misc,
        }


@dataclass(frozen=True)
class CoachPositionContext:
    state: OpeningTreeState
    opening_name: str | None
    eco_code: str | None
    pgn: str | None
    fen: str | None

    @classmethod
    def from_tree_context(cls, tree_context: OpeningTreeContext) -> "CoachPositionContext":
        current = tree_context.current
        return cls(
            state=tree_context.state,
            opening_name=current.opening_name if current else tree_context.fallback_opening_name,
            eco_code=current.eco_code if current else None,
            pgn=current.pgn if current else None,
            fen=current.fen if current else None,
        )

    def to_artifact(self) -> dict:
        return {
            "state": self.state,
            "opening_name": self.opening_name,
            "eco_code": self.eco_code,
            "pgn": self.pgn,
            "fen": self.fen,
        }


@dataclass(frozen=True)
class CoachSourceAttribution:
    chunk_id: str
    source: str
    source_url: str | None
    license_or_terms: str | None
    page_id: str
    canonical_title: str
    section_title: str | None
    section_index: int | None
    part_index: int

    @classmethod
    def from_retrieved_context(cls, context: RetrievedContext) -> "CoachSourceAttribution":
        return cls(
            chunk_id=context.chunk_id,
            source=context.source,
            source_url=context.source_url,
            license_or_terms=context.license_or_terms,
            page_id=context.page_id,
            canonical_title=context.canonical_title,
            section_title=context.section_title,
            section_index=context.section_index,
            part_index=context.part_index,
        )

    def to_artifact(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "source": self.source,
            "source_url": self.source_url,
            "license_or_terms": self.license_or_terms,
            "page_id": self.page_id,
            "canonical_title": self.canonical_title,
            "section_title": self.section_title,
            "section_index": self.section_index,
            "part_index": self.part_index,
        }


@dataclass(frozen=True)
class CoachProsePassage:
    text: str
    relation_to_position: RelationToPosition
    source_chunk_id: str
    opening_name: str | None = None
    eco_code: str | None = None
    entry_move: str | None = None

    def __post_init__(self) -> None:
        if self.relation_to_position == "child" and not self.entry_move:
            raise ValueError("child coach prose requires entry_move for conditional labelling")
        if self.relation_to_position == "current" and self.entry_move is not None:
            raise ValueError("current coach prose cannot carry entry_move")

    @classmethod
    def from_retrieved_context(cls, context: RetrievedContext) -> "CoachProsePassage":
        return cls(
            text=context.text,
            relation_to_position=context.relation_to_position,
            entry_move=context.entry_move,
            source_chunk_id=context.chunk_id,
            opening_name=context.opening_name,
            eco_code=context.eco_code,
        )

    def to_artifact(self) -> dict:
        return {
            "text": self.text,
            "relation_to_position": self.relation_to_position,
            "entry_move": self.entry_move,
            "source_chunk_id": self.source_chunk_id,
            "opening_name": self.opening_name,
            "eco_code": self.eco_code,
        }


@dataclass(frozen=True)
class CoachCandidateContinuation:
    entry_move: str
    opening_name: str | None
    eco_code: str | None
    prose: tuple[CoachProsePassage, ...]

    def __post_init__(self) -> None:
        for passage in self.prose:
            if passage.relation_to_position != "child":
                raise ValueError("candidate continuations can contain only child prose")
            if passage.entry_move != self.entry_move:
                raise ValueError("child prose entry_move must match candidate continuation")

    def to_artifact(self) -> dict:
        return {
            "entry_move": self.entry_move,
            "opening_name": self.opening_name,
            "eco_code": self.eco_code,
            "prose": [passage.to_artifact() for passage in self.prose],
        }


@dataclass(frozen=True)
class CoachContext:
    current_position: CoachPositionContext
    current_prose: tuple[CoachProsePassage, ...] = ()
    candidate_continuations: tuple[CoachCandidateContinuation, ...] = ()
    source_attributions: tuple[CoachSourceAttribution, ...] = ()
    lichess_stats: dict | None = None
    stockfish: dict | None = None
    fallbacks: tuple[str, ...] = ()

    def to_artifact(self) -> dict:
        return {
            "current_position": self.current_position.to_artifact(),
            "current_prose": [passage.to_artifact() for passage in self.current_prose],
            "candidate_continuations": [
                continuation.to_artifact() for continuation in self.candidate_continuations
            ],
            "source_attributions": [
                attribution.to_artifact() for attribution in self.source_attributions
            ],
            "lichess_stats": self.lichess_stats,
            "stockfish": self.stockfish,
            "fallbacks": list(self.fallbacks),
        }


def build_coach_context(
    *,
    tree_context: OpeningTreeContext,
    retrieved_contexts: tuple[RetrievedContext, ...] = (),
    lichess_stats: dict | None = None,
    stockfish: dict | None = None,
    fallbacks: tuple[str, ...] = (),
) -> CoachContext:
    current_prose: list[CoachProsePassage] = []
    child_prose_by_move: dict[str, list[CoachProsePassage]] = {}
    source_attributions: list[CoachSourceAttribution] = []

    for context in retrieved_contexts:
        passage = CoachProsePassage.from_retrieved_context(context)
        source_attributions.append(CoachSourceAttribution.from_retrieved_context(context))
        if passage.relation_to_position == "child":
            child_prose_by_move.setdefault(passage.entry_move or "", []).append(passage)
        elif passage.relation_to_position == "current":
            current_prose.append(passage)

    candidate_continuations = tuple(
        CoachCandidateContinuation(
            entry_move=entry_move,
            opening_name=passages[0].opening_name if passages else None,
            eco_code=passages[0].eco_code if passages else None,
            prose=tuple(passages),
        )
        for entry_move, passages in child_prose_by_move.items()
    )

    return CoachContext(
        current_position=CoachPositionContext.from_tree_context(tree_context),
        current_prose=tuple(current_prose),
        candidate_continuations=candidate_continuations,
        source_attributions=tuple(source_attributions),
        lichess_stats=lichess_stats,
        stockfish=stockfish,
        fallbacks=fallbacks,
    )
