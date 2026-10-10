from typing import Literal

import chess
from pydantic import BaseModel, Field, field_validator


PedagogicalLevel = Literal["debutant", "intermediaire", "avance"]
FamilyStatus = Literal["pending", "running", "generated", "fallback", "failed", "skipped"]
CoachStatus = FamilyStatus


class AnalyzePositionRequest(BaseModel):
    fen: str = Field(min_length=1)
    pgn: str = Field(min_length=1)
    moves: list[str] = Field(min_length=1)
    level: PedagogicalLevel
    question: str | None = Field(default=None, max_length=500)
    rating_min: int | None = Field(default=None, ge=0)
    rating_max: int | None = Field(default=None, ge=0)
    session_id: str | None = Field(default=None, min_length=1)

    @field_validator("fen")
    @classmethod
    def validate_fen(cls, value: str) -> str:
        try:
            chess.Board(value)
        except ValueError as exc:
            raise ValueError("fen must be a valid chess FEN") from exc
        return value

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class SessionEndRequest(BaseModel):
    pass


class SessionMovePayload(BaseModel):
    ply: int = Field(ge=1)
    uci: str = Field(min_length=2)
    san: str = Field(min_length=1)
    fen: str = Field(min_length=1)

    @field_validator("fen")
    @classmethod
    def validate_fen(cls, value: str) -> str:
        try:
            chess.Board(value)
        except ValueError as exc:
            raise ValueError("fen must be a valid chess FEN") from exc
        return value


class SessionMove(BaseModel):
    ply: int
    uci: str
    san: str
    fen: str
    pgn: str
    created_at: str


class SessionAnalysisRecord(BaseModel):
    position_key: str
    fen: str = Field(min_length=1)
    response: dict | None = None
    facts: dict | None = None
    coach_status: str | None = None
    coach_explanation: str | None = None
    coach_fallbacks: list[str] = Field(default_factory=list)
    created_at: str | None = None


class SessionResponse(BaseModel):
    id: str
    started_at: str
    ended_at: str | None = None
    status: str
    moves: list[SessionMove] = Field(default_factory=list)
    analyses: list[SessionAnalysisRecord] = Field(default_factory=list)


class StockfishEvaluateRequest(BaseModel):
    fen: str = Field(min_length=1)

    @field_validator("fen")
    @classmethod
    def validate_fen(cls, value: str) -> str:
        try:
            chess.Board(value)
        except ValueError as exc:
            raise ValueError("fen must be a valid chess FEN") from exc
        return value


class Opening(BaseModel):
    eco: str
    name: str
    matched: bool
    source: str


class RecommendedMove(BaseModel):
    uci: str
    san: str
    description: str
    source: str
    games: int | None = None
    white: float | None = None
    draws: float | None = None
    black: float | None = None
    average_rating: int | None = None
    move_share: float | None = None
    relevant: bool = True
    badges: list[str] = Field(default_factory=list)


class LichessStats(BaseModel):
    source: str
    games: int
    white: float
    draws: float
    black: float


class RagContext(BaseModel):
    text: str
    source: str
    url: str | None
    chunk_id: str | None = None
    license_or_terms: str | None = None
    page_id: str | None = None
    section_index: int | None = None
    part_index: int | None = None
    section_title: str | None = None
    relation_to_position: str | None = None
    entry_move: str | None = None
    opening_name: str | None = None
    eco_code: str | None = None


class Video(BaseModel):
    title: str
    url: str
    source: str
    channel_title: str | None = None
    thumbnail_url: str | None = None
    published_at: str | None = None
    description: str | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    view_count: int | None = Field(default=None, ge=0)


class VideosResponse(BaseModel):
    videos: list[Video] = Field(default_factory=list)
    fallbacks_used: list[str] = Field(default_factory=list)
    cache: str


class AnalyzePositionResponse(BaseModel):
    opening: Opening
    recommended_moves: list[RecommendedMove]
    masters_moves: list[RecommendedMove] = Field(default_factory=list)
    masters_stats: LichessStats
    lichess_stats: LichessStats | dict
    source_confidence: dict = Field(default_factory=dict)
    rag_context: list[RagContext]
    coach_explanation: str
    coach_status: CoachStatus = "pending"
    analysis_key: str | None = None
    stockfish: dict | None
    videos: list[Video]
    fallbacks_used: list[str]
    session_id: str | None = None
    cache: dict = Field(default_factory=dict)
    run_id: str | None = None
    explorer_status: FamilyStatus = "generated"
    stockfish_status: FamilyStatus = "pending"
    rag_status: FamilyStatus = "pending"


class AnalysisRun(BaseModel):
    """Persisted unit shared by the progressive analysis endpoints."""

    run_id: str
    session_id: str | None = None
    analysis_key: str
    request_fingerprint: str
    fen: str
    pgn: str
    moves: list[str] = Field(default_factory=list)
    level: PedagogicalLevel
    question: str | None = None
    rating_min: int | None = None
    rating_max: int | None = None
    explorer_status: FamilyStatus = "pending"
    stockfish_status: FamilyStatus = "pending"
    rag_status: FamilyStatus = "pending"
    coach_status: FamilyStatus = "pending"
    explorer_facts: dict | None = None
    stockfish_result: dict | None = None
    stockfish_fallbacks: list[str] = Field(default_factory=list)
    rag_context: list[dict] = Field(default_factory=list)
    rag_tree_context: dict | None = None
    rag_retrieved_contexts: list[dict] = Field(default_factory=list)
    rag_fallbacks: list[str] = Field(default_factory=list)
    coach_context_artifact: dict | None = None
    coach_result: dict | None = None
    created_at: str
    updated_at: str


class AnalysisSnapshot(BaseModel):
    """Serializable source-bound facts stored inside an ``AnalysisRun``.

    Explorer writes the initial artifact; the RAG and Stockfish families add
    their own payloads to the run before coach rendering.
    """

    opening: Opening
    recommended_moves: list[RecommendedMove]
    masters_moves: list[RecommendedMove] = Field(default_factory=list)
    masters_stats: LichessStats
    lichess_stats: LichessStats | dict
    source_confidence: dict = Field(default_factory=dict)
    rag_context: list[RagContext] = Field(default_factory=list)
    stockfish: dict | None = None
    videos: list[Video] = Field(default_factory=list)
    fallbacks_used: list[str] = Field(default_factory=list)
    cache: dict = Field(default_factory=dict)
    coach_context: dict = Field(default_factory=dict)


class CoachExplanationRequest(BaseModel):
    run_id: str = Field(min_length=1)
    level: PedagogicalLevel


class CoachExplanationResponse(BaseModel):
    explanation: str
    coach_status: CoachStatus
    fallbacks_used: list[str] = Field(default_factory=list)


class AnalysisRunRequest(BaseModel):
    run_id: str = Field(min_length=1)


class StockfishRunResponse(BaseModel):
    stockfish: dict | None = None
    stockfish_status: FamilyStatus
    fallbacks_used: list[str] = Field(default_factory=list)


class RagContextResponse(BaseModel):
    rag_context: list[RagContext] = Field(default_factory=list)
    rag_status: FamilyStatus
    fallbacks_used: list[str] = Field(default_factory=list)
