"""Validation and normalization of LLM coach output."""

import re


_THINK_BLOCK_PATTERN = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def validate_coach_output(text: str, max_length: int) -> tuple[str | None, str | None]:
    """Return cleaned text and an explicit failure reason, if any."""
    cleaned = _THINK_BLOCK_PATTERN.sub("", text.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if not cleaned:
        return None, "llm_coach_empty"
    if len(cleaned) > max_length:
        return None, "llm_coach_too_long"
    return cleaned, None
