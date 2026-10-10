from dataclasses import replace as dataclass_replace

import pytest

from backend.app.services.coach import ConservativeCoachService, LlmCoachService, prepare_coach_output
from backend.app.services.llm import (
    FakeLLMProvider,
    LLMProviderEmptyError,
    LLMProviderError,
    LLMProviderTimeoutError,
)
from backend.app.services.retrieval_contracts import (
    CoachCandidateContinuation,
    CoachContext,
    CoachPositionContext,
    CoachProsePassage,
    CoachSourceAttribution,
)


def replace(obj, /, **changes):
    if hasattr(obj, "model_copy"):
        return obj.model_copy(update=changes)
    return dataclass_replace(obj, **changes)


SOURCE = CoachSourceAttribution(
    chunk_id="chunk-ruy",
    source="wikibooks-chess-opening-theory",
    source_url="https://en.wikibooks.org/wiki/Chess_Opening_Theory/Ruy_Lopez",
    license_or_terms="CC BY-SA 4.0",
    page_id="wikibooks::ruy-lopez",
    canonical_title="Chess Opening Theory/Ruy Lopez",
    section_title="Plans",
    section_index=1,
    part_index=0,
)

CHILD_SOURCE = CoachSourceAttribution(
    chunk_id="chunk-berlin",
    source="wikibooks-chess-opening-theory",
    source_url="https://en.wikibooks.org/wiki/Chess_Opening_Theory/Ruy_Lopez/Berlin",
    license_or_terms="CC BY-SA 4.0",
    page_id="wikibooks::berlin",
    canonical_title="Chess Opening Theory/Ruy Lopez/Berlin",
    section_title="Berlin defence",
    section_index=0,
    part_index=0,
)


def _context(*, sources: tuple[CoachSourceAttribution, ...] = (SOURCE, CHILD_SOURCE)) -> CoachContext:
    return CoachContext(
        current_position=CoachPositionContext(
            state="matched",
            opening_name="Ruy Lopez",
            eco_code="C60",
            pgn="1. e4 e5 2. Nf3 Nc6 3. Bb5",
            fen="ruy-fen",
        ),
        current_prose=(
            CoachProsePassage(
                text="The Ruy Lopez increases pressure on e5 and prepares castling.",
                relation_to_position="current",
                source_chunk_id="chunk-ruy",
                opening_name="Ruy Lopez",
                eco_code="C60",
            ),
        ),
        candidate_continuations=(
            CoachCandidateContinuation(
                entry_move="Nf6",
                opening_name="Ruy Lopez: Berlin Defense",
                eco_code="C65",
                prose=(
                    CoachProsePassage(
                        text="The Berlin Defense begins after Black answers 3.Bb5 with ...Nf6.",
                        relation_to_position="child",
                        entry_move="Nf6",
                        source_chunk_id="chunk-berlin",
                        opening_name="Ruy Lopez: Berlin Defense",
                        eco_code="C65",
                    ),
                ),
            ),
        ),
        source_attributions=sources,
    )


def test_conservative_coach_renders_current_and_child_prose_separately() -> None:
    explanation = ConservativeCoachService().explain(_context(), level="intermediaire").text

    assert "Ruy Lopez (C60)" in explanation
    assert "Dans la position actuelle" in explanation
    assert "The Ruy Lopez increases pressure on e5" in explanation
    assert "Si le camp au trait joue ...Nf6" in explanation
    assert "The Berlin Defense begins" in explanation
    assert "[source: Plans, CC BY-SA 4.0]" in explanation
    assert "[source: Berlin defence, CC BY-SA 4.0]" in explanation


def test_conservative_coach_keeps_child_move_conditional_and_side_aware() -> None:
    context = replace(
        _context(),
        current_position=replace(
            _context().current_position,
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        ),
        candidate_continuations=(replace(_context().candidate_continuations[0], entry_uci="g8f6"),),
    )

    explanation = ConservativeCoachService().explain(context, level="intermediaire").text

    assert "Si les Noirs jouent [[move:uci=g8f6,label=...Nf6]]" in explanation


