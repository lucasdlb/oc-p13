from backend.app.services.intent_router import CandidateMove, IntentDecision
from backend.app.services.retrieval_contracts import OpeningTreeContext, OpeningTreeNodeContext
from backend.app.services.retrieval_plan_builder import ROOT_OPENING_PAGE_ID, build_retrieval_plan


RUY = OpeningTreeNodeContext(
    node_id="ruy-node",
    eco_code="C60",
    opening_name="Ruy Lopez",
    pgn="1. e4 e5 2. Nf3 Nc6 3. Bb5",
    uci=("e2e4", "e7e5", "g1f3", "b8c6", "f1b5"),
    san=("e4", "e5", "Nf3", "Nc6", "Bb5"),
    fen="ruy-fen",
    epd="ruy-epd",
    depth=5,
)

OPEN_GAME = OpeningTreeNodeContext(
    node_id="open-game-node",
    eco_code="C20",
    opening_name="Open Game",
    pgn="1. e4 e5",
    uci=("e2e4", "e7e5"),
    san=("e4", "e5"),
    fen="open-game-fen",
    epd="open-game-epd",
    depth=2,
)

BERLIN = OpeningTreeNodeContext(
    node_id="berlin-node",
    eco_code="C65",
    opening_name="Ruy Lopez: Berlin Defense",
    pgn="1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6",
    uci=("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6"),
    san=("e4", "e5", "Nf3", "Nc6", "Bb5", "Nf6"),
    fen="berlin-fen",
    epd="berlin-epd",
    depth=6,
    entry_move="Nf6",
)

MORPHY = OpeningTreeNodeContext(
    node_id="morphy-node",
    eco_code="C68",
    opening_name="Ruy Lopez: Morphy Defense",
    pgn="1. e4 e5 2. Nf3 Nc6 3. Bb5 a6",
    uci=("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"),
    san=("e4", "e5", "Nf3", "Nc6", "Bb5", "a6"),
    fen="morphy-fen",
    epd="morphy-epd",
    depth=6,
    entry_move="a6",
)


TREE = OpeningTreeContext(
    current=RUY,
    parent=OPEN_GAME,
    children=(BERLIN, MORPHY),
    excluded_descendant_node_ids=("rio-gambit-node", "arkhangelsk-node"),
)


def _decision(intent: str, confidence: float = 0.86, *, matched: CandidateMove | None = None) -> IntentDecision:
    return IntentDecision(
        intent=intent,  # type: ignore[arg-type]
        confidence=confidence,
        probabilities={intent: confidence},  # type: ignore[dict-item]
        matched_candidate_move=matched,
    )


def test_explain_current_position_uses_current_prose_and_excludes_descendants() -> None:
    plan = build_retrieval_plan(TREE, _decision("explain_current_position"))

    assert plan.intent == "explain_current_position"
    assert plan.requires_stockfish is False
    assert [(bucket.name, bucket.relation_to_position, bucket.node_ids) for bucket in plan.buckets] == [
        ("current", "current", ("ruy-node",)),
        ("parent", "parent", ("open-game-node",)),
    ]
    assert plan.excluded_node_ids == ("rio-gambit-node", "arkhangelsk-node")


def test_ask_next_moves_allows_direct_children_with_separate_budget() -> None:
    plan = build_retrieval_plan(TREE, _decision("ask_next_moves", confidence=0.9))

    child_bucket = plan.buckets[1]
    assert child_bucket.name == "children"
    assert child_bucket.relation_to_position == "child"
    assert child_bucket.node_ids == ("berlin-node", "morphy-node")
    assert child_bucket.limit == 3
    assert child_bucket.query_hint == "conditional continuations"
    assert plan.excluded_node_ids == ("rio-gambit-node", "arkhangelsk-node")


def test_medium_confidence_next_moves_caps_child_budget_tightly() -> None:
    plan = build_retrieval_plan(TREE, _decision("ask_next_moves", confidence=0.62))

    assert plan.buckets[1].name == "children"
    assert plan.buckets[1].limit == 1
    assert plan.reason == "child_allowed_medium_confidence"


def test_specific_candidate_allows_only_matched_child() -> None:
    plan = build_retrieval_plan(
        TREE,
        _decision(
            "ask_specific_candidate",
            matched=CandidateMove(san="Nf6", opening_node_id="berlin-node", opening_name="Ruy Lopez: Berlin Defense"),
        ),
    )

    assert plan.buckets[1].name == "matched_child"
    assert plan.buckets[1].node_ids == ("berlin-node",)
    assert plan.buckets[1].entry_move == "Nf6"


def test_specific_candidate_without_known_child_falls_back_current_only() -> None:
    plan = build_retrieval_plan(
        TREE,
        _decision("ask_specific_candidate", matched=CandidateMove(san="d4", opening_node_id="unknown-node")),
    )

    assert [bucket.name for bucket in plan.buckets] == ["current"]
    assert plan.reason == "specific_candidate_not_in_direct_children"


