"""Compatibility facade for the coach service modules."""

from backend.app.services.coach_service import (
    CoachFallbackError,
    CoachResult,
    CoachService,
    ConservativeCoachService,
    LlmCoachService,
    prepare_coach_output,
    sanitize_coach_output,
)

__all__ = [
    "CoachFallbackError",
    "CoachResult",
    "CoachService",
    "ConservativeCoachService",
    "LlmCoachService",
    "prepare_coach_output",
    "sanitize_coach_output",
]
