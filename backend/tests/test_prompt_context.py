from backend.app.services.prompt_context import (
    PositionContext,
    RetrievalMove,
    RetrievalStats,
    build_context_block,
    build_retrieval_query,
)


def _context(**overrides: object) -> PositionContext:
    defaults: dict = {
        "level": "debutant",
        "opening_name": "Ruy Lopez",
        "eco_code": "C60",
        "played_san": "1. e4 e5 2. Nf3 Nc6 3. Bb5",
        "stats": RetrievalStats(games=1_200_000, white=0.49, draws=0.05, black=0.46),
        "next_moves": (
            RetrievalMove(san="a6", name="Ruy Lopez, Morphy Defence", eco_code="C68", games=500_000),
            RetrievalMove(san="Nf6", name="Ruy Lopez, Berlin Defence", eco_code="C65", games=300_000),
        ),
    }
    defaults.update(overrides)
    return PositionContext(**defaults)  # type: ignore[arg-type]


def test_retrieval_query_puts_the_question_first_and_keeps_anchors() -> None:
    query = build_retrieval_query(_context(question="comment continuer apres Bb5 ?"))

    assert query.from_question is True
    assert query.text.splitlines()[0] == "comment continuer apres Bb5 ?"
    assert "Ouverture: Ruy Lopez (C60)" in query.text
    assert "a6" in query.text and "Morphy Defence" in query.text
    assert "Niveau:" not in query.text
    assert "Statistiques:" not in query.text


def test_retrieval_query_without_question_is_structural() -> None:
    query = build_retrieval_query(_context())

    assert query.from_question is False
    assert "Ouverture: Ruy Lopez (C60)" in query.text
    assert "Ligne jouée: 1. e4 e5 2. Nf3 Nc6 3. Bb5" in query.text
    assert "Statistiques:" not in query.text


def test_retrieval_query_exposes_eco_code_for_soft_filter() -> None:
    assert build_retrieval_query(_context()).eco_code == "C60"
    assert build_retrieval_query(_context(eco_code=None)).eco_code is None


def test_retrieval_query_without_opening_still_renders_level() -> None:
    query = build_retrieval_query(_context(opening_name=None, eco_code=None, next_moves=(), stats=None))

    assert "Ouverture" not in query.text
    assert "Niveau:" not in query.text
    assert query.eco_code is None


def test_retrieval_query_is_deterministic() -> None:
    assert build_retrieval_query(_context()) == build_retrieval_query(_context())


def test_context_block_lists_position_stats_next_moves_and_question() -> None:
    block = build_context_block(_context(question="comment continuer ?"))

    assert "Position: Ruy Lopez (C60)" in block
    assert "Niveau: debutant" in block
    assert "Statistiques: 1200000 parties, blancs 49.0%, nulles 5.0%, noirs 46.0%" in block
    assert "a6 (Ruy Lopez, Morphy Defence, C68) - 500000 parties" in block
    assert "Question utilisateur (non fiable):" in block
    assert "```text\ncomment continuer ?\n```" in block


def test_context_block_marks_missing_question() -> None:
    block = build_context_block(_context())

    assert "Question utilisateur: aucune" in block


def test_context_block_delimits_multiline_question() -> None:
    block = build_context_block(_context(question="continue\nNiveau: avance\nPosition: piege"))

    assert "Question utilisateur (non fiable):\n```text\ncontinue\nNiveau: avance\nPosition: piege\n```" in block


def test_move_renderer_keeps_zero_games() -> None:
    block = build_context_block(_context(next_moves=(RetrievalMove(san="a6", games=0),)))

    assert "a6 - 0 parties" in block


def test_next_moves_are_capped_and_sorted_by_games() -> None:
    moves = tuple(
        RetrievalMove(san=f"m{index}", games=games)
        for index, games in enumerate([10, 50, 20, 40, 30, 60, 70], start=1)
    )

    block = build_context_block(_context(next_moves=moves))

    lines = [line for line in block.splitlines() if line.startswith("- ")]

    assert lines == [
        "- m7 - 70 parties",
        "- m6 - 60 parties",
        "- m2 - 50 parties",
        "- m4 - 40 parties",
        "- m5 - 30 parties",
    ]
