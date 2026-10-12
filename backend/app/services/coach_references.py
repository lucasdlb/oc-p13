"""Validated chess references used by the coach and the frontend."""

from dataclasses import dataclass, replace
import re
from typing import Literal

import chess

from backend.app.services.retrieval_contracts import CoachContext


CoachReferenceKind = Literal["move", "square", "line"]
_UCI_PATTERN = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$", re.IGNORECASE)
_SQUARE_PATTERN = re.compile(r"^[a-h][1-8]$", re.IGNORECASE)
_MARKER_PATTERN = re.compile(r"\[\[([a-z]+):([^\[\]]*)\]\]", re.IGNORECASE)
_SAN_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:O-O-O|O-O|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_UCI_TOKEN_PATTERN = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$", re.IGNORECASE)
_SQUARE_TOKEN_PATTERN = re.compile(r"[a-h][1-8]", re.IGNORECASE)
_SQUARE_CONTEXT_PATTERN = re.compile(
    r"\b(?:cases?(?:\s+(?:centrale?|strategique|strategiques|critique|critiques|importante|importantes|cible|cibles))?"
    r"|sur(?:\s+(?:la|les))?(?:\s+cases?)?|pions?)\s+(?P<squares>(?:\*\*)?[a-h][1-8](?:\*\*)?"
    r"(?:\s*(?:,|ou|et)\s*(?:\*\*)?[a-h][1-8](?:\*\*)?)*)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MoveRecord:
    uci: str
    san: str


@dataclass(frozen=True)
class MoveIndex:
    board: chess.Board | None
    records: tuple[MoveRecord, ...]

    @classmethod
    def from_context(cls, context: CoachContext) -> "MoveIndex":
        board = board_from_fen(context.current_position.fen)
        if board is None:
            return cls(None, tuple(_candidate_records(context)))

        candidates = [str(_value(move, "uci") or "") for move in context.recommended_moves]
        candidates.extend(str(_value(move, "uci") or "") for move in context.masters_moves)
        candidates.extend(_stockfish_move_uci(context.stockfish))
        candidates.extend(
            continuation.entry_uci
            for continuation in context.candidate_continuations
            if continuation.entry_uci
        )
        records: list[MoveRecord] = []
        seen: set[str] = set()
        for raw_uci in candidates:
            if not raw_uci or raw_uci in seen:
                continue
            try:
                move = chess.Move.from_uci(raw_uci)
            except ValueError:
                continue
            if board.is_legal(move):
                seen.add(raw_uci)
                records.append(MoveRecord(raw_uci, board.san(move)))
        return cls(board, tuple(records))


@dataclass(frozen=True)
class CoachReference:
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


def board_from_fen(fen: str | None) -> chess.Board | None:
    if not fen:
        return None
    try:
        return chess.Board(fen)
    except (TypeError, ValueError):
        return None


def sanitize_coach_references(text: str, *, fen: str | None, allowed_moves: set[str]) -> str:
    board = board_from_fen(fen)

    def replace_marker(match: re.Match[str]) -> str:
        reference = parse_coach_reference(match.group(1), match.group(2))
        if reference is None or not _is_supported(reference, board, allowed_moves):
            return _label_from_body(match.group(2), board)
        return _repair_label(reference, board).to_markup()

    return _MARKER_PATTERN.sub(replace_marker, text)


def annotate_references(text: str, index: MoveIndex) -> str:
    if index.board is None:
        return text
    enriched = _annotate_line_reference(text, index)
    enriched = _annotate_square_reference(enriched)
    for record in index.records:
        enriched = _annotate_move_reference(enriched, record)
    return enriched


def find_illegal_san_citations(text: str, fen: str | None) -> tuple[str, ...]:
    """Report SAN-like citations that fail parsing, without changing the prose."""
    board = board_from_fen(fen)
    if board is None:
        return ()
    masked = _mask_coach_markers(text)
    findings: list[str] = []
    for match in _SAN_TOKEN_PATTERN.finditer(masked):
        prefix = masked[:match.start()].lower()
        if not re.search(r"(?:joue|jouer|coup|apres|après|preparant|préparant|suivi de|si)\s*$", prefix):
            continue
        if _parse_move_token(board, match.group(0)) is None and match.group(0) not in findings:
            findings.append(match.group(0))
    return tuple(findings)


def parse_coach_reference(kind: str, body: str) -> CoachReference | None:
    normalized_kind = kind.lower()
    if normalized_kind == "move":
        values = _parse_simple_attributes(body, required="uci")
        if values is None or not _UCI_PATTERN.fullmatch(values["uci"]):
            return None
        uci = values["uci"].lower()
        return CoachReference("move", _label(values.get("label"), uci), uci=uci)
    if normalized_kind == "square":
        values = _parse_simple_attributes(body, required="sq")
        if values is None or not _SQUARE_PATTERN.fullmatch(values["sq"]):
            return None
        square = values["sq"].lower()
        return CoachReference("square", _label(values.get("label"), square), square=square)
    if normalized_kind == "line":
        moves_text, separator, label = body.partition(",label=")
        if not separator or not moves_text.startswith("moves="):
            return None
        raw_moves = moves_text.removeprefix("moves=").split(",")
        if len(raw_moves) < 2 or not all(_UCI_PATTERN.fullmatch(move) for move in raw_moves):
            return None
        moves = tuple(move.lower() for move in raw_moves)
        return CoachReference("line", _label(label, " puis ".join(moves)), moves=moves)
    return None


def _annotate_line_reference(text: str, index: MoveIndex) -> str:
    masked = _mask_coach_markers(text)
    matches = list(_SAN_TOKEN_PATTERN.finditer(masked))
    allowed_moves = {record.uci for record in index.records}
    board = index.board
    if board is None:
        return text
    for start, first in enumerate(matches):
        board_copy = board.copy(stack=False)
        parsed: list[tuple[str, str]] = []
        last = None
        for match in matches[start:]:
            if last is not None and not _is_sequence_gap(masked[last.end():match.start()]):
                break
            move = _parse_move_token(board_copy, match.group(0))
            if move is None:
                break
            parsed.append((move.uci(), board_copy.san(move)))
            board_copy.push(move)
            last = match
        if len(parsed) >= 2 and parsed[0][0] in allowed_moves and last is not None:
            label = " puis ".join(san for _, san in parsed)
            marker = f"[[line:moves={','.join(uci for uci, _ in parsed)},label={label}]]"
            return text[:first.start()] + marker + text[last.end():]
    return text


def _annotate_square_reference(text: str) -> str:
    masked = _mask_coach_markers(text)
    replacements: list[tuple[int, int, str]] = []
    for context_match in _SQUARE_CONTEXT_PATTERN.finditer(masked):
        squares = context_match.group("squares")
        squares_start = context_match.start("squares")
        for square_match in _SQUARE_TOKEN_PATTERN.finditer(squares):
            square = square_match.group(0).lower()
            start = squares_start + square_match.start()
            replacements.append((start, squares_start + square_match.end(), f"[[square:sq={square},label={square}]]"))
    for start, end, replacement in reversed(replacements):
        text = text[:start] + replacement + text[end:]
    return text


def _annotate_move_reference(text: str, record: MoveRecord) -> str:
    # Only annotate explicit move contexts; bare squares remain readable squares.
    for token in (record.san, record.uci):
        while True:
            masked = _mask_coach_markers(text)
            match = _find_move_match(masked, token)
            if not match:
                break
            marker = f"[[move:uci={record.uci},label={record.san}]]"
            text = text[:match.start()] + marker + text[match.end():]
    return text


def _find_move_match(text: str, token: str) -> re.Match[str] | None:
    pattern = rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])"
    for match in re.finditer(pattern, text, re.IGNORECASE):
        if _UCI_TOKEN_PATTERN.fullmatch(token):
            return match
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_prefix = text[line_start:match.start()]
        line_suffix = text[match.end():]
        if re.fullmatch(r"\s*(?:[-*]\s*)?", line_prefix) and re.match(r"\s*:", line_suffix):
            return match
        prefix = text[:match.start()].rstrip("* ")
        if re.search(r"(?:jouer|joue|coup|si|regardez|suite|ou|,)\s*$|\d+\.(?:\.\.)?$", prefix, re.IGNORECASE):
            return match
    return None


