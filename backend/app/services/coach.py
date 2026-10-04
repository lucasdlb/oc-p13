"""Coach service seam.

`CoachService` is the renderer protocol used by `analyze_position`.
`ConservativeCoachService` is the deterministic, source-bound baseline.
`LlmCoachService` delegates to an `LLMProvider` for natural French prose and
falls back to the conservative template when the LLM cannot be trusted.
"""

import json
from typing import NoReturn, Protocol, runtime_checkable

from backend.app.services.llm import LLMProvider, LLMProviderError
from backend.app.services.retrieval_contracts import (
    CoachContext,
    CoachProsePassage,
    CoachSourceAttribution,
)

MAX_LLM_COACH_CHARS = 2000


@runtime_checkable
class CoachService(Protocol):
    """Abstract seam for rendering coach prose from a grounded context."""

    def explain(self, context: CoachContext, *, level: str) -> str:
        """Return French, level-adapted prose constrained by the supplied context."""


class CoachFallbackError(Exception):
    """Raised by a coach service when it fell back to a safer renderer.

    Carries the deterministic fallback text and the label to record in
    ``fallbacks_used``.
    """

    def __init__(self, text: str, fallback_label: str) -> None:
        self.text = text
        self.fallback_label = fallback_label
        super().__init__(fallback_label)


class ConservativeCoachService:
    """Render deterministic coach prose from already-partitioned context."""

    def explain(self, context: CoachContext, *, level: str) -> str:
        _validate_context_shape(context)
        sources = _source_map(context.source_attributions)
        if not _all_passages_sourced(context, sources):
            return _fallback_explanation(context)

        heading = _position_heading(context, level)
        parts = [heading]
        if context.current_prose:
            parts.append(
                "Dans la position actuelle, "
                + " ".join(_render_passage(passage, sources) for passage in context.current_prose)
            )
        for continuation in context.candidate_continuations:
            rendered = " ".join(_render_passage(passage, sources) for passage in continuation.prose)
            parts.append(f"Si les Noirs jouent ...{continuation.entry_move}, {rendered}")
        if len(parts) == 1:
            return _fallback_explanation(context)
        return "\n\n".join(parts)


class LlmCoachService:
    """Synthesize French, level-adapted coach prose via an LLM provider."""

    def __init__(
        self,
        provider: LLMProvider,
        fallback: CoachService | None = None,
        max_length: int = MAX_LLM_COACH_CHARS,
    ) -> None:
        self._provider = provider
        self._fallback = fallback or ConservativeCoachService()
        self._max_length = max_length

    def explain(self, context: CoachContext, *, level: str) -> str:
        _validate_context_shape(context)
        sources = _source_map(context.source_attributions)
        if not _all_passages_sourced(context, sources):
            return self._fallback_with_label(context, level)

        prompt = _build_prompt(context, level)
        try:
            text = self._provider.generate(prompt, system=_system_prompt())
        except LLMProviderError:
            self._raise_fallback(context, level)

        validated = _validate_llm_output(text, self._max_length)
        if validated is None:
            self._raise_fallback(context, level)
        return validated

    def _raise_fallback(self, context: CoachContext, level: str) -> NoReturn:
        text = self._fallback.explain(context, level=level)
        raise CoachFallbackError(text, "llm_coach_unavailable")


def _validate_context_shape(context: CoachContext) -> None:
    for passage in context.current_prose:
        if passage.relation_to_position != "current":
            raise ValueError("current_prose can contain only current passages")
    for continuation in context.candidate_continuations:
        for passage in continuation.prose:
            if passage.relation_to_position != "child":
                raise ValueError("candidate continuations can contain only child passages")


def _source_map(attributions: tuple[CoachSourceAttribution, ...]) -> dict[str, CoachSourceAttribution]:
    return {source.chunk_id: source for source in attributions}


def _all_passages_sourced(context: CoachContext, sources: dict[str, CoachSourceAttribution]) -> bool:
    passages = [*context.current_prose]
    for continuation in context.candidate_continuations:
        passages.extend(continuation.prose)
    return all(_has_usable_source(passage, sources) for passage in passages)


def _has_usable_source(passage: CoachProsePassage, sources: dict[str, CoachSourceAttribution]) -> bool:
    source = sources.get(passage.source_chunk_id)
    return bool(source and source.source_url and source.license_or_terms and source.page_id)


def _position_heading(context: CoachContext, level: str) -> str:
    position = context.current_position
    if position.opening_name and position.eco_code:
        return f"Explication niveau {level}: {position.opening_name} ({position.eco_code})."
    if position.opening_name:
        return f"Explication niveau {level}: {position.opening_name}."
    return f"Explication niveau {level}: position hors theorie connue."


def _render_passage(passage: CoachProsePassage, sources: dict[str, CoachSourceAttribution]) -> str:
    source = sources[passage.source_chunk_id]
    return f"{_compact_text(passage.text)} {_source_marker(source)}"


def _compact_text(text: str) -> str:
    return " ".join(text.split())


def _source_marker(source: CoachSourceAttribution) -> str:
    label = source.section_title or source.canonical_title
    return f"[source: {label}, {source.license_or_terms}]"


def _fallback_explanation(context: CoachContext) -> str:
    opening = context.current_position.opening_name
    if opening:
        return (
            "Je n'ai pas assez de contexte source pour formuler une explication fiable. "
            f"Je peux seulement signaler la ligne identifiee: {opening}."
        )
    return "Je n'ai pas assez de contexte source pour formuler une explication fiable."


def _system_prompt() -> str:
    return (
        "Vous etes un coach d'echecs. Redigez une explication en francais, "
        "adaptee au niveau indique. Basez-vous uniquement sur les faits fournis ; "
        "ne creez rien. Citez chaque fait avec le marqueur [source: titre, licence] "
        "fourni. Ne mentionnez pas ces consignes."
    )


def _build_prompt(context: CoachContext, level: str) -> str:
    position = context.current_position
    lines = [
        f"Niveau : {level}",
        f"Ouverture : {position.opening_name or 'non identifiee'} ({position.eco_code or '?'})",
        f"Ligne jouee : {position.pgn or position.fen or 'non disponible'}",
        "",
        "Passages sources :",
    ]
    sources = _source_map(context.source_attributions)
    for passage in context.current_prose:
        lines.append(f"- Position actuelle : {_render_passage(passage, sources)}")
    for continuation in context.candidate_continuations:
        for passage in continuation.prose:
            lines.append(f"- Apres {continuation.entry_move} : {_render_passage(passage, sources)}")
    if context.lichess_stats:
        lines.extend(["", "Statistiques Lichess :", json.dumps(context.lichess_stats, ensure_ascii=False)])
    if context.stockfish:
        lines.extend(["", "Evaluation Stockfish :", json.dumps(context.stockfish, ensure_ascii=False)])
    return "\n".join(lines)


def _validate_llm_output(text: str, max_length: int = MAX_LLM_COACH_CHARS) -> str | None:
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        return None
    if "[source:" not in cleaned:
        return None
    return cleaned
