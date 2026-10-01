from typing import Literal

import chess
from pydantic import BaseModel, Field, field_validator


PedagogicalLevel = Literal["debutant", "intermediaire", "avance"]


class AnalyzePositionRequest(BaseModel):
    fen: str = Field(min_length=1)
    pgn: str = Field(min_length=1)
    moves: list[str] = Field(min_length=1)
    level: PedagogicalLevel
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
    response: dict
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


class Video(BaseModel):
    title: str
    url: str
    source: str


class AnalyzePositionResponse(BaseModel):
    opening: Opening
    recommended_moves: list[RecommendedMove]
    masters_moves: list[RecommendedMove] = Field(default_factory=list)
    masters_stats: LichessStats
    lichess_stats: LichessStats | dict
    source_confidence: dict = Field(default_factory=dict)
    rag_context: list[RagContext]
    coach_explanation: str
    stockfish: dict | None
    videos: list[Video]
    fallbacks_used: list[str]
    session_id: str | None = None
    cache: dict = Field(default_factory=dict)