def _parse_move_token(board: chess.Board, token: str) -> chess.Move | None:
    if _UCI_TOKEN_PATTERN.fullmatch(token):
        try:
            move = chess.Move.from_uci(token.lower())
        except ValueError:
            return None
        return move if board.is_legal(move) else None
    try:
        return board.parse_san(token)
    except ValueError:
        return None


def _is_sequence_gap(gap: str) -> bool:
    return bool(re.fullmatch(r"\s*(?:(?:\d+\.)|puis|,|;|:|->|…|\.\.\.)*\s*", gap, re.IGNORECASE))


def _mask_coach_markers(text: str) -> str:
    return _MARKER_PATTERN.sub(lambda match: " " * len(match.group(0)), text)


def _is_supported(reference: CoachReference, board: chess.Board | None, allowed_moves: set[str]) -> bool:
    if reference.kind == "square":
        return True
    moves = (reference.uci,) if reference.kind == "move" else reference.moves
    if not moves or moves[0] not in allowed_moves:
        return False
    return board is not None and _is_legal_sequence(board, tuple(moves))


def _repair_label(reference: CoachReference, board: chess.Board | None) -> CoachReference:
    if reference.kind != "move" or board is None or reference.uci is None:
        return reference
    move = chess.Move.from_uci(reference.uci)
    if board.is_legal(move):
        san = board.san(move)
        if _label_contains_san(reference.label, san):
            return reference
        if reference.label.startswith("..."):
            san = f"...{san}"
        return replace(reference, label=san)
    return reference


