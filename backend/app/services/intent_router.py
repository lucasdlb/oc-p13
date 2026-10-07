"""Typed intent routing for retrieval planning.

The router classifies a user question; it does not build retrieval filters,
query Milvus, or generate coach prose. The primary classifier calls the
TypeSafe SystemOne API, while the conservative local fallback keeps the demo
usable offline.
"""

import logging
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal, Protocol, get_args

import chess
import httpx

from backend.app.core.settings import TypeSafeSettings
from backend.app.services.retrieval_contracts import RetrievalIntent


logger = logging.getLogger("backend.intent_router")


RouterSource = Literal[
    "rule_fallback",
    "jev",
    "fallback_after_provider_error",
    "fallback_after_low_confidence",
    "fallback_after_invalid_response",
]

_INTENTS: tuple[RetrievalIntent, ...] = get_args(RetrievalIntent)
_ROUTABLE_INTENTS: tuple[RetrievalIntent, ...] = tuple(
    intent for intent in _INTENTS if intent not in {"ask_unsupported", "ask_out_of_theory"}
)

_INTENT_DESCRIPTIONS: dict[RetrievalIntent, str] = {
    "explain_current_position": "Explain plans and ideas for the current chess position.",
    "ask_next_moves": "Ask what moves are available or what to play next.",
    "ask_specific_candidate": "Ask about a specific candidate move.",
    "evaluate_move_quality": "Evaluate whether a concrete move is good or bad.",
    "compare_moves": "Compare candidate moves by a named criterion such as best, safest, or most aggressive.",
    "ask_trap": "Ask about traps in the opening.",
    "ask_mistake": "Ask about common mistakes or errors.",
    "ask_history": "Ask about the history or origins of the opening.",
    "ask_unsupported": "Ask about an unsupported opening.",
    "ask_out_of_theory": "Ask about a concrete move that may be out of theory.",
    "general_principle": "Ask for a general chess principle.",
    "unclear": "The user's intent is unclear.",
}


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
    probabilities: Mapping[RetrievalIntent, float] | None
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
            decision = self._fallback.classify(context)
            _log_decision(decision, context)
            return decision

        try:
            decision = self._primary.classify(context)
            _validate_decision(decision)
        except IntentRouterError:
            logger.exception("Intent classifier provider failed")
            decision = _with_source(
                self._fallback.classify(context),
                "fallback_after_provider_error",
                "primary_provider_error",
            )
            _log_decision(decision, context)
            return decision
        except (TypeError, ValueError):
            logger.exception("Intent classifier returned an invalid response")
            decision = _with_source(
                self._fallback.classify(context),
                "fallback_after_invalid_response",
                "primary_invalid_response",
            )
            _log_decision(decision, context)
            return decision
        except Exception:
            logger.exception("Intent classifier crashed unexpectedly")
            decision = _with_source(
                self._fallback.classify(context),
                "fallback_after_provider_error",
                "primary_unexpected_error",
            )
            _log_decision(decision, context)
            return decision

        if decision.confidence < self._medium_confidence:
            decision = _with_source(
                self._fallback.classify(context),
                "fallback_after_low_confidence",
                "primary_low_confidence",
            )
            _log_decision(decision, context)
            return decision
        _log_decision(decision, context)
        return decision

    def close(self) -> None:
        close = getattr(self._primary, "close", None)
        if callable(close):
            close()


@dataclass(frozen=True)
class Rule:
    intent: RetrievalIntent
    pattern: re.Pattern[str]
    confidence: float
    code: str


def _rx(alts: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w)(?:{alts})(?!\w)")


