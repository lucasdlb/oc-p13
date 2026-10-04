"""Typed intent routing for retrieval planning.

The router classifies a user question; it does not build retrieval filters,
query Milvus, or generate coach prose. JEV/System-One can be added behind the
``IntentClassifier`` seam later, while the conservative local fallback keeps the
demo usable offline.
"""

import logging
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal, Protocol

import httpx

from backend.app.core.settings import TypeSafeSettings


logger = logging.getLogger("backend.intent_router")


RetrievalIntent = Literal[
    "explain_current_position",
    "ask_next_moves",
    "ask_specific_candidate",
    "evaluate_move_quality",
    "ask_trap",
    "ask_mistake",
    "ask_history",
    "ask_unsupported",
    "ask_out_of_theory",
    "general_principle",
    "unclear",
]

RouterSource = Literal[
    "rule_fallback",
    "jev",
    "fallback_after_provider_error",
    "fallback_after_low_confidence",
    "fallback_after_invalid_response",
]

_INTENTS: tuple[RetrievalIntent, ...] = (
    "explain_current_position",
    "ask_next_moves",
    "ask_specific_candidate",
    "evaluate_move_quality",
    "ask_trap",
    "ask_mistake",
    "ask_history",
    "ask_unsupported",
    "ask_out_of_theory",
    "general_principle",
    "unclear",
)


class IntentRouterError(RuntimeError):
    """Raised when a router provider fails or returns unusable output."""


@dataclass(frozen=True)
class CandidateMove:
    san: str
    uci: str | None = None
    opening_name: str | None = None
    eco_code: str | None = None
    opening_node_id: str | None = None


@dataclass(frozen=True)
class IntentRouterContext:
    question: str | None
    level: str
    moves: tuple[str, ...] = ()
    fen: str | None = None
    current_opening_name: str | None = None
    current_eco: str | None = None
    current_node_id: str | None = None
    legal_child_moves: tuple[CandidateMove, ...] = ()


@dataclass(frozen=True)
class IntentDecision:
    intent: RetrievalIntent
    confidence: float
    probabilities: Mapping[RetrievalIntent, float]
    matched_candidate_move: CandidateMove | None = None
    reason_codes: tuple[str, ...] = ()
    source: RouterSource = "rule_fallback"
    provider_model: str | None = None


class IntentClassifier(Protocol):
    def classify(self, context: IntentRouterContext) -> IntentDecision: ...


class IntentRouter:
    def __init__(
        self,
        *,
        fallback: IntentClassifier | None = None,
        primary: IntentClassifier | None = None,
        medium_confidence: float = 0.5,
    ) -> None:
        self._fallback = fallback or RuleBasedIntentClassifier()
        self._primary = primary
        self._medium_confidence = medium_confidence

    def classify(self, context: IntentRouterContext) -> IntentDecision:
        if self._primary is None:
            return self._fallback.classify(context)

        try:
            decision = self._primary.classify(context)
            _validate_decision(decision)
        except IntentRouterError:
            return _with_source(
                self._fallback.classify(context),
                "fallback_after_provider_error",
                "primary_provider_error",
            )
        except (TypeError, ValueError):
            return _with_source(
                self._fallback.classify(context),
                "fallback_after_invalid_response",
                "primary_invalid_response",
            )

        if decision.confidence < self._medium_confidence:
            return _with_source(
                self._fallback.classify(context),
                "fallback_after_low_confidence",
                "primary_low_confidence",
            )
        return decision


