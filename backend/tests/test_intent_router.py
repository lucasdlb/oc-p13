import json
import logging
from pathlib import Path

import pytest
import httpx

from backend.app.core.settings import TypeSafeSettings

from backend.app.services.intent_router import (
    _INTENTS,
    CandidateMove,
    IntentDecision,
    IntentRouter,
    IntentRouterContext,
    IntentRouterError,
    JevIntentClassifier,
    RuleBasedIntentClassifier,
)


BERLIN = CandidateMove(
    san="Nf6",
    uci="g8f6",
    opening_name="Ruy Lopez: Berlin Defense",
    eco_code="C65",
    opening_node_id="berlin-node",
)

MORPHY = CandidateMove(
    san="a6",
    uci="a7a6",
    opening_name="Ruy Lopez: Morphy Defense",
    eco_code="C70",
    opening_node_id="morphy-node",
)

QUEENS_GAMBIT_ACCEPTED = CandidateMove(
    san="dxc4",
    uci="d5c4",
    opening_name="Queen's Gambit Accepted",
    eco_code="D20",
    opening_node_id="qga-node",
)

DATASET_PATH = Path(__file__).resolve().parents[2] / "experiments" / "rag" / "eval_v2" / "dataset.json"


def _context(
    question: str | None,
    *,
    candidates: tuple[CandidateMove, ...] = (BERLIN,),
) -> IntentRouterContext:
    return IntentRouterContext(
        question=question,
        level="debutant",
        moves=("e2e4", "e7e5", "g1f3", "b8c6", "f1b5"),
        fen="r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
        current_opening_name="Ruy Lopez",
        current_eco="C60",
        current_node_id="ruy-node",
        legal_child_moves=candidates,
    )


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("Que peuvent jouer les Noirs ?", "ask_next_moves"),
        ("Je fais quoi maintenant ?", "ask_next_moves"),
        ("Si les noirs jouent Nf6, c'est quoi l'idée ?", "ask_specific_candidate"),
        ("Est-ce une erreur de jouer ça ?", "evaluate_move_quality"),
        ("Raconte l'histoire de cette ouverture", "ask_history"),
        ("Quel principe général je dois retenir ?", "general_principle"),
        ("Explique-moi le plan dans cette position", "explain_current_position"),
        ("Quelle est la réponse la plus agressive ?", "compare_moves"),
    ],
)
def test_rule_based_classifier_handles_french_question_variety(question: str, intent: str) -> None:
    decision = RuleBasedIntentClassifier().classify(_context(question))

    assert decision.intent == intent
    assert decision.source == "rule_fallback"
    assert decision.confidence >= 0.5
    assert decision.probabilities is None


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("Si les noirs jouent Cf6, c'est quoi l'idée ?", "ask_specific_candidate"),
        ("Est-ce que Cf6 est correct ?", "evaluate_move_quality"),
        ("Est-ce que Nf6 est un bon coup ?", "evaluate_move_quality"),
        ("Quelle suite est la plus solide ?", "compare_moves"),
        ("Quel coup est le plus joué ?", "compare_moves"),
    ],
)
def test_rule_based_classifier_handles_concrete_moves_and_comparisons(question: str, intent: str) -> None:
    decision = RuleBasedIntentClassifier().classify(_context(question))

    assert decision.intent == intent


@pytest.mark.parametrize(
    "question",
    [
        "Cette position est-elle simple ?",
        "Je veux une version courte.",
        "Explique la position sans planifier trop loin.",
        "Ce coup est incorrect dans le nom de la ligne ?",
        "Que se passe-t-il en 3 coups ?",
        "Après 2 minutes, que dois-je retenir ?",
    ],
)
def test_rule_based_classifier_avoids_substring_false_positives(question: str) -> None:
    decision = RuleBasedIntentClassifier().classify(_context(question))

    assert decision.intent not in {"ask_specific_candidate", "evaluate_move_quality"}


