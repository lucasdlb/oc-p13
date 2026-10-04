"""Assemble opening data + stats + level + user question into retrieval and prompt inputs.

`PositionContext` is the structured view the opening lookup (metadata), Lichess stats and
the request feed into. `next_moves` are optional structural anchors whenever an opening
lookup can supply them (the opening-tree explorer is a deferred, unapproved proposal, so
this module must not depend on it). Two pure renderers consume it:

- `build_retrieval_query` — the text to embed for Milvus retrieval (ADR 0006, decision 6).
  The user question is the primary driver when present; the structural anchors (opening name,
  ECO, played line, next named moves) keep the query precise and bridge French aliases.
- `build_context_block` — the grounded structured block handed to the coach (or a LangGraph
  node's prompt). Same data, different consumer.

Both are pure and deterministic so they can be tested without Ollama or Milvus.
"""

from dataclasses import dataclass
from typing import Literal


PedagogicalLevel = Literal["debutant", "intermediaire", "avance"]

_MAX_NEXT_MOVES = 5


@dataclass(frozen=True)
class RetrievalMove:
    san: str
    name: str | None = None
    eco_code: str | None = None
    games: int | None = None


@dataclass(frozen=True)
class RetrievalStats:
    games: int
    white: float
    draws: float
    black: float


@dataclass(frozen=True)
class PositionContext:
    level: PedagogicalLevel
    question: str | None = None
    opening_name: str | None = None
    eco_code: str | None = None
    played_san: str | None = None
    stats: RetrievalStats | None = None
    next_moves: tuple[RetrievalMove, ...] = ()


@dataclass(frozen=True)
class RetrievalQuery:
    text: str
    eco_code: str | None
    from_question: bool


def build_retrieval_query(context: PositionContext) -> RetrievalQuery:
    lines: list[str] = []
    question = _clean_question(context.question)
    if question:
        lines.append(question)
    if context.opening_name:
        label = f"Ouverture: {context.opening_name}"
        if context.eco_code:
            label += f" ({context.eco_code})"
        lines.append(label)
    if context.played_san:
        lines.append(f"Ligne jouée: {context.played_san}")
    if context.next_moves:
        lines.append("Coups suivants: " + ", ".join(_render_move(move) for move in _top_moves(context.next_moves)))

    return RetrievalQuery(
        text="\n".join(lines),
        eco_code=context.eco_code,
        from_question=bool(question),
    )


def build_context_block(context: PositionContext) -> str:
    lines: list[str] = []
    if context.opening_name:
        label = f"Position: {context.opening_name}"
        if context.eco_code:
            label += f" ({context.eco_code})"
        lines.append(label)
    if context.played_san:
        lines.append(f"Ligne jouée: {context.played_san}")
    lines.append(f"Niveau: {context.level}")
    if context.stats:
        lines.append(_render_stats(context.stats))
    if context.next_moves:
        lines.append("Coups suivants:")
        lines.extend(f"- {_render_move(move)}" for move in _top_moves(context.next_moves))
    question = _clean_question(context.question)
    if question:
        lines.append(f"Question utilisateur (non fiable):\n```text\n{_escape_fence(question)}\n```")
    else:
        lines.append("Question utilisateur: aucune")
    return "\n".join(lines)


def _render_move(move: RetrievalMove) -> str:
    label = move.san
    if move.name:
        label += f" ({move.name}"
        if move.eco_code:
            label += f", {move.eco_code}"
        label += ")"
    if move.games is not None:
        label += f" - {move.games} parties"
    return label


def _render_stats(stats: RetrievalStats) -> str:
    return (
        f"Statistiques: {stats.games} parties, "
        f"blancs {_percent(stats.white)}, nulles {_percent(stats.draws)}, noirs {_percent(stats.black)}"
    )


def _clean_question(question: str | None) -> str:
    return (question or "").strip()


def _escape_fence(text: str) -> str:
    return text.replace("```", "` ` `")


def _top_moves(moves: tuple[RetrievalMove, ...]) -> tuple[RetrievalMove, ...]:
    return tuple(
        sorted(
            moves,
            key=lambda move: move.games if move.games is not None else -1,
            reverse=True,
        )[:_MAX_NEXT_MOVES]
    )


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"