def test_conservative_coach_falls_back_without_source_attribution() -> None:
    explanation = ConservativeCoachService().explain(_context(sources=(SOURCE,)), level="debutant").text

    assert explanation == (
        "Je n'ai pas assez de contexte source pour formuler une explication fiable. "
        "Je peux seulement signaler la ligne identifiée : Ruy Lopez."
    )


def test_conservative_coach_rejects_child_passage_in_current_bucket() -> None:
    bad_context = CoachContext(
        current_position=_context().current_position,
        current_prose=(
            CoachProsePassage(
                text="Child prose misplaced.",
                relation_to_position="parent",
                source_chunk_id="chunk-ruy",
            ),
        ),
        source_attributions=(SOURCE,),
    )

    with pytest.raises(ValueError, match="current_prose can contain only current passages"):
        ConservativeCoachService().explain(bad_context, level="avance")


def test_llm_coach_returns_synthesized_prose_with_citations() -> None:
    response = "Explication synthetisee. [source: Plans, CC BY-SA 4.0]"
    service = LlmCoachService(provider=FakeLLMProvider(response=response))

    explanation = service.explain(_context(), level="intermediaire").text

    assert explanation == response


def test_llm_coach_preserves_display_formatting() -> None:
    response = "## Plan simple\n\n**e5** controle le centre.\n\n- Developper une piece\n- Roquer rapidement"
    service = LlmCoachService(provider=FakeLLMProvider(response=response))

    explanation = service.explain(_context(), level="debutant").text

    assert explanation == "## Plan simple\n\n**e5** controle le centre.\n\n- Developper une piece\n\n- Roquer rapidement"


def test_llm_coach_adds_interactive_references_when_model_omits_dsl() -> None:
    context = replace(
        _context(),
        current_position=replace(
            _context().current_position,
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        ),
        recommended_moves=[
            {"san": "e5", "uci": "e7e5"},
        ],
    )
    response = "La case **e5** est importante. Le coup **e5** est naturel. Exemple **e5 puis Nf3**."

    explanation = LlmCoachService(provider=FakeLLMProvider(response=response)).explain(
        context,
        level="debutant",
    ).text

    assert "[[square:sq=e5,label=e5]]" in explanation
    assert "[[move:uci=e7e5,label=e5]]" in explanation
    assert "[[line:moves=e7e5,g1f3,label=e5 puis Nf3]]" in explanation


def test_llm_coach_annotates_all_allowed_uci_and_san_move_mentions() -> None:
    context = replace(
        _context(),
        current_position=replace(
            _context().current_position,
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        ),
        recommended_moves=[
            {"san": "d5", "uci": "d7d5"},
            {"san": "e6", "uci": "e7e6"},
            {"san": "Nc6", "uci": "b8c6"},
            {"san": "Nf6", "uci": "g8f6"},
        ],
    )
    response = "Regardez d7d5, e7e6, b8c6 ou Nf6. Suite d7d5 puis g1f3. Le coup e1e5 reste indisponible."

    explanation = LlmCoachService(provider=FakeLLMProvider(response=response)).explain(
        context,
        level="debutant",
    ).text

    for uci, san in (("d7d5", "d5"), ("e7e6", "e6"), ("b8c6", "Nc6"), ("g8f6", "Nf6")):
        assert f"[[move:uci={uci},label={san}]]" in explanation
    assert "[[line:moves=d7d5,g1f3,label=d5 puis Nf3]]" in explanation
    assert "[[move:uci=e1e5" not in explanation
    assert "e1e5" in explanation


def test_llm_coach_annotates_numbered_san_mentions_every_time() -> None:
    context = replace(
        _context(),
        current_position=replace(
            _context().current_position,
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        ),
        recommended_moves=[
            {"san": "e5", "uci": "e7e5"},
            {"san": "Nf6", "uci": "g8f6"},
        ],
    )
    response = "Regardez 2. e5, 2.e5 ou 2...Nf6."

    explanation = LlmCoachService(provider=FakeLLMProvider(response=response)).explain(
        context,
        level="debutant",
    ).text

    assert explanation.count("[[move:uci=e7e5,label=e5]]") == 2
    assert explanation.count("[[move:uci=g8f6,label=Nf6]]") == 1


