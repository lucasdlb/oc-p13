from backend.app.services.coach_references import (
    parse_coach_reference,
    sanitize_coach_references,
)


FEN_AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
FEN_WHITE_TO_MOVE = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1"


def test_parser_keeps_move_square_and_line_intentions_separate() -> None:
    move = parse_coach_reference("move", "uci=e7e5,label=e5")

    assert move is not None
    assert move.kind == "move"
    assert move.uci == "e7e5"
    assert parse_coach_reference("square", "sq=e5,label=e5") is not None
    line = parse_coach_reference("line", "moves=e7e5,g8f6,label=e5 puis ...Nf6")

    assert line is not None
    assert line.kind == "line"
    assert line.moves == ("e7e5", "g8f6")


def test_sanitizer_rejects_other_side_and_illegal_sequence() -> None:
    text = (
        "Case [[square:sq=e5,label=e5]], coup [[move:uci=e7e5,label=e5]], "
        "adverse [[move:uci=e2e4,label=e4]], "
        "suite [[line:moves=e7e5,g1f3,g8f6,label=e5 puis Nf3 puis ...Nf6]], "
        "fausse suite [[line:moves=e7e5,e2e4,label=fausse]]."
    )

    sanitized = sanitize_coach_references(
        text,
        fen=FEN_AFTER_E4,
        allowed_moves={"e7e5"},
    )

    assert "[[square:sq=e5,label=e5]]" in sanitized
    assert "[[move:uci=e7e5,label=e5]]" in sanitized
    assert "[[line:moves=e7e5,g1f3,g8f6,label=e5 puis Nf3 puis ...Nf6]]" in sanitized
    assert "[[move:uci=e2e4" not in sanitized
    assert "[[line:moves=e7e5,e2e4" not in sanitized
    assert "fausse" in sanitized


def test_sanitizer_removes_unsupported_move_even_when_legal() -> None:
    sanitized = sanitize_coach_references(
        "[[move:uci=d7d5,label=d5]]",
        fen=FEN_AFTER_E4,
        allowed_moves={"e7e5"},
    )

    assert sanitized == "d5"


def test_sanitizer_repairs_empty_labels_from_the_current_position() -> None:
    sanitized = sanitize_coach_references(
        "Jouez **[[move:uci=e7e5,label=]]** et visez [[square:sq=e5,label=]].",
        fen=FEN_AFTER_E4,
        allowed_moves={"e7e5"},
    )

    assert "[[move:uci=e7e5,label=e5]]" in sanitized
    assert "[[square:sq=e5,label=e5]]" in sanitized


def test_sanitizer_normalizes_valid_move_labels_to_san() -> None:
    sanitized = sanitize_coach_references(
        "Jouez [[move:uci=b1c3,label=c3]].",
        fen=FEN_WHITE_TO_MOVE,
        allowed_moves={"b1c3"},
    )

    assert sanitized == "Jouez [[move:uci=b1c3,label=Nc3]]."


def test_sanitizer_preserves_move_number_labels_containing_san() -> None:
    sanitized = sanitize_coach_references(
        "### [[move:uci=g7g6,label=2...g6]]",
        fen="rnbqkbnr/pppppppp/8/5n2/2PP4/8/PP2PPPP/RNBQKBNR b KQkq c3 0 2",
        allowed_moves={"g7g6"},
    )

    assert sanitized == "### [[move:uci=g7g6,label=2...g6]]"


def test_sanitizer_keeps_unsupported_empty_labels_visible() -> None:
    sanitized = sanitize_coach_references(
        "Coup indisponible [[move:uci=e2e4,label=]].",
        fen=FEN_AFTER_E4,
        allowed_moves={"e7e5"},
    )

    assert sanitized == "Coup indisponible e2e4."
