"""Deterministic coach fallback rendering and diagnostic labels."""

from backend.app.services.llm import (
    LLMProviderEmptyError,
    LLMProviderError,
    LLMProviderLengthError,
    LLMProviderTimeoutError,
)
from backend.app.services.retrieval_contracts import CoachContext


_FALLBACK_LABELS = (
    (LLMProviderTimeoutError, "llm_coach_timeout"),
    (LLMProviderEmptyError, "llm_coach_empty"),
    (LLMProviderLengthError, "llm_coach_too_long"),
    (LLMProviderError, "llm_coach_unavailable"),
)


def fallback_label(exc: LLMProviderError) -> str:
    return next(label for cls, label in _FALLBACK_LABELS if isinstance(exc, cls))


def fallback_explanation(context: CoachContext) -> str:
    opening = context.current_position.opening_name
    if opening:
        return (
            "Je n'ai pas assez de contexte source pour formuler une explication fiable. "
            f"Je peux seulement signaler la ligne identifiée : {opening}."
        )
    return "Je n'ai pas assez de contexte source pour formuler une explication fiable."