def test_llm_coach_distinguishes_square_mentions_from_move_mentions() -> None:
    context = replace(
        _context(),
        current_position=replace(
            _context().current_position,
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        ),
        recommended_moves=[
            {"san": "d5", "uci": "d7d5"},
            {"san": "e5", "uci": "e7e5"},
        ],
    )
    response = (
        "Apres 1. e4, les Blancs preparent une attaque sur e5 ou d5. "
        "Les Noirs doivent controler le centre (cases e5, d5). "
        "La case centrale e5 est cruciale. Elle permet de capturer le pion e4. "
        "Le coup e5 est naturel."
    )

    explanation = LlmCoachService(provider=FakeLLMProvider(response=response)).explain(
        context,
        level="debutant",
    ).text

    assert explanation.count("[[square:sq=e5,label=e5]]") == 3
    assert explanation.count("[[square:sq=d5,label=d5]]") == 2
    assert "[[square:sq=e4,label=e4]]" in explanation
    assert explanation.count("[[move:uci=e7e5,label=e5]]") == 1


def test_llm_coach_prompt_includes_recommended_moves_and_structure() -> None:
    provider = FakeLLMProvider(response="Explication. [source: Plans, CC BY-SA 4.0]")
    service = LlmCoachService(provider=provider)
    context = replace(
        _context(),
        question="Pourquoi jouer Nf3 ici ?",
        recommended_moves=[
            {
                "san": "e5",
                "uci": "e7e5",
                "move_share": 0.6,
                "games": 60,
            }
        ],
    )

    service.explain(context, level="intermediaire")

    prompt = provider.prompts[0]
    system = provider.systems[0]
    assert "| e5 | e7e5 |" in prompt
    assert "Question de l'utilisateur :" in prompt
    assert "Pourquoi jouer Nf3 ici ?" in prompt
    assert prompt.startswith("QUESTION DE L'UTILISATEUR A TRAITER EN PRIORITE :\nPourquoi jouer Nf3 ici ?")
    assert prompt.endswith("Rappel prioritaire : repondez d'abord a la question de l'utilisateur :\nPourquoi jouer Nf3 ici ?")
    assert "repondez-y en priorite" in system
    assert "Plan simple" in system
    assert "Idee principale" in system
    assert "Coups a regarder" in system
    assert "Conclusion :" in system
    assert "strictement en francais" in system
    assert "Consignes finales obligatoires" in prompt
    assert "[[move:uci=e7e5,label=e5]]" in prompt
    assert "entre 100 et 220 mots" in prompt
    assert "chaque coup en une courte phrase" in prompt
    assert "label SAN exact" in prompt
    assert prompt.rfind("Consignes finales obligatoires") > prompt.rfind("e5 (e7e5)")


def test_llm_coach_bounds_long_source_passages_before_prompting() -> None:
    long_context = replace(
        _context(),
        current_prose=(
            replace(_context().current_prose[0], text="source " * 1000),
        ),
    )
    provider = FakeLLMProvider(response="Explication.")

    LlmCoachService(provider=provider).explain(long_context, level="debutant")

    prompt = provider.prompts[0]
    assert "[...] (reference: Plans)" in prompt
    assert len(prompt) < 16000


def test_llm_coach_stream_uses_lichess_as_source_when_rag_is_empty() -> None:
    response = "Les statistiques indiquent le coup e5."
    provider = FakeLLMProvider(response=response)
    service = LlmCoachService(provider=provider)
    context = replace(
        _context(),
        current_prose=(),
        candidate_continuations=(),
        source_attributions=(),
        lichess_stats={"games": 100, "white": 0.5, "draws": 0.1, "black": 0.4},
        recommended_moves=[{"san": "e5", "uci": "e7e5", "move_share": 0.6, "games": 60}],
    )

    explanation = "".join(service.stream_explain(context, level="debutant"))

    assert explanation == response
    assert "Statistiques Lichess" in provider.prompts[0]
    assert "[source:" not in provider.systems[0]


