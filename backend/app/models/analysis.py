from typing import Literal

import chess
from pydantic import BaseModel, Field, field_validator


PedagogicalLevel = Literal["debutant", "intermediaire", "avance"]


class AnalyzePositionRequest(BaseModel):
    fen: str = Field(min_length=1)
    pgn: str = Field(min_length=1)
    moves: list[str] = Field(min_length=1)
    level: PedagogicalLevel

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
    lichess_stats: LichessStats | dict
    rag_context: list[RagContext]
    coach_explanation: str
    stockfish: dict | None
    videos: list[Video]
    fallbacks_used: list[str]