class RuleBasedIntentClassifier:
    def classify(self, context: IntentRouterContext) -> IntentDecision:
        question = _normalize(context.question)
        if not question:
            return _decision("unclear", 0.4, reason_codes=("empty_question",))

        matched = _matched_candidate(question, context.legal_child_moves)
        if matched is not None:
            return _decision(
                "ask_specific_candidate",
                0.78,
                matched_candidate_move=matched,
                reason_codes=("matched_candidate_move",),
            )

        if _asks_about_specific_candidate(question):
            return _decision("ask_specific_candidate", 0.66, reason_codes=("specific_candidate_phrase",))

        if _contains_any(
            question,
            ("histoire", "historique", "origine", "vient d ou", "vient d'ou", "d ou vient", "d'ou vient"),
        ):
            return _decision("ask_history", 0.8, reason_codes=("history_phrase",))

        if _contains_any(question, ("piege", "piège")):
            return _decision("ask_trap", 0.82, reason_codes=("trap_phrase",))

        if _contains_any(
            question,
            (
                "comment s appelle cette ouverture",
                "comment s'appelle cette ouverture",
                "gambit hobbs",
            ),
        ):
            return _decision("ask_unsupported", 0.78, reason_codes=("unsupported_opening_phrase",))

        if _contains_any(question, ("erreurs classiques", "mauvais coup a eviter", "mauvais coup à éviter")):
            return _decision("ask_mistake", 0.8, reason_codes=("mistake_phrase",))

        if _asks_about_concrete_move_quality(question):
            return _decision("ask_out_of_theory", 0.74, reason_codes=("concrete_move_quality_phrase",))

        if _contains_any(
            question,
            (
                "erreur",
                "gaffe",
                "blunder",
                "mauvais coup",
                "bon coup",
                "qualite du coup",
                "qualité du coup",
                "evaluer ce coup",
                "évaluer ce coup",
                "est ce correct",
            ),
        ):
            return _decision("evaluate_move_quality", 0.78, reason_codes=("move_quality_phrase",))

        if _contains_any(
            question,
            (
                "que jouer",
                "quoi jouer",
                "je fais quoi",
                "quel coup",
                "prochain coup",
                "coups suivants",
                "peuvent jouer",
                "peut faire mon adversaire",
                "dois je faire",
                "continuer",
                "suite",
                "coup candidat",
            ),
        ):
            return _decision("ask_next_moves", 0.74, reason_codes=("next_move_phrase",))

        if _contains_any(
            question,
            (
                "principe",
                "idee generale",
                "idée générale",
                "concept",
                "regle generale",
                "règle générale",
                "comment jouer contre",
                "debutant",
                "débutant",
            ),
        ):
            return _decision("general_principle", 0.68, reason_codes=("general_principle_phrase",))

        if _contains_any(question, ("pourquoi", "plan", "idee", "idée", "explique", "comprendre")):
            return _decision("explain_current_position", 0.68, reason_codes=("current_explanation_phrase",))

        return _decision("explain_current_position", 0.55, reason_codes=("conservative_default",))


