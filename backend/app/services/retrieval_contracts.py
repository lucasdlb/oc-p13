"""Stable service-domain contracts for the retrieval pipeline.

These contracts describe the seam between opening-tree context, intent routing,
retrieval planning, retrieved chunks, and coach-facing context. They deliberately
avoid Milvus, JEV, FastAPI, and LangGraph dependencies.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


RetrievalIntent = Literal[
    "explain_current_position",
    "ask_next_moves",
    "ask_specific_candidate",
    "evaluate_move_quality",
    "compare_moves",
    "ask_trap",
    "ask_mistake",
    "ask_history",
    "ask_unsupported",
    "ask_out_of_theory",
    "general_principle",
    "unclear",
]


RelationToPosition = Literal["current", "child", "parent", "general", "fallback"]
OpeningTreeState = Literal["matched", "out_of_theory", "unsupported"]


class ContractModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class OpeningTreeNodeContext(ContractModel):
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
            "node_id": self.node_id, "eco_code": self.eco_code, "opening_name": self.opening_name,
            "pgn": self.pgn, "uci": list(self.uci), "san": list(self.san), "fen": self.fen,
            "epd": self.epd, "depth": self.depth, "entry_move": self.entry_move,
        }


class OpeningTreeContext(ContractModel):
    state: OpeningTreeState = "matched"
    current: OpeningTreeNodeContext | None = None
    parent: OpeningTreeNodeContext | None = None
    children: tuple[OpeningTreeNodeContext, ...] = ()
    excluded_descendant_node_ids: tuple[str, ...] = ()

    def to_artifact(self) -> dict:
        return {
            "state": self.state,
            "current": self.current.to_artifact() if self.current else None,
            "parent": self.parent.to_artifact() if self.parent else None,
            "children": [child.to_artifact() for child in self.children],
            "excluded_descendant_node_ids": list(self.excluded_descendant_node_ids),
        }


class RetrievalBucket(ContractModel):
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


class RetrievalPlan(ContractModel):
    intent: RetrievalIntent
    state: OpeningTreeState
    buckets: tuple[RetrievalBucket, ...]
    excluded_node_ids: tuple[str, ...] = ()
    reason: str | None = None
    requires_stockfish: bool = False

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
    def no_book_context(
        cls,
        *,
        tree_context: OpeningTreeContext,
        intent: RetrievalIntent = "unclear",
        reason: str = "no_supported_theory_context",
        requires_stockfish: bool = False,
    ) -> "RetrievalPlan":
        return cls(
            intent=intent,
            state=tree_context.state,
            reason=reason,
            excluded_node_ids=tree_context.excluded_descendant_node_ids,
            requires_stockfish=requires_stockfish,
            buckets=(),
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


class RetrievedContext(ContractModel):
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


class CoachPositionContext(ContractModel):
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
            opening_name=current.opening_name if current else None,
            eco_code=current.eco_code if current else None,
            pgn=current.pgn if current else None,
            fen=current.fen if current else None,
        )

    @classmethod
    def from_artifact(cls, payload: dict) -> "CoachPositionContext":
        return cls.model_validate(payload)

    def to_artifact(self) -> dict:
        return {
            "state": self.state,
            "opening_name": self.opening_name,
            "eco_code": self.eco_code,
            "pgn": self.pgn,
            "fen": self.fen,
        }


class CoachSourceAttribution(ContractModel):
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

    @classmethod
    def from_artifact(cls, payload: dict) -> "CoachSourceAttribution":
        return cls.model_validate(payload)

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


class CoachProsePassage(ContractModel):
    text: str
    relation_to_position: RelationToPosition
    source_chunk_id: str
    opening_name: str | None = None
    eco_code: str | None = None
    entry_move: str | None = None
    is_history: bool = False

    @model_validator(mode="after")
    def validate_relation(self) -> "CoachProsePassage":
        if self.relation_to_position == "child" and not self.entry_move:
            raise ValueError("child coach prose requires entry_move for conditional labelling")
        if self.relation_to_position == "current" and self.entry_move is not None:
            raise ValueError("current coach prose cannot carry entry_move")
        return self

    @classmethod
    def from_retrieved_context(cls, context: RetrievedContext) -> "CoachProsePassage":
        return cls(
            text=context.text,
            relation_to_position=context.relation_to_position,
            entry_move=context.entry_move,
            source_chunk_id=context.chunk_id,
            opening_name=context.opening_name,
            eco_code=context.eco_code,
            is_history=context.is_history,
        )

    @classmethod
    def from_artifact(cls, payload: dict) -> "CoachProsePassage":
        return cls.model_validate(payload)

    def to_artifact(self) -> dict:
        artifact = {
            "text": self.text,
            "relation_to_position": self.relation_to_position,
            "entry_move": self.entry_move,
            "source_chunk_id": self.source_chunk_id,
            "opening_name": self.opening_name,
            "eco_code": self.eco_code,
        }
        if self.is_history:
            artifact["is_history"] = True
        return artifact


class CoachCandidateContinuation(ContractModel):
    entry_move: str
    opening_name: str | None
    eco_code: str | None
    prose: tuple[CoachProsePassage, ...]
    entry_uci: str | None = None

    @model_validator(mode="after")
    def validate_prose(self) -> "CoachCandidateContinuation":
        for passage in self.prose:
            if passage.relation_to_position != "child":
                raise ValueError("candidate continuations can contain only child prose")
            if passage.entry_move != self.entry_move:
                raise ValueError("child prose entry_move must match candidate continuation")
        return self

    @classmethod
    def from_artifact(cls, payload: dict) -> "CoachCandidateContinuation":
        return cls.model_validate(payload)

    def to_artifact(self) -> dict:
        return {
            "entry_move": self.entry_move,
            "entry_uci": self.entry_uci,
            "opening_name": self.opening_name,
            "eco_code": self.eco_code,
            "prose": [passage.to_artifact() for passage in self.prose],
        }


class RecommendedMove(ContractModel):
    uci: str
    san: str
    description: str = ""
    source: str = ""
    games: int | None = None
    white: float | None = None
    draws: float | None = None
    black: float | None = None
    average_rating: int | None = None
    move_share: float | None = None
    relevant: bool = True
    badges: list[str] | None = None
    score: dict | str | float | None = None
    engine_score: dict | str | None = None
    counterexample: str | None = None


class StockfishEval(ContractModel):
    status: str | None = None
    best_move: str | None = None
    score: dict | None = None
    mate: int | None = None
    pv: tuple[str, ...] = ()
    depth: int | None = None
    model_config = ConfigDict(frozen=True, extra="allow")


class EvidencePack(ContractModel):
    """Normalized facts presented to the coach for interpretation."""

    position: CoachPositionContext
    lichess_stats: dict | None = None
    explorer_moves: tuple[RecommendedMove, ...] = ()
    masters_stats: dict | None = None
    masters_moves: tuple[RecommendedMove, ...] = ()
    stockfish: StockfishEval | None = None


class CoachContext(ContractModel):
    current_position: CoachPositionContext
    question: str | None = None
    intent: RetrievalIntent | None = None
    current_prose: tuple[CoachProsePassage, ...] = ()
    supporting_prose: tuple[CoachProsePassage, ...] = ()
    candidate_continuations: tuple[CoachCandidateContinuation, ...] = ()
    source_attributions: tuple[CoachSourceAttribution, ...] = ()
    lichess_stats: dict | None = None
    recommended_moves: tuple[RecommendedMove, ...] = ()
    masters_stats: dict | None = None
    masters_moves: tuple[RecommendedMove, ...] = ()
    stockfish: StockfishEval | None = None
    fallbacks: tuple[str, ...] = ()

    def to_artifact(self) -> dict:
        artifact = {
            "current_position": self.current_position.to_artifact(),
            "question": self.question,
            "current_prose": [passage.to_artifact() for passage in self.current_prose],
            "candidate_continuations": [
                continuation.to_artifact() for continuation in self.candidate_continuations
            ],
            "source_attributions": [
                attribution.to_artifact() for attribution in self.source_attributions
            ],
            "lichess_stats": self.lichess_stats,
            "recommended_moves": [move.model_dump() for move in self.recommended_moves],
            "stockfish": (
                {
                    key: value
                    for key, value in self.stockfish.model_dump(exclude_none=True).items()
                    if value not in ((), [])
                }
                if self.stockfish
                else None
            ),
            "fallbacks": list(self.fallbacks),
        }
        if self.supporting_prose:
            artifact["supporting_prose"] = [passage.to_artifact() for passage in self.supporting_prose]
        if self.masters_stats is not None:
            artifact["masters_stats"] = self.masters_stats
        if self.masters_moves:
            artifact["masters_moves"] = [move.model_dump() for move in self.masters_moves]
        if self.intent is not None:
            artifact["intent"] = self.intent
        return artifact

    @classmethod
    def from_artifact(cls, payload: dict) -> "CoachContext":
        return cls.model_validate(payload)


def build_coach_context(
    *,
    tree_context: OpeningTreeContext,
    current_fen: str | None = None,
    current_pgn: str | None = None,
    question: str | None = None,
    intent: RetrievalIntent | None = None,
    retrieved_contexts: tuple[RetrievedContext, ...] = (),
    lichess_stats: dict | None = None,
    recommended_moves: list[dict] | tuple[RecommendedMove, ...] | None = None,
    masters_stats: dict | None = None,
    masters_moves: list[dict] | tuple[RecommendedMove, ...] | None = None,
    stockfish: dict | StockfishEval | None = None,
    fallbacks: tuple[str, ...] = (),
) -> CoachContext:
    current_prose: list[CoachProsePassage] = []
    child_prose_by_move: dict[str, list[CoachProsePassage]] = {}
    supporting_prose: list[CoachProsePassage] = []
    source_attributions_by_id: dict[str, CoachSourceAttribution] = {}
    child_by_node_id = {child.node_id: child for child in tree_context.children}

    for context in retrieved_contexts:
        entry_move = context.entry_move
        if context.relation_to_position == "child" and not entry_move:
            child = child_by_node_id.get(context.opening_node_id or "")
            entry_move = child.entry_move if child else None
        if context.relation_to_position == "child" and not entry_move:
            import logging

            logging.getLogger("backend.retrieval_contracts").warning(
                "dropping child passage without entry move: %s", context.chunk_id
            )
            continue
        passage = CoachProsePassage(
            text=context.text,
            relation_to_position=context.relation_to_position,
            entry_move=entry_move,
            source_chunk_id=context.chunk_id,
            opening_name=context.opening_name,
            eco_code=context.eco_code,
            is_history=context.is_history or context.intent == "history",
        )
        source_attributions_by_id.setdefault(
            context.chunk_id,
            CoachSourceAttribution.from_retrieved_context(context),
        )
        if passage.relation_to_position == "child":
            child_prose_by_move.setdefault(passage.entry_move, []).append(passage)
        elif passage.is_history or passage.relation_to_position in {"parent", "general", "fallback"}:
            supporting_prose.append(passage)
        elif passage.relation_to_position == "current":
            current_prose.append(passage)

    child_uci_by_move = {
        child.entry_move or (child.san[-1] if child.san else ""): child.uci[-1]
        for child in tree_context.children
        if child.uci
    }
    candidate_continuations = tuple(
        CoachCandidateContinuation(
            entry_move=entry_move,
            opening_name=passages[0].opening_name if passages else None,
            eco_code=passages[0].eco_code if passages else None,
            prose=tuple(passages),
            entry_uci=child_uci_by_move.get(entry_move),
        )
        for entry_move, passages in child_prose_by_move.items()
    )

    current_position = CoachPositionContext.from_tree_context(tree_context)
    if current_fen:
        current_position = current_position.model_copy(
            update={"fen": current_fen, "pgn": current_pgn or current_position.pgn}
        )

    return CoachContext(
        current_position=current_position,
        question=question,
        intent=intent,
        current_prose=tuple(current_prose),
        supporting_prose=tuple(supporting_prose),
        candidate_continuations=candidate_continuations,
        source_attributions=tuple(source_attributions_by_id.values()),
        lichess_stats=lichess_stats,
        recommended_moves=tuple(RecommendedMove.model_validate(move) for move in (recommended_moves or ())),
        masters_stats=masters_stats,
        masters_moves=tuple(RecommendedMove.model_validate(move) for move in (masters_moves or ())),
        stockfish=stockfish if isinstance(stockfish, StockfishEval) else StockfishEval.model_validate(stockfish) if stockfish else None,
        fallbacks=fallbacks,
    )
