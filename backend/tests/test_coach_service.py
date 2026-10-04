import pytest

from backend.app.services.coach import CoachFallbackError, ConservativeCoachService, LlmCoachService
from backend.app.services.llm import FakeLLMProvider, LLMProviderError
from backend.app.services.retrieval_contracts import (
    CoachCandidateContinuation,
    CoachContext,
    CoachPositionContext,
    CoachProsePassage,
    CoachSourceAttribution,
)


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
    explanation = ConservativeCoachService().explain(_context(), level="intermediaire")

    assert "Ruy Lopez (C60)" in explanation
    assert "Dans la position actuelle" in explanation
    assert "The Ruy Lopez increases pressure on e5" in explanation
    assert "Si les Noirs jouent ...Nf6" in explanation
    assert "The Berlin Defense begins" in explanation
    assert "[source: Plans, CC BY-SA 4.0]" in explanation
    assert "[source: Berlin defence, CC BY-SA 4.0]" in explanation


def test_conservative_coach_falls_back_without_source_attribution() -> None:
    explanation = ConservativeCoachService().explain(_context(sources=(SOURCE,)), level="debutant")

    assert explanation == (
        "Je n'ai pas assez de contexte source pour formuler une explication fiable. "
        "Je peux seulement signaler la ligne identifiee: Ruy Lopez."
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

    explanation = service.explain(_context(), level="intermediaire")

    assert explanation == response


def test_llm_coach_falls_back_when_citation_missing() -> None:
    service = LlmCoachService(provider=FakeLLMProvider(response="Pas de citation."))

    with pytest.raises(CoachFallbackError) as exc_info:
        service.explain(_context(), level="intermediaire")

    assert exc_info.value.fallback_label == "llm_coach_unavailable"
    assert "Ruy Lopez" in exc_info.value.text


def test_llm_coach_falls_back_on_provider_error() -> None:
    service = LlmCoachService(provider=FakeLLMProvider(responses=[LLMProviderError("boom")]))

    with pytest.raises(CoachFallbackError) as exc_info:
        service.explain(_context(), level="intermediaire")

    assert exc_info.value.fallback_label == "llm_coach_unavailable"
    assert "Ruy Lopez" in exc_info.value.text


def test_llm_coach_falls_back_when_response_too_long() -> None:
    service = LlmCoachService(provider=FakeLLMProvider(response="x" * 2001), max_length=2000)

    with pytest.raises(CoachFallbackError) as exc_info:
        service.explain(_context(), level="intermediaire")

    assert exc_info.value.fallback_label == "llm_coach_unavailable"