def test_rule_based_classifier_agrees_with_frozen_eval_v2_questions() -> None:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    classifier = RuleBasedIntentClassifier()

    decisions = {
        case["id"]: classifier.classify(
            _context(case["question"], candidates=(BERLIN, MORPHY, QUEENS_GAMBIT_ACCEPTED))
        ).intent
        for case in dataset["cases"]
    }
    routed_cases = [case for case in dataset["cases"] if case["intent"] not in {"ask_unsupported", "ask_out_of_theory"}]
    mismatches = {
        case["id"]: (case["intent"], decisions[case["id"]])
        for case in routed_cases
        if decisions[case["id"]] != case["intent"]
    }

    assert len(routed_cases) - len(mismatches) >= 14, mismatches
    assert decisions["explain-espagnole-001"] == "explain_current_position"
    assert decisions["explain-italienne-002"] == "explain_current_position"
    assert decisions["explain-najdorf-003"] == "explain_current_position"
    assert decisions["next-espagnole-001"] == "ask_next_moves"
    assert decisions["next-sicilienne-003"] == "ask_next_moves"
    assert decisions["history-indienne-roi-002"] == "ask_history"
    assert decisions["principle-developpement-001"] == "general_principle"


def test_specific_candidate_records_matched_child_move() -> None:
    decision = RuleBasedIntentClassifier().classify(_context("Est-ce que Berlin Defense est possible ?"))

    assert decision.intent == "ask_specific_candidate"
    assert decision.matched_candidate_move == BERLIN
    assert "matched_candidate_move" in decision.reason_codes


def test_empty_question_is_unclear_and_low_confidence() -> None:
    decision = RuleBasedIntentClassifier().classify(_context(None))

    assert decision.intent == "unclear"
    assert decision.confidence < 0.5


class FailingPrimary:
    def classify(self, context: IntentRouterContext) -> IntentDecision:
        raise IntentRouterError("provider unavailable")


class LowConfidencePrimary:
    def classify(self, context: IntentRouterContext) -> IntentDecision:
        return IntentDecision(
            intent="ask_next_moves",
            confidence=0.2,
            probabilities={"ask_next_moves": 0.2},
            source="jev",
            provider_model="jev-1.13.0",
        )


class InvalidPrimary:
    def classify(self, context: IntentRouterContext) -> IntentDecision:
        return IntentDecision(  # type: ignore[arg-type]
            intent="freeform_plan",
            confidence=0.9,
            probabilities={},
            source="jev",
        )


class CrashingPrimary:
    def classify(self, context: IntentRouterContext) -> IntentDecision:
        raise AttributeError("unexpected provider crash")


def test_router_falls_back_when_primary_provider_fails() -> None:
    decision = IntentRouter(primary=FailingPrimary()).classify(_context("Que jouer ?"))

    assert decision.intent == "ask_next_moves"
    assert decision.source == "fallback_after_provider_error"
    assert "primary_provider_error" in decision.reason_codes


def test_router_falls_back_when_primary_confidence_is_low() -> None:
    decision = IntentRouter(primary=LowConfidencePrimary()).classify(_context("Que jouer ?"))

    assert decision.intent == "ask_next_moves"
    assert decision.source == "fallback_after_low_confidence"
    assert "primary_low_confidence" in decision.reason_codes



def test_router_falls_back_when_primary_response_is_invalid() -> None:
    decision = IntentRouter(primary=InvalidPrimary()).classify(_context("Que jouer ?"))

    assert decision.intent == "ask_next_moves"
    assert decision.source == "fallback_after_invalid_response"
    assert "primary_invalid_response" in decision.reason_codes


def test_router_falls_back_when_primary_crashes_unexpectedly() -> None:
    decision = IntentRouter(primary=CrashingPrimary()).classify(_context("Que jouer ?"))

    assert decision.intent == "ask_next_moves"
    assert decision.source == "fallback_after_provider_error"
    assert "primary_unexpected_error" in decision.reason_codes



def test_jev_classifier_disabled_by_default_routes_to_fallback() -> None:
    decision = IntentRouter(primary=JevIntentClassifier()).classify(_context("Que jouer ?"))

    assert decision.intent == "ask_next_moves"
    assert decision.source == "fallback_after_provider_error"


