import chess
import pytest

from backend.app.services.coach_prompt import allowed_move_records, build_prompt
from backend.app.services.retrieval_contracts import (
    CoachContext,
    CoachPositionContext,
    CoachProsePassage,
    CoachSourceAttribution,
)


START_FEN = chess.Board().fen()
AFTER_E4_FEN = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1").fen()


def _context(
    fen: str = START_FEN,
    *,
    recommended_moves: list[dict] | None = None,
    passages: tuple[CoachProsePassage, ...] = (),
) -> CoachContext:
    sources = tuple(
        CoachSourceAttribution(
            chunk_id=passage.source_chunk_id,
            source="wikibooks",
            source_url="https://example.test/source",
            license_or_terms="CC BY-SA 4.0",
            page_id=passage.source_chunk_id,
            canonical_title="Opening source",
            section_title="Plans",
            section_index=0,
            part_index=0,
        )
        for passage in passages
    )
    return CoachContext(
        current_position=CoachPositionContext(
            state="matched",
            opening_name="Opening",
            eco_code="C20",
            pgn="1. e4",
            fen=fen,
        ),
        question="Quel est le plan ?",
        current_prose=passages,
        source_attributions=sources,
        recommended_moves=tuple(recommended_moves or ()),
    )


def test_prompt_snapshot_keeps_grounding_sections_and_reference_syntax() -> None:
    context = _context(recommended_moves=[{"san": "e4", "uci": "e2e4", "games": 10}])

    prompt = build_prompt(context, "debutant")

    assert prompt.splitlines()[:8] == [
        "QUESTION DE L'UTILISATEUR A TRAITER EN PRIORITE :",
        "Quel est le plan ?",
        "<question>Quel est le plan ?</question>",
        "Question de l'utilisateur :",
        "",
        "Niveau : debutant",
        "Ouverture : Opening (C20)",
        "Ligne jouee : 1. e4",
    ]
    assert "Coups autorises (UCI obligatoire dans les marqueurs) :" in prompt
    assert "- e4 -> e2e4" in prompt
    assert prompt.endswith("Quel est le plan ?")


@pytest.mark.parametrize(
    ("fen", "moves"),
    [
        (START_FEN, ["e2e4", "d2d4", "g1f3"]),
        (AFTER_E4_FEN, ["e7e5", "g8f6", "d7d5"]),
    ],
)
def test_every_allowed_uci_is_legal_and_has_position_san(fen: str, moves: list[str]) -> None:
    context = _context(
        fen,
        recommended_moves=[{"san": "ignored", "uci": move} for move in moves],
    )
    board = chess.Board(fen)

    records = allowed_move_records(context)

    assert {record["uci"] for record in records} == set(moves)
    assert all(board.is_legal(chess.Move.from_uci(record["uci"])) for record in records)
    assert all(record["san"] == board.san(chess.Move.from_uci(record["uci"])) for record in records)


def test_allowed_moves_drop_illegal_and_keep_first_record_for_duplicate_uci() -> None:
    context = _context(
        recommended_moves=[
            {"san": "wrong label", "uci": "e2e4"},
            {"san": "illegal", "uci": "e2e5"},
        ],
    ).model_copy(update={"stockfish": {"best_move": "e2e4"}})

    records = allowed_move_records(context)

    assert records == [{"san": "e4", "uci": "e2e4"}]


def test_worst_case_prompt_stays_under_ollama_context_budget() -> None:
    passages = tuple(
        CoachProsePassage(
            text=(f"source-{index} " * 500).strip(),
            relation_to_position="current",
            source_chunk_id=f"chunk-{index}",
        )
        for index in range(5)
    )
    prompt = build_prompt(
        _context(
            recommended_moves=[{"san": "e4", "uci": "e2e4", "games": 100}] * 12,
            passages=passages,
        ),
        "intermediaire",
    )

    budget_chars = (16384 - 1000) * 3
    assert len(prompt) < budget_chars
