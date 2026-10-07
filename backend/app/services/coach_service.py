"""Coach service seam and concrete renderers."""

from collections.abc import Iterator
from dataclasses import dataclass
import logging
from typing import Protocol, runtime_checkable

from backend.app.services.coach_fallback import fallback_explanation, fallback_label
from backend.app.services.coach_prompt import build_prompt, system_prompt
from backend.app.services.coach_references import MoveIndex, annotate_references, sanitize_coach_references
from backend.app.services.coach_validation import validate_coach_output
from backend.app.services.llm import LLMProvider, LLMProviderError
from backend.app.services.retrieval_contracts import CoachContext, CoachProsePassage, CoachSourceAttribution


MAX_LLM_COACH_CHARS = 4000
logger = logging.getLogger("backend.coach")


@dataclass(frozen=True)
class CoachResult:
    text: str
    fallback: str | None = None


@runtime_checkable
class CoachService(Protocol):
    def explain(self, context: CoachContext, *, level: str) -> CoachResult:
        """Return grounded coach prose and optional fallback metadata."""


class CoachFallbackError(Exception):
    """Legacy streaming-only fallback signal kept for custom stream producers."""

    def __init__(self, text: str, fallback_label: str) -> None:
        self.text = text
        self.fallback_label = fallback_label
        super().__init__(fallback_label)


class ConservativeCoachService:
    def explain(self, context: CoachContext, *, level: str) -> CoachResult:
        _validate_context_shape(context)
        sources = _source_map(context.source_attributions)
        if not _all_passages_sourced(context, sources):
            return CoachResult(fallback_explanation(context), "llm_coach_source_metadata")

        heading = _position_heading(context, level)
        parts = [heading]
        if context.current_prose:
            parts.append("Dans la position actuelle, " + " ".join(_render_passage(p, sources) for p in context.current_prose))
        if context.supporting_prose:
            parts.append("Contexte complémentaire, " + " ".join(_render_passage(p, sources) for p in context.supporting_prose))
        for continuation in context.candidate_continuations:
            rendered = " ".join(_render_passage(p, sources) for p in continuation.prose)
            side = _side_to_move_label(context)
            entry = continuation.entry_move
            if continuation.entry_uci:
                label = f"...{continuation.entry_move}" if side == "Noirs" else continuation.entry_move
                entry = f"[[move:uci={continuation.entry_uci},label={label}]]"
            prefix = "" if continuation.entry_uci else "..."
            conditional = "Si le camp au trait joue" if side == "le camp au trait" else f"Si les {side} jouent"
            parts.append(f"{conditional} {prefix}{entry}, {rendered}")
        if len(parts) == 1:
            return CoachResult(fallback_explanation(context), "llm_coach_source_metadata")
        return CoachResult(prepare_coach_output("\n\n".join(parts), context).text)


class LlmCoachService:
    def __init__(self, provider: LLMProvider, fallback: CoachService | None = None, max_length: int = MAX_LLM_COACH_CHARS) -> None:
        self._provider = provider
        self._fallback = fallback or ConservativeCoachService()
        self._max_length = max_length

    def explain(self, context: CoachContext, *, level: str) -> CoachResult:
        _validate_context_shape(context)
        sources = _source_map(context.source_attributions)
        if not _all_passages_sourced(context, sources):
            return self._fallback_result(context, level, "llm_coach_source_metadata")
        try:
            text = self._provider.generate(build_prompt(context, level), system=system_prompt())
        except LLMProviderError as exc:
            label = fallback_label(exc)
            logger.warning("LLM coach fallback %s: %s", label, exc)
            return self._fallback_result(context, level, label)
        validated, reason = validate_coach_output(text, self._max_length)
        if validated is None:
            return self._fallback_result(context, level, reason or "llm_coach_invalid_output")
        return prepare_coach_output(validated, context)

    def stream_explain(self, context: CoachContext, *, level: str) -> Iterator[str]:
        _validate_context_shape(context)
        sources = _source_map(context.source_attributions)
        if not _all_passages_sourced(context, sources):
            result = self._fallback_result(context, level, "llm_coach_source_metadata")
            raise CoachFallbackError(result.text, "llm_coach_source_metadata")
        chunks: list[str] = []
        try:
            for chunk in self._provider.generate_stream(build_prompt(context, level), system=system_prompt()):
                chunks.append(chunk)
                yield chunk
        except LLMProviderError as exc:
            label = fallback_label(exc)
            logger.warning("LLM coach fallback %s: %s", label, exc)
            result = self._fallback_result(context, level, label)
            raise CoachFallbackError(result.text, label) from exc
        combined = "".join(chunks)
        validated, reason = validate_coach_output(combined, self._max_length)
        if validated is None:
            result = self._fallback_result(context, level, reason or "llm_coach_invalid_output")
            raise CoachFallbackError(result.text, reason or "llm_coach_invalid_output")

    def _fallback_result(self, context: CoachContext, level: str, label: str) -> CoachResult:
        result = self._fallback.explain(context, level=level)
        return CoachResult(prepare_coach_output(result.text, context).text, label)


def prepare_coach_output(text: str, context: CoachContext) -> CoachResult:
    index = MoveIndex.from_context(context)
    allowed_moves = {record.uci for record in index.records}
    sanitized = sanitize_coach_references(text, fen=context.current_position.fen, allowed_moves=allowed_moves)
    if index.board is None:
        return CoachResult(sanitized)
    enriched = annotate_references(sanitized, index)
    if "[[" in enriched:
        return CoachResult(enriched)
    fallback = _interactive_reference_fallback(index)
    return CoachResult(f"{enriched}\n\n{fallback}" if fallback else enriched)


def sanitize_coach_output(text: str, context: CoachContext) -> str:
    index = MoveIndex.from_context(context)
    return sanitize_coach_references(text, fen=context.current_position.fen, allowed_moves={record.uci for record in index.records})


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
    passages = [*context.current_prose, *context.supporting_prose]
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
    return f"Explication niveau {level}: position hors théorie connue."


def _render_passage(passage: CoachProsePassage, sources: dict[str, CoachSourceAttribution]) -> str:
    source = sources[passage.source_chunk_id]
    label = source.section_title or source.canonical_title
    return f"{' '.join(passage.text.split())} [source: {label}, {source.license_or_terms}]"


def _side_to_move_label(context: CoachContext) -> str:
    index = MoveIndex.from_context(context)
    if index.board is None:
        return "le camp au trait"
    return "Blancs" if index.board.turn else "Noirs"


def _interactive_reference_fallback(index: MoveIndex) -> str:
    if not index.records:
        return ""
    first = index.records[0]
    destination = first.uci[2:4]
    return (
        "Références interactives :\n"
        f"- Coup : [[move:uci={first.uci},label={first.san}]]\n"
        f"- Case cible : [[square:sq={destination},label={destination}]]"
    )