def test_jev_classifier_validates_provider_success_without_logging_secret(caplog) -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        requests.append(payload)
        assert request.headers["authorization"] == "Bearer ts-key"
        assert "ts-key" not in repr(payload)
        assert request.url.path.endswith("/v1/systemone")
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {
                    "intent": {
                        "type": "choice",
                        "choice": "ask_next_moves",
                        "confidence": 0.86,
                        "probabilities": {
                            "ask_next_moves": 0.86,
                            "explain_current_position": 0.05,
                            "ask_specific_candidate": 0.03,
                            "evaluate_move_quality": 0.02,
                            "ask_trap": 0.01,
                            "ask_mistake": 0.01,
                            "ask_history": 0.01,
                            "ask_unsupported": 0.01,
                            "ask_out_of_theory": 0.0,
                            "general_principle": 0.0,
                            "unclear": 0.0,
                        },
                    }
                },
                "usage": {"input_tokens": 120, "output_tokens": 12},
            },
        )

    classifier = JevIntentClassifier(
        settings=TypeSafeSettings(
            enabled=True,
            api_key="ts-key",
            base_url="https://gateway.example.test/typesafe",
            model="jev-1.13.0",
        ),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with caplog.at_level(logging.INFO, logger="backend.intent_router"):
        decision = classifier.classify(_context("Que jouer ?"))

    assert decision.intent == "ask_next_moves"
    assert decision.confidence == 0.86
    assert decision.source == "jev"
    assert decision.provider_model == "jev-1.13.0"
    assert decision.reason_codes == ("jev_choice",)
    request_payload = requests[0]
    assert request_payload["model"] == "jev-1.13.0"
    assert request_payload["questions"]["intent"]["type"] == "choice"
    assert set(request_payload["questions"]["intent"]["criteria"]) == set(_INTENTS) - {
        "ask_unsupported",
        "ask_out_of_theory",
    }
    assert request_payload["state"]["legal_child_moves"] == [
        {
            "san": "Nf6",
            "uci": "g8f6",
            "opening_name": "Ruy Lopez: Berlin Defense",
            "eco_code": "C65",
            "opening_node_id": "berlin-node",
        }
    ]
    assert any(
        getattr(record, "provider_model", None) == "jev-1.13.0"
        and getattr(record, "confidence", None) == 0.86
        for record in caplog.records
    )
    assert "ts-key" not in caplog.text


def test_jev_classifier_routes_to_fallback_on_timeout() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    classifier = JevIntentClassifier(
        settings=TypeSafeSettings(enabled=True, api_key="ts-key"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    decision = IntentRouter(primary=classifier).classify(_context("Que jouer ?"))

    assert decision.intent == "ask_next_moves"
    assert decision.source == "fallback_after_provider_error"


def test_jev_classifier_routes_to_fallback_on_invalid_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {
                    "intent": {
                        "type": "choice",
                        "choice": "freeform_plan",
                        "confidence": 0.9,
                        "probabilities": {},
                    }
                },
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    classifier = JevIntentClassifier(
        settings=TypeSafeSettings(enabled=True, api_key="ts-key"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    decision = IntentRouter(primary=classifier).classify(_context("Que jouer ?"))

    assert decision.intent == "ask_next_moves"
    assert decision.source == "fallback_after_invalid_response"


def test_jev_low_confidence_cannot_unlock_child_prose_intent() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {
                    "intent": {
                        "type": "choice",
                        "choice": "ask_next_moves",
                        "confidence": 0.2,
                        "probabilities": {
                            "ask_next_moves": 0.2,
                            "explain_current_position": 0.8,
                        },
                    }
                },
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    classifier = JevIntentClassifier(
        settings=TypeSafeSettings(enabled=True, api_key="ts-key"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    decision = IntentRouter(primary=classifier, medium_confidence=0.5).classify(_context("Bonjour"))

    assert decision.intent == "explain_current_position"
    assert decision.source == "fallback_after_low_confidence"


def test_jev_enabled_without_key_routes_to_fallback() -> None:
    classifier = JevIntentClassifier(settings=TypeSafeSettings(enabled=True, api_key=None))

    decision = IntentRouter(primary=classifier).classify(_context("Que jouer ?"))

    assert decision.intent == "ask_next_moves"
    assert decision.source == "fallback_after_provider_error"