def test_llm_coach_accepts_response_without_citation() -> None:
    response = "Explication sans citation."
    service = LlmCoachService(provider=FakeLLMProvider(response=response))

    explanation = service.explain(_context(), level="intermediaire").text

    assert explanation == response


def test_llm_coach_sanitizes_references_against_current_position() -> None:
    context = replace(
        _context(),
        current_position=replace(
            _context().current_position,
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        ),
        recommended_moves=[{"san": "e5", "uci": "e7e5"}],
    )
    response = (
        "[[move:uci=e7e5,label=e5]] [[square:sq=e5,label=e5]] "
        "[[move:uci=e2e4,label=e4]]"
    )

    explanation = LlmCoachService(provider=FakeLLMProvider(response=response)).explain(
        context,
        level="debutant",
    ).text

    assert "[[move:uci=e7e5,label=e5]]" in explanation
    assert "[[square:sq=e5,label=e5]]" in explanation
    assert "[[move:uci=e2e4" not in explanation
    assert "e4" in explanation


def test_llm_coach_falls_back_on_provider_error() -> None:
    service = LlmCoachService(provider=FakeLLMProvider(responses=[LLMProviderError("boom")]))

    result = service.explain(_context(), level="intermediaire")

    assert result.fallback == "llm_coach_unavailable"
    assert "Ruy Lopez" in result.text


def test_llm_coach_falls_back_with_empty_label() -> None:
    service = LlmCoachService(provider=FakeLLMProvider(responses=[LLMProviderEmptyError("empty")]))

    result = service.explain(_context(), level="intermediaire")

    assert result.fallback == "llm_coach_empty"


def test_llm_coach_falls_back_with_timeout_label() -> None:
    service = LlmCoachService(provider=FakeLLMProvider(responses=[LLMProviderTimeoutError("timeout")]))

    result = service.explain(_context(), level="intermediaire")

    assert result.fallback == "llm_coach_timeout"


def test_llm_coach_falls_back_when_response_too_long() -> None:
    service = LlmCoachService(provider=FakeLLMProvider(response="x" * 2001), max_length=2000)

    result = service.explain(_context(), level="intermediaire")

    assert result.fallback == "llm_coach_too_long"


def test_llm_coach_accepts_response_within_streaming_budget() -> None:
    response = "x" * 3400
    service = LlmCoachService(provider=FakeLLMProvider(response=response))

    explanation = service.explain(_context(), level="intermediaire").text

    assert explanation == response


def test_prepare_coach_output_with_missing_fen_has_no_interactive_markers() -> None:
    context = replace(
        _context(),
        current_position=replace(_context().current_position, fen=None),
        recommended_moves=[{"san": "e5", "uci": "e7e5"}],
    )

    result = prepare_coach_output("[[move:uci=e7e5,label=e5]] e5", context)

    assert "[[" not in result.text


def test_prepare_coach_output_is_idempotent() -> None:
    context = replace(
        _context(),
        current_position=replace(
            _context().current_position,
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        ),
        recommended_moves=[{"san": "e5", "uci": "e7e5"}],
    )

    once = prepare_coach_output("Le coup e5 est naturel.", context).text

    assert prepare_coach_output(once, context).text == once


def test_prepare_coach_output_keeps_a_three_move_line_together() -> None:
    context = replace(
        _context(),
        current_position=replace(
            _context().current_position,
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        ),
        recommended_moves=[{"san": "e5", "uci": "e7e5"}],
    )

    result = prepare_coach_output("Suite e5 puis Nf3 puis Nc6.", context).text

    assert result.count("[[line:") == 1
    assert "e7e5,g1f3,b8c6" in result
