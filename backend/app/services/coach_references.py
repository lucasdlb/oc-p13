"""Parse and validate the coach's structured inline references.

The coach may use a very small markup language so the frontend never has to
guess whether a SAN-looking word is a move, a square, or a variation.
"""

from dataclasses import dataclass, replace
import re
from typing import Literal

import chess


CoachReferenceKind = Literal["move", "square", "line"]

_UCI_PATTERN = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$", re.IGNORECASE)
_SQUARE_PATTERN = re.compile(r"^[a-h][1-8]$", re.IGNORECASE)
_MARKER_PATTERN = re.compile(r"\[\[([a-z]+):([^\[\]]*)\]\]", re.IGNORECASE)


@dataclass(frozen=True)
class CoachReference:
    """One parsed and validated reference intended for the UI."""

    kind: CoachReferenceKind
    label: str
    uci: str | None = None
    square: str | None = None
    moves: tuple[str, ...] = ()

    def to_markup(self) -> str:
        if self.kind == "move":
            return f"[[move:uci={self.uci},label={self.label}]]"
        if self.kind == "square":
            return f"[[square:sq={self.square},label={self.label}]]"
        return f"[[line:moves={','.join(self.moves)},label={self.label}]]"


def sanitize_coach_references(text: str, *, fen: str, allowed_moves: set[str]) -> str:
    """Keep only references that describe supported actions for ``fen``.

    Invalid or unsupported markers are replaced with their human label. This
    preserves readable prose while ensuring the frontend receives no fake
    interactive target.
    """

    board = _load_board(fen)

    def replace(match: re.Match[str]) -> str:
        kind = match.group(1).lower()
        body = match.group(2)
        reference = parse_coach_reference(kind, body)
        if reference is None or not _is_supported(reference, board, allowed_moves):
            return _label_from_body(body, board)
        reference = _repair_label(reference, board)
        return reference.to_markup()

    return _MARKER_PATTERN.sub(replace, text)


def parse_coach_reference(kind: str, body: str) -> CoachReference | None:
    """Parse one marker body without considering board state or provenance."""

    normalized_kind = kind.lower()
    if normalized_kind == "move":
        values = _parse_simple_attributes(body, required="uci")
        if values is None or not _UCI_PATTERN.fullmatch(values["uci"]):
            return None
        uci = values["uci"].lower()
        return CoachReference(
            kind="move",
            uci=uci,
            label=_label(values.get("label"), uci),
        )

    if normalized_kind == "square":
        values = _parse_simple_attributes(body, required="sq")
        if values is None or not _SQUARE_PATTERN.fullmatch(values["sq"]):
            return None
        square = values["sq"].lower()
        return CoachReference(
            kind="square",
            square=square,
            label=_label(values.get("label"), square),
        )

    if normalized_kind == "line":
        moves_text, separator, label = body.partition(",label=")
        if not separator or not moves_text.startswith("moves="):
            return None
        raw_moves = moves_text.removeprefix("moves=").split(",")
        if len(raw_moves) < 2 or not all(_UCI_PATTERN.fullmatch(move) for move in raw_moves):
            return None
        moves = tuple(move.lower() for move in raw_moves)
        return CoachReference(
            kind="line",
            moves=moves,
            label=_label(label, " puis ".join(moves)),
        )

    return None


def _parse_simple_attributes(body: str, *, required: str) -> dict[str, str] | None:
    values: dict[str, str] = {}
    for item in body.split(","):
        key, separator, value = item.partition("=")
        if not separator or key not in {required, "label"}:
            return None
        if key == required and not value.strip():
            return None
        if key in values:
            return None
        values[key] = value.strip()
    return values if required in values else None


def _is_supported(
    reference: CoachReference,
    board: chess.Board | None,
    allowed_moves: set[str],
) -> bool:
    if reference.kind == "square":
        return True

    if reference.kind == "move":
        assert reference.uci is not None
        if reference.uci not in allowed_moves:
            return False
        return board is None or _is_legal_sequence(board, (reference.uci,))

    if not reference.moves or reference.moves[0] not in allowed_moves:
        return False
    return board is None or _is_legal_sequence(board, reference.moves)


def _repair_label(reference: CoachReference, board: chess.Board | None) -> CoachReference:
    if reference.kind != "move" or board is None:
        return reference

    assert reference.uci is not None
    move = chess.Move.from_uci(reference.uci)
    if board.is_legal(move):
        san = board.san(move)
        if reference.label.startswith("..."):
            san = f"...{san}"
        return replace(reference, label=san)
    return reference


def _is_legal_sequence(board: chess.Board, moves: tuple[str, ...]) -> bool:
    candidate = board.copy(stack=False)
    for uci in moves:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            return False
        if not candidate.is_legal(move):
            return False
        candidate.push(move)
    return True


def _load_board(fen: str) -> chess.Board | None:
    try:
        return chess.Board(fen)
    except ValueError:
        return None


def _label(value: str | None, fallback: str) -> str:
    cleaned = " ".join((value or fallback).split())
    return cleaned[:120] or fallback


def _label_from_body(body: str, board: chess.Board | None = None) -> str:
    match = re.search(r"(?:^|,)label=([^,]*)", body)
    label = " ".join(match.group(1).split()) if match else ""
    if label:
        return label[:120]

    uci_match = re.search(r"(?:^|,)uci=([^,]*)", body)
    if uci_match:
        uci = uci_match.group(1).strip().lower()
        if board is not None:
            try:
                move = chess.Move.from_uci(uci)
                if board.is_legal(move):
                    return board.san(move)
            except ValueError:
                pass
        return uci[:120]

    square_match = re.search(r"(?:^|,)sq=([^,]*)", body)
    if square_match:
        return square_match.group(1).strip().lower()[:120]

    moves_match = re.search(r"(?:^|,)moves=([^,]+(?:,[^,]+)*)(?:,label=|$)", body)
    if moves_match:
        return " puis ".join(part.strip().lower() for part in moves_match.group(1).split(","))[:120]

    return ""