def test_evaluate_move_quality_requires_stockfish_without_broad_child_prose() -> None:
    plan = build_retrieval_plan(TREE, _decision("evaluate_move_quality"))

    assert plan.requires_stockfish is True
    assert [bucket.name for bucket in plan.buckets] == ["current"]
    assert all(bucket.relation_to_position != "child" for bucket in plan.buckets)


def test_compare_moves_uses_children_and_stockfish() -> None:
    plan = build_retrieval_plan(TREE, _decision("compare_moves"))

    assert plan.intent == "compare_moves"
    assert plan.requires_stockfish is True
    assert [(bucket.name, bucket.relation_to_position) for bucket in plan.buckets] == [
        ("current", "current"),
        ("children", "child"),
    ]
    assert plan.buckets[1].node_ids == ("berlin-node", "morphy-node")
    assert plan.reason == "compare_children_with_stockfish"


def test_ask_history_limits_history_to_current_node() -> None:
    plan = build_retrieval_plan(TREE, _decision("ask_history"))

    assert plan.buckets[0].name == "history"
    assert plan.buckets[0].node_ids == ("ruy-node",)
    assert plan.buckets[0].limit == 1
    assert plan.buckets[0].include_history is True
    assert plan.buckets[0].include_misc is False


def test_trap_and_mistake_are_current_line_only() -> None:
    trap = build_retrieval_plan(TREE, _decision("ask_trap"))
    mistake = build_retrieval_plan(TREE, _decision("ask_mistake"))

    assert [bucket.name for bucket in trap.buckets] == ["current"]
    assert [bucket.name for bucket in mistake.buckets] == ["current"]
    assert trap.reason == "trap_current_line"
    assert mistake.reason == "mistake_current_line"


def test_unsupported_and_out_of_theory_do_not_retrieve_book_prose() -> None:
    unsupported = build_retrieval_plan(TREE, _decision("ask_unsupported"))
    out_of_theory = build_retrieval_plan(
        OpeningTreeContext(state="out_of_theory"),
        _decision("ask_out_of_theory"),
    )

    assert unsupported.buckets == ()
    assert unsupported.reason == "no_supported_theory_context"
    assert out_of_theory.buckets == ()
    assert out_of_theory.requires_stockfish is True


def test_general_principle_avoids_child_opening_prose() -> None:
    plan = build_retrieval_plan(TREE, _decision("general_principle"))

    assert [bucket.name for bucket in plan.buckets] == ["current"]
    assert all(bucket.relation_to_position != "child" for bucket in plan.buckets)


def test_general_principle_without_current_node_searches_only_root_page() -> None:
    plan = build_retrieval_plan(
        OpeningTreeContext(state="unsupported"),
        _decision("general_principle"),
    )

    assert plan.reason == "general_principle_root_page"
    assert [bucket.name for bucket in plan.buckets] == ["root_general"]
    assert plan.buckets[0].page_ids == (ROOT_OPENING_PAGE_ID,)
    assert plan.buckets[0].node_ids == ()


def test_unclear_low_confidence_and_out_of_theory_are_conservative() -> None:
    unclear = build_retrieval_plan(TREE, _decision("unclear", confidence=0.9))
    low_confidence = build_retrieval_plan(TREE, _decision("ask_next_moves", confidence=0.4))
    out_of_theory = build_retrieval_plan(
        OpeningTreeContext(state="out_of_theory"),
        _decision("ask_next_moves", confidence=0.9),
    )

    assert [bucket.name for bucket in unclear.buckets] == ["current"]
    assert unclear.reason == "unclear_conservative"
    assert [bucket.name for bucket in low_confidence.buckets] == ["current"]
    assert low_confidence.reason == "low_confidence_conservative"
    assert out_of_theory.buckets == ()
    assert out_of_theory.reason == "out_of_theory_no_book_context"


def test_out_of_theory_state_never_retrieves_opening_prose_for_standard_intents() -> None:
    tree_context = OpeningTreeContext(state="out_of_theory")

    for intent in ("explain_current_position", "ask_next_moves"):
        plan = build_retrieval_plan(tree_context, _decision(intent))

        assert plan.buckets == ()
        assert plan.reason == "out_of_theory_no_book_context"


def test_out_of_theory_question_keeps_intent_separate_and_requires_stockfish() -> None:
    plan = build_retrieval_plan(OpeningTreeContext(state="out_of_theory"), _decision("ask_out_of_theory"))

    assert plan.buckets == ()
    assert plan.intent == "ask_out_of_theory"
    assert plan.requires_stockfish is True


def test_default_plans_always_exclude_deep_descendants() -> None:
    intents = (
        "explain_current_position",
        "ask_next_moves",
        "ask_specific_candidate",
        "evaluate_move_quality",
        "compare_moves",
        "ask_trap",
        "ask_mistake",
        "ask_history",
        "ask_unsupported",
        "ask_out_of_theory",
        "general_principle",
        "unclear",
    )

    for intent in intents:
        plan = build_retrieval_plan(TREE, _decision(intent))
        assert plan.excluded_node_ids == ("rio-gambit-node", "arkhangelsk-node")
