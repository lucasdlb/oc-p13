import json
import logging
from pathlib import Path

import pytest
import httpx

from backend.app.core.settings import TypeSafeSettings

from backend.app.services.intent_router import (
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
    ],
)
def test_rule_based_classifier_handles_french_question_variety(question: str, intent: str) -> None:
    decision = RuleBasedIntentClassifier().classify(_context(question))

    assert decision.intent == intent
    assert decision.source == "rule_fallback"
    assert decision.confidence >= 0.5
    assert decision.probabilities[decision.intent] == pytest.approx(decision.confidence)


def test_rule_based_classifier_agrees_with_frozen_eval_v2_questions() -> None:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    classifier = RuleBasedIntentClassifier()

    decisions = {
        case["id"]: classifier.classify(
            _context(case["question"], candidates=(BERLIN, MORPHY, QUEENS_GAMBIT_ACCEPTED))
        ).intent
        for case in dataset["cases"]
    }
    mismatches = {
        case["id"]: (case["intent"], decisions[case["id"]])
        for case in dataset["cases"]
        if decisions[case["id"]] != case["intent"]
    }

    assert len(decisions) - len(mismatches) >= 18, mismatches
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



def test_jev_classifier_seam_fails_closed_until_adapter_is_implemented() -> None:
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
        return httpx.Response(
            200,
            json={
                "choice": "ask_next_moves",
                "confidence": 0.86,
                "reason_codes": ["jev_choice"],
                "model": "jev-1.13.0",
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
    assert requests[0]["choices"] == [
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
    assert requests[0]["context"]["legal_child_moves"] == [
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
        return httpx.Response(200, json={"choice": "freeform_plan", "confidence": 0.9})

    classifier = JevIntentClassifier(
        settings=TypeSafeSettings(enabled=True, api_key="ts-key"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    decision = IntentRouter(primary=classifier).classify(_context("Que jouer ?"))

    assert decision.intent == "ask_next_moves"
    assert decision.source == "fallback_after_invalid_response"


def test_jev_low_confidence_cannot_unlock_child_prose_intent() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choice": "ask_next_moves", "confidence": 0.2})

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