_RULES: tuple[Rule, ...] = (
    Rule("ask_history", _rx(r"histoire|historique|origine|vient d ?ou|d ?ou vient"), 0.80, "history_phrase"),
    Rule("ask_trap", _rx(r"pieges?|trappes?|tactique cachee|combinaison cachee"), 0.82, "trap_phrase"),
    Rule("ask_mistake", _rx(r"erreurs? classiques?|gaffes?|mauvais coups? a eviter|pieges? a eviter"), 0.80, "mistake_phrase"),
    Rule(
        "compare_moves",
        _rx(r"le plus (?:agressif|solide|sur|fort|joue)|la plus (?:agressive|solide|sure|forte|jouee)|meilleurs?|plus agressif|plus solide|plus sur|plus fort"),
        0.78,
        "comparison_phrase",
    ),
    Rule("ask_next_moves", _rx(r"que jouer|quoi jouer|je fais quoi|quel coup|prochains? coups?|coups? suivants?|peuvent jouer|peut faire mon adversaire|dois je faire|continuer|suite|coups? candidats?"), 0.74, "next_move_phrase"),
    Rule("general_principle", _rx(r"principes?|idee generale|concepts?|regle generale|comment jouer contre|debutants?"), 0.68, "general_principle_phrase"),
    Rule("explain_current_position", _rx(r"pourquoi|plans?|idees?|explique|comprendre|position|variante|ouverture"), 0.68, "current_explanation_phrase"),
)


_QUALITY_PATTERN = _rx(r"bon coup|mauvais coup|correct|erreurs?|gaffes?|blunder|qualite du coup|evaluer ce coup|est ce correct")
_SPECIFIC_CANDIDATE_PATTERN = _rx(r"si|joue|avec|prendre|possible|repondre|apres")


class RuleBasedIntentClassifier:
    def classify(self, context: IntentRouterContext) -> IntentDecision:
        question = _normalize(context.question)
        if not question:
            return _decision("unclear", 0.4, reason_codes=("empty_question",))

        concrete_moves = _moves_in_question(question, context.fen)
        matched = _matched_candidate(question, context.legal_child_moves, concrete_moves)
        if matched is not None:
            if _asks_about_move_quality(question, has_concrete_move=True):
                return _decision(
                    "evaluate_move_quality",
                    0.80,
                    matched_candidate_move=matched,
                    reason_codes=("matched_candidate_move", "move_quality_phrase"),
                )
            return _decision(
                "ask_specific_candidate",
                0.78,
                matched_candidate_move=matched,
                reason_codes=("matched_candidate_move",),
            )

        has_concrete_move = bool(concrete_moves) or _contains_concrete_move_without_board(question)
        if _asks_about_move_quality(question, has_concrete_move=has_concrete_move):
            return _decision("evaluate_move_quality", 0.78, reason_codes=("move_quality_phrase",))

        compare_rule = next(rule for rule in _RULES if rule.intent == "compare_moves")
        if compare_rule.pattern.search(question):
            return _decision(compare_rule.intent, compare_rule.confidence, reason_codes=(compare_rule.code,))

        next_move_rule = next(rule for rule in _RULES if rule.intent == "ask_next_moves")
        if next_move_rule.pattern.search(question):
            return _decision(next_move_rule.intent, next_move_rule.confidence, reason_codes=(next_move_rule.code,))

        if _asks_about_specific_candidate(question, has_concrete_move=has_concrete_move):
            return _decision("ask_specific_candidate", 0.66, reason_codes=("specific_candidate_phrase",))

        for rule in _RULES:
            if rule.pattern.search(question):
                return _decision(rule.intent, rule.confidence, reason_codes=(rule.code,))

        return _decision("explain_current_position", 0.55, reason_codes=("conservative_default",))