class JevIntentClassifier:
    """Optional TypeSafe/JEV classifier behind the ``IntentClassifier`` seam."""

    def __init__(
        self,
        *,
        settings: TypeSafeSettings | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings or TypeSafeSettings()
        self._client = client or httpx.Client(timeout=self._settings.timeout_seconds)

    def classify(self, context: IntentRouterContext) -> IntentDecision:
        if not self._settings.enabled:
            raise IntentRouterError("JEV intent classifier is disabled")
        if not self._settings.api_key:
            raise IntentRouterError("TYPESAFE_API_KEY is required when JEV is enabled")

        try:
            response = self._client.post(
                _join_url(self._settings.base_url, "/v1/choice"),
                headers={"Authorization": f"Bearer {self._settings.api_key}"},
                json=_jev_payload(context, self._settings.model),
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise IntentRouterError("JEV provider request failed") from exc
        except ValueError as exc:
            raise ValueError("JEV provider returned non-JSON response") from exc

        decision = _decision_from_jev_payload(payload, default_model=self._settings.model)
        logger.info(
            "JEV intent classified",
            extra={
                "intent": decision.intent,
                "confidence": decision.confidence,
                "provider_model": decision.provider_model,
            },
        )
        return decision


def _decision(
    intent: RetrievalIntent,
    confidence: float,
    *,
    matched_candidate_move: CandidateMove | None = None,
    reason_codes: tuple[str, ...] = (),
    source: RouterSource = "rule_fallback",
    provider_model: str | None = None,
) -> IntentDecision:
    return IntentDecision(
        intent=intent,
        confidence=confidence,
        probabilities=_probabilities(intent, confidence),
        matched_candidate_move=matched_candidate_move,
        reason_codes=reason_codes,
        source=source,
        provider_model=provider_model,
    )


def _probabilities(intent: RetrievalIntent, confidence: float) -> dict[RetrievalIntent, float]:
    bounded = max(0.0, min(1.0, confidence))
    if len(_INTENTS) == 1:
        return {intent: 1.0}
    rest = (1.0 - bounded) / (len(_INTENTS) - 1)
    return {candidate: bounded if candidate == intent else rest for candidate in _INTENTS}


def _jev_payload(context: IntentRouterContext, model: str) -> dict:
    return {
        "model": model,
        "question": "Classify the user's retrieval intent. Return exactly one choice.",
        "choices": list(_INTENTS),
        "context": {
            "user_question": context.question,
            "level": context.level,
            "moves": list(context.moves),
            "fen": context.fen,
            "current_opening_name": context.current_opening_name,
            "current_eco": context.current_eco,
            "current_node_id": context.current_node_id,
            "legal_child_moves": [_candidate_move_payload(move) for move in context.legal_child_moves],
        },
    }


def _candidate_move_payload(move: CandidateMove) -> dict:
    return {
        "san": move.san,
        "uci": move.uci,
        "opening_name": move.opening_name,
        "eco_code": move.eco_code,
        "opening_node_id": move.opening_node_id,
    }


def _decision_from_jev_payload(payload: object, *, default_model: str) -> IntentDecision:
    if not isinstance(payload, Mapping):
        raise ValueError("JEV response must be an object")

    choice = payload.get("choice")
    confidence = payload.get("confidence")
    if choice not in _INTENTS:
        raise ValueError(f"unknown JEV retrieval intent {choice!r}")
    if not isinstance(confidence, int | float) or not 0.0 <= float(confidence) <= 1.0:
        raise ValueError("JEV confidence must be between 0 and 1")

    reason_codes = payload.get("reason_codes", ())
    if reason_codes is None:
        reason_codes = ()
    if not isinstance(reason_codes, Sequence) or isinstance(reason_codes, str):
        raise ValueError("JEV reason_codes must be a list")
    if not all(isinstance(reason, str) for reason in reason_codes):
        raise ValueError("JEV reason_codes must contain strings")

    model = payload.get("model", default_model)
    if model is not None and not isinstance(model, str):
        raise ValueError("JEV model must be a string")

    return _decision(
        choice,
        float(confidence),
        reason_codes=tuple(reason_codes),
        source="jev",
        provider_model=model,
    )


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _validate_decision(decision: IntentDecision) -> None:
    if decision.intent not in _INTENTS:
        raise ValueError(f"unknown retrieval intent {decision.intent!r}")
    if not 0.0 <= decision.confidence <= 1.0:
        raise ValueError("intent confidence must be between 0 and 1")


def _with_source(decision: IntentDecision, source: RouterSource, reason: str) -> IntentDecision:
    return replace(decision, source=source, reason_codes=(*decision.reason_codes, reason))


def _matched_candidate(question: str, candidates: Sequence[CandidateMove]) -> CandidateMove | None:
    for candidate in candidates:
        terms = [candidate.san, candidate.uci, candidate.opening_name, *_opening_name_aliases(candidate.opening_name)]
        for term in terms:
            if term and _term_in_question(_normalize(term), question):
                return candidate
    return None


def _opening_name_aliases(name: str | None) -> tuple[str, ...]:
    if not name:
        return ()
    aliases: list[str] = []
    for separator in (":", ","):
        if separator in name:
            aliases.append(name.rsplit(separator, 1)[1].strip())
    return tuple(alias for alias in aliases if alias)


def _term_in_question(term: str, question: str) -> bool:
    if not term:
        return False
    if re.fullmatch(r"[a-h][1-8][a-h][1-8][qrbn]?", term):
        return term in question
    return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", question))


def _contains_any(value: str, needles: Sequence[str]) -> bool:
    normalized_needles = (_normalize(needle) for needle in needles)
    return any(needle in value for needle in normalized_needles)


def _asks_about_concrete_move_quality(question: str) -> bool:
    return bool(
        _contains_concrete_move(question)
        and _contains_any(question, ("bon coup", "correct", "erreur"))
    )


def _asks_about_specific_candidate(question: str) -> bool:
    return bool(
        _contains_concrete_move(question)
        and _contains_any(question, ("si", "joue", "avec", "prendre"))
    )


def _contains_concrete_move(question: str) -> bool:
    return bool(re.search(r"\b\d+\s*\.?\s*(?:[a-z]|[nbrqk])[a-z0-9=+#-]*", question))


def _normalize(value: str | None) -> str:
    text = (value or "").casefold().replace("...", " ")
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", ascii_text).strip()
