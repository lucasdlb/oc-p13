import chess
import pytest

from backend.app.services.coach_prompt import (
    _expand_chess_annotations,
    allowed_move_records,
    build_prompt,
    system_prompt,
)
from backend.app.services.coach_references import find_illegal_san_citations
from backend.app.services.retrieval_contracts import (
    CoachContext,
    CoachPositionContext,
    CoachProsePassage,
    CoachSourceAttribution,
)


START_FEN = chess.Board().fen()
AFTER_E4_FEN = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1").fen()


def test_expand_chess_annotations_explains_attached_symbols() -> None:
    text = _expand_chess_annotations("1...e5?! puis 3...Qf6!? et 4.Bxh7+")

    assert "e5?! [annotation: coup douteux, risque ou imprecis]" in text
    assert "Qf6!? [annotation: coup interessant ou speculatif]" in text
    assert "Bxh7+" in text
    assert "Bxh7+ [annotation:" not in text


def test_expand_chess_annotations_ignores_unattached_question_marks() -> None:
    assert _expand_chess_annotations("Pourquoi ? Une bonne idee.") == "Pourquoi ? Une bonne idee."


def _context(
    fen: str = START_FEN,
    *,
    recommended_moves: list[dict] | None = None,
    passages: tuple[CoachProsePassage, ...] = (),
    intent: str | None = None,
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
        intent=intent,
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
    assert "- [[move:uci=e2e4,label=e4]]" in prompt
    assert prompt.endswith("Quel est le plan ?")


def test_prompt_marks_out_of_theory_state_without_opening_context() -> None:
    context = _context().model_copy(
        update={
            "current_position": CoachPositionContext(
                state="out_of_theory",
                opening_name=None,
                eco_code=None,
                pgn=None,
                fen=START_FEN,
            )
        }
    )

    prompt = build_prompt(context, "debutant")

    assert "Etat : position hors theorie connue" in prompt
    assert "Ouverture :" not in prompt
    assert "n'expliquez pas une ouverture precedente comme contexte courant" in prompt


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


def test_question_intent_uses_direct_criterion_structure_and_top_three_moves() -> None:
    context = _context(
        intent="compare_moves",
        recommended_moves=[
            {"san": "e4", "uci": "e2e4", "move_share": 0.2},
            {"san": "d4", "uci": "d2d4", "move_share": 0.8},
            {"san": "Nf3", "uci": "g1f3", "move_share": 0.5},
            {"san": "c4", "uci": "c2c4", "move_share": 0.1},
        ],
    )

    prompt = build_prompt(context, "intermediaire")

    assert "Reponse directe : (nommez le critere demande)" in system_prompt(context.intent)
    assert "| d4 | d2d4 |" in prompt
    assert "| Nf3 | g1f3 |" in prompt
    assert "| e4 | e2e4 |" in prompt
    assert "| c4 | c2c4 |" not in prompt


def test_system_prompt_keeps_source_provenance_out_of_coach_voice() -> None:
    prompt = system_prompt("compare_moves")

    assert "Parlez d'echecs comme un coach" in prompt
    assert "jamais du document" in prompt
    assert "la source indique" in prompt
    assert "selon les sources" in prompt
    assert "La provenance est geree par l'interface" in prompt
    assert "nuance strategique tiree des faits" in prompt


def test_prose_detector_reports_illegal_san_without_rewriting() -> None:
    findings = find_illegal_san_citations("Le plan preparant Bg4 est actif.", AFTER_E4_FEN)

    assert findings == ("Bg4",)


def test_compare_prompt_contains_computed_table_and_engine_fallback() -> None:
    context = _context(
        intent="compare_moves",
        recommended_moves=[{"san": "e4", "uci": "e2e4", "move_share": 0.7}],
    )

    prompt = build_prompt(context, "intermediaire")

    assert "Tableau comparatif determine" in prompt
    assert "| [[move:uci=e2e4,label=e4]] | 70.0%" in prompt
    assert "repli: moteur indisponible" in prompt


def test_evidence_pack_renders_lichess_and_stockfish_as_explicit_tables() -> None:
    context = _context(
        recommended_moves=[
            {
                "san": "e4",
                "uci": "e2e4",
                "games": 145000,
                "move_share": 0.52,
                "white": 0.52,
                "draws": 0.08,
                "black": 0.40,
            },
            {
                "san": "d4",
                "uci": "d2d4",
                "games": 98000,
                "move_share": 0.35,
                "white": 0.49,
                "draws": 0.12,
                "black": 0.39,
            },
        ],
    ).model_copy(
        update={
            "lichess_stats": {
                "source": "lichess-opening-explorer",
                "games": 243000,
            },
            "stockfish": {
                "status": "ok",
                "best_move": "e2e4",
                "score": {"type": "cp", "value": 35},
                "depth": 18,
                "pv": ("e2e4", "e7e5", "g1f3"),
                "multipv": 2,
                "variations": [
                    {
                        "best_move": "e2e4",
                        "score": {"type": "cp", "value": 35},
                        "pv": ("e2e4", "e7e5", "g1f3"),
                    },
                    {
                        "best_move": "d2d4",
                        "score": {"type": "cp", "value": 22},
                        "pv": ("d2d4", "d7d5"),
                    },
                ],
            },
        }
    )

    prompt = build_prompt(context, "intermediaire")

    assert "EVIDENCE PACK" in prompt
    assert "Source: lichess-opening-explorer | Parties totales: 243000" in prompt
    assert "| e4 | e2e4 | 145000 | 52.0% | 52.0% | 8.0% | 40.0% |" in prompt
    assert "Position: actuelle | Trait: Blancs | Profondeur: 18" in prompt
    assert "| 1 | e4 | e2e4 | +0.35 pion | e4 e5 Nf3 |" in prompt
    assert "| 2 | d4 | d2d4 | +0.22 pion | d4 d5 |" in prompt
    assert "Les statistiques Explorer/Lichess decrivent la pratique observee" in prompt


def test_stockfish_variants_are_added_to_allowed_moves_only_when_legal() -> None:
    context = _context().model_copy(
        update={
            "stockfish": {
                "status": "ok",
                "best_move": "e2e4",
                "variations": [
                    {"best_move": "d2d4", "pv": ("d2d4",)},
                    {"best_move": "e2e5", "pv": ("e2e5",)},
                ],
            }
        }
    )

    records = allowed_move_records(context)

    assert [record["uci"] for record in records] == ["e2e4", "d2d4"]