class JevIntentClassifier:
    """TypeSafe SystemOne intent classifier behind the ``IntentClassifier`` seam.

    Sends a single ``choice`` question to the TypeSafe ``/v1/systemone`` endpoint
    and returns the chosen retrieval intent. Falls back to the rule-based
    classifier if the provider fails or the answer is invalid.
    """

    def __init__(
        self,
        *,
        settings: TypeSafeSettings | None = None,
        client: httpx.Client | None = None,
        allowed_intents: Sequence[RetrievalIntent] | None = None,
    ) -> None:
        self._settings = settings or TypeSafeSettings()
        self._client = client or httpx.Client(timeout=self._settings.timeout_seconds)
        self._allowed_intents = tuple(allowed_intents or _ROUTABLE_INTENTS)

    def classify(self, context: IntentRouterContext) -> IntentDecision:
        if not self._settings.enabled:
            raise IntentRouterError("JEV intent classifier is disabled")
        if not self._settings.api_key:
            raise IntentRouterError("TYPESAFE_API_KEY is required when JEV is enabled")

        try:
            response = self._client.post(
                _join_url(self._settings.base_url, "/v1/systemone"),
                headers={"Authorization": f"Bearer {self._settings.api_key.get_secret_value()}"},
                json=_systemone_payload(
                    context,
                    self._settings.model,
                    allowed_intents=self._allowed_intents,
                ),
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise IntentRouterError("TypeSafe provider request failed") from exc
        except ValueError as exc:
            raise ValueError("TypeSafe provider returned non-JSON response") from exc

        decision = _systemone_decision(
            payload,
            default_model=self._settings.model,
            allowed_intents=self._allowed_intents,
        )
        logger.info(
            "JEV intent classified",
            extra={
                "intent": decision.intent,
                "confidence": decision.confidence,
                "source": decision.source,
                "reason_codes": decision.reason_codes,
                "provider_model": decision.provider_model,
            },
        )
        return decision

    def close(self) -> None:
        self._client.close()


def _decision(
    intent: RetrievalIntent,
    confidence: float,
    *,
    matched_candidate_move: CandidateMove | None = None,
    reason_codes: tuple[str, ...] = (),
    source: RouterSource = "rule_fallback",
    provider_model: str | None = None,
    probabilities: Mapping[RetrievalIntent, float] | None = None,
) -> IntentDecision:
    return IntentDecision(
        intent=intent,
        confidence=confidence,
        probabilities=probabilities,
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


def _normalize_probabilities(
    probabilities: Mapping,
    chosen_intent: RetrievalIntent,
    chosen_confidence: float,
) -> dict[RetrievalIntent, float]:
    """Coerce the provider's probability map to a valid distribution over intents."""
    parsed: dict[RetrievalIntent, float] = {}
    for intent in _INTENTS:
        value = probabilities.get(intent)
        try:
            parsed[intent] = float(value) if isinstance(value, int | float) else 0.0
        except (TypeError, ValueError):
            parsed[intent] = 0.0
    total = sum(parsed.values())
    if total <= 0:
        return _probabilities(chosen_intent, chosen_confidence)
    return {intent: value / total for intent, value in parsed.items()}


def _systemone_payload(
    context: IntentRouterContext,
    model: str,
    *,
    allowed_intents: Sequence[RetrievalIntent] = _ROUTABLE_INTENTS,
) -> dict:
    return {
        "model": model,
        "state": {
            "user_question": context.question,
            "level": context.level,
            "moves": list(context.moves),
            "fen": context.fen,
            "current_opening_name": context.current_opening_name,
            "current_eco": context.current_eco,
            "current_node_id": context.current_node_id,
            "legal_child_moves": [_candidate_move_payload(move) for move in context.legal_child_moves],
        },
        "questions": {
            "intent": {
                "type": "choice",
                "instructions": "Classify the user's retrieval intent for a chess opening coach. Choose the option that best describes what the user wants.",
                "criteria": {intent: _INTENT_DESCRIPTIONS[intent] for intent in allowed_intents},
            }
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


def _systemone_decision(
    payload: object,
    *,
    default_model: str,
    allowed_intents: Sequence[RetrievalIntent] = _ROUTABLE_INTENTS,
) -> IntentDecision:
    if not isinstance(payload, Mapping):
        raise ValueError("TypeSafe response must be an object")

    model = payload.get("model", default_model)
    if model is not None and not isinstance(model, str):
        raise ValueError("TypeSafe model must be a string")

    answers = payload.get("answers")
    if not isinstance(answers, Mapping):
        raise ValueError("TypeSafe response must contain an answers object")

    answer = answers.get("intent")
    if not isinstance(answer, Mapping):
        raise ValueError("TypeSafe response must contain an answer named 'intent'")
    if answer.get("type") != "choice":
        raise ValueError("TypeSafe answer for 'intent' must be a choice")

    choice = answer.get("choice")
    if choice not in allowed_intents:
        raise ValueError(f"unknown TypeSafe retrieval intent {choice!r}")

    confidence = answer.get("confidence")
    if not isinstance(confidence, int | float) or not 0.0 <= float(confidence) <= 1.0:
        raise ValueError("TypeSafe confidence must be between 0 and 1")

    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, Mapping):
        raise ValueError("TypeSafe probabilities must be an object")

    return _decision(
        choice,
        float(confidence),
        probabilities=_normalize_probabilities(probabilities, choice, float(confidence)),
        reason_codes=("jev_choice",),
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


def _log_decision(decision: IntentDecision, context: IntentRouterContext) -> None:
    logger.info(
        "Intent classified",
        extra={
            "intent": decision.intent,
            "confidence": decision.confidence,
            "source": decision.source,
            "reason_codes": decision.reason_codes,
            "has_fen": bool(context.fen),
        },
    )


def _matched_candidate(
    question: str,
    candidates: Sequence[CandidateMove],
    concrete_moves: Sequence[chess.Move],
) -> CandidateMove | None:
    concrete_uci = {move.uci() for move in concrete_moves}
    for candidate in candidates:
        if candidate.uci and candidate.uci in concrete_uci:
            return candidate
        terms = [
            candidate.san,
            _san_to_french(candidate.san),
            candidate.uci,
            candidate.opening_name,
            *_opening_name_aliases(candidate.opening_name),
        ]
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


def _asks_about_move_quality(question: str, *, has_concrete_move: bool) -> bool:
    if _rx(r"est[- ]ce une erreur de jouer ca|ce coup est[- ]il|evaluer ce coup|qualite du coup").search(question):
        return True
    return has_concrete_move and bool(_QUALITY_PATTERN.search(question))


def _asks_about_specific_candidate(question: str, *, has_concrete_move: bool) -> bool:
    return has_concrete_move and bool(_SPECIFIC_CANDIDATE_PATTERN.search(question))


def _moves_in_question(question: str, fen: str | None) -> list[chess.Move]:
    if not fen:
        return []
    try:
        board = chess.Board(fen)
    except ValueError:
        return []

    moves: list[chess.Move] = []
    for token in re.findall(r"(?<!\w)[a-z][a-z0-9=+#-]*(?!\w)", question):
        for candidate in (token, _french_san_to_english(token)):
            try:
                move = board.parse_san(candidate)
            except ValueError:
                continue
            if move not in moves:
                moves.append(move)
            break
    return moves


def _contains_concrete_move_without_board(question: str) -> bool:
    return bool(re.search(r"(?<!\w)(?:[a-h][1-8][a-h][1-8][qrbn]?|[nbrqkcftdr]?[a-h]?[1-8]?x?[a-h][1-8](?:=[nbrqkcftdr])?[+#]?|o-o(?:-o)?)(?!\w)", question))


def _french_san_to_english(token: str) -> str:
    if not token:
        return token
    pieces = {"c": "N", "f": "B", "t": "R", "d": "Q", "r": "K", "n": "N", "b": "B", "q": "Q", "k": "K"}
    promoted = re.sub(r"=([cftdr])", lambda match: f"={pieces[match.group(1)]}", token)
    first = promoted[0]
    if first in pieces:
        return pieces[first] + promoted[1:]
    return promoted


def _san_to_french(token: str | None) -> str | None:
    if not token:
        return token
    pieces = {"N": "C", "B": "F", "R": "T", "Q": "D", "K": "R"}
    promoted = re.sub(r"=([NBRQK])", lambda match: f"={pieces[match.group(1)]}", token)
    first = promoted[0]
    if first in pieces:
        return pieces[first] + promoted[1:]
    return promoted


def _normalize(value: str | None) -> str:
    text = (value or "").casefold().replace("...", " ")
    text = text.replace("'", " ").replace("’", " ")
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", ascii_text).strip()