def _label_contains_san(label: str, san: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(san)}(?![A-Za-z0-9])", label, re.IGNORECASE))


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


def _parse_simple_attributes(body: str, *, required: str) -> dict[str, str] | None:
    values: dict[str, str] = {}
    for item in body.split(","):
        key, separator, value = item.partition("=")
        if not separator or key not in {required, "label"} or key in values:
            return None
        values[key] = value.strip()
    return values if values.get(required) else None


def _candidate_records(context: CoachContext) -> list[MoveRecord]:
    candidates: list[tuple[str, str]] = [
        (str(_value(move, "san") or "?"), str(_value(move, "uci") or ""))
        for move in (*context.recommended_moves, *context.masters_moves)
    ]
    if context.stockfish:
        candidates.extend(("?", uci) for uci in _stockfish_move_uci(context.stockfish))
    candidates.extend((continuation.entry_move, continuation.entry_uci or "") for continuation in context.candidate_continuations)
    seen: set[str] = set()
    return [MoveRecord(uci, san) for san, uci in candidates if uci and not (uci in seen or seen.add(uci))]


def _stockfish_move_uci(stockfish: object) -> list[str]:
    if not stockfish:
        return []
    candidates: list[str] = []
    best = _value(stockfish, "best_move")
    if isinstance(best, str) and best:
        candidates.append(best)
    variations = _value(stockfish, "variations")
    if isinstance(variations, (list, tuple)):
        for variation in variations[:3]:
            move = _value(variation, "best_move")
            if isinstance(move, str) and move:
                candidates.append(move)
    return list(dict.fromkeys(candidates))


def _label(value: str | None, fallback: str) -> str:
    return " ".join((value or fallback).split())[:120] or fallback


def _label_from_body(body: str, board: chess.Board | None = None) -> str:
    match = re.search(r"(?:^|,)label=([^,]*)", body)
    if match and (label := " ".join(match.group(1).split())):
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


def _value(value: object, field: str) -> object:
    if isinstance(value, dict):
        return value.get(field)
    return getattr(value, field, None)
