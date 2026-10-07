import pytest

from backend.app.services.retrieval_contracts import (
    CoachContext,
    CoachProsePassage,
    OpeningTreeContext,
    OpeningTreeNodeContext,
    RetrievalBucket,
    RetrievalPlan,
    RetrievedContext,
    build_coach_context,
)


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


def test_retrieved_context_artifact_keeps_source_attribution_and_relation() -> None:
    context = RetrievedContext(
        chunk_id="chunk-1",
        text="The Ruy Lopez puts pressure on e5.",
        source="wikibooks-chess-opening-theory",
        source_url="https://en.wikibooks.org/wiki/Chess_Opening_Theory/1._e4/1...e5/2._Nf3/2...Nc6/3._Bb5",
        license_or_terms="CC BY-SA 4.0",
        page_id="wikibooks::Ruy Lopez",
        canonical_title="Ruy Lopez",
        section_index=2,
        part_index=0,
        section_title="Main ideas",
        score=0.87,
        relation_to_position="current",
        opening_node_id="ruy-node",
        eco_code="C60",
        opening_name="Ruy Lopez",
    )

    assert context.to_artifact() == {
        "chunk_id": "chunk-1",
        "text": "The Ruy Lopez puts pressure on e5.",
        "source": "wikibooks-chess-opening-theory",
        "source_url": "https://en.wikibooks.org/wiki/Chess_Opening_Theory/1._e4/1...e5/2._Nf3/2...Nc6/3._Bb5",
        "license_or_terms": "CC BY-SA 4.0",
        "page_id": "wikibooks::Ruy Lopez",
        "canonical_title": "Ruy Lopez",
        "section_index": 2,
        "part_index": 0,
        "section_title": "Main ideas",
        "score": 0.87,
        "relation_to_position": "current",
        "entry_move": None,
        "opening_node_id": "ruy-node",
        "eco_code": "C60",
        "opening_name": "Ruy Lopez",
        "intent": None,
        "is_history": False,
        "is_misc": False,
    }


def test_retrieval_plan_can_express_history_only_retrieval() -> None:
    tree_context = OpeningTreeContext(current=RUY)
    plan = RetrievalPlan.history_only(tree_context=tree_context)

    assert plan.intent == "ask_history"
    assert plan.buckets == (
            RetrievalBucket(
                name="history",
                relation_to_position="current",
                node_ids=("ruy-node",),
                eco_code="C60",
                limit=1,
            include_history=True,
            query_hint="history",
        ),
    )


def test_retrieval_plan_can_express_out_of_theory_conservative_retrieval() -> None:
    tree_context = OpeningTreeContext(state="out_of_theory", current=None, fallback_opening_name="Open Game")
    plan = RetrievalPlan.out_of_theory(tree_context=tree_context)

    assert plan.to_artifact() == {
        "intent": "unclear",
        "state": "out_of_theory",
        "reason": "out_of_theory_conservative",
        "requires_stockfish": False,
        "buckets": [
            {
                "name": "fallback",
                "relation_to_position": "fallback",
                "node_ids": [],
                "page_ids": [],
                "eco_code": None,
                "limit": 2,
                "include_history": False,
                "include_misc": False,
                "entry_move": None,
                "query_hint": "Open Game",
            }
        ],
        "excluded_node_ids": [],
    }


def test_child_context_requires_entry_move_for_conditional_labelling() -> None:
    child_context = RetrievedContext(
        chunk_id="chunk-berlin",
        text="The Berlin Defense starts after ...Nf6.",
        source="wikibooks-chess-opening-theory",
        source_url=None,
        license_or_terms="CC BY-SA 4.0",
        page_id="wikibooks::Berlin Defense",
        canonical_title="Berlin Defense",
        section_index=1,
        part_index=0,
        section_title="Overview",
        score=0.74,
        relation_to_position="child",
        entry_move="Nf6",
    )

    assert child_context.to_artifact()["relation_to_position"] == "child"
    assert child_context.to_artifact()["entry_move"] == "Nf6"


def test_coach_context_separates_current_ruy_lopez_and_berlin_child_continuation() -> None:
    coach_context = build_coach_context(
        tree_context=OpeningTreeContext(current=RUY, children=(BERLIN,)),
        question="Pourquoi jouer Nf3 ?",
        retrieved_contexts=(
            RetrievedContext(
                chunk_id="chunk-ruy-plans",
                text="The Ruy Lopez increases pressure on e5 and prepares castling.",
                source="wikibooks-chess-opening-theory",
                source_url="https://en.wikibooks.org/wiki/Chess_Opening_Theory/1._e4/1...e5/2._Nf3/2...Nc6/3._Bb5",
                license_or_terms="CC BY-SA 4.0",
                page_id="wikibooks::ruy-lopez",
                canonical_title="Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5",
                section_index=1,
                part_index=0,
                section_title="Plans",
                score=0.91,
                relation_to_position="current",
                opening_node_id="ruy-node",
                eco_code="C60",
                opening_name="Ruy Lopez",
                intent="plan",
            ),
            RetrievedContext(
                chunk_id="chunk-berlin-overview",
                text="The Berlin Defense begins after Black answers 3.Bb5 with ...Nf6.",
                source="wikibooks-chess-opening-theory",
                source_url="https://en.wikibooks.org/wiki/Chess_Opening_Theory/1._e4/1...e5/2._Nf3/2...Nc6/3._Bb5/3...Nf6",
                license_or_terms="CC BY-SA 4.0",
                page_id="wikibooks::berlin-defense",
                canonical_title="Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5/3...Nf6",
                section_index=0,
                part_index=0,
                section_title="Overview",
                score=0.82,
                relation_to_position="child",
                entry_move="Nf6",
                opening_node_id="berlin-node",
                eco_code="C65",
                opening_name="Ruy Lopez: Berlin Defense",
                intent="variation",
            ),
        ),
        lichess_stats={"source": "lichess-opening-explorer", "games": 240000},
        fallbacks=("youtube_search_fallback",),
    )

    assert coach_context.to_artifact() == {
        "current_position": {
            "state": "matched",
            "opening_name": "Ruy Lopez",
            "eco_code": "C60",
            "pgn": "1. e4 e5 2. Nf3 Nc6 3. Bb5",
            "fen": "ruy-fen",
        },
        "question": "Pourquoi jouer Nf3 ?",
        "current_prose": [
            {
                "text": "The Ruy Lopez increases pressure on e5 and prepares castling.",
                "relation_to_position": "current",
                "entry_move": None,
                "source_chunk_id": "chunk-ruy-plans",
                "opening_name": "Ruy Lopez",
                "eco_code": "C60",
            }
        ],
        "candidate_continuations": [
                {
                    "entry_move": "Nf6",
                    "entry_uci": "g8f6",
                    "opening_name": "Ruy Lopez: Berlin Defense",
                "eco_code": "C65",
                "prose": [
                    {
                        "text": "The Berlin Defense begins after Black answers 3.Bb5 with ...Nf6.",
                        "relation_to_position": "child",
                        "entry_move": "Nf6",
                        "source_chunk_id": "chunk-berlin-overview",
                        "opening_name": "Ruy Lopez: Berlin Defense",
                        "eco_code": "C65",
                    }
                ],
            }
        ],
        "source_attributions": [
            {
                "chunk_id": "chunk-ruy-plans",
                "source": "wikibooks-chess-opening-theory",
                "source_url": "https://en.wikibooks.org/wiki/Chess_Opening_Theory/1._e4/1...e5/2._Nf3/2...Nc6/3._Bb5",
                "license_or_terms": "CC BY-SA 4.0",
                "page_id": "wikibooks::ruy-lopez",
                "canonical_title": "Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5",
                "section_title": "Plans",
                "section_index": 1,
                "part_index": 0,
            },
            {
                "chunk_id": "chunk-berlin-overview",
                "source": "wikibooks-chess-opening-theory",
                "source_url": "https://en.wikibooks.org/wiki/Chess_Opening_Theory/1._e4/1...e5/2._Nf3/2...Nc6/3._Bb5/3...Nf6",
                "license_or_terms": "CC BY-SA 4.0",
                "page_id": "wikibooks::berlin-defense",
                "canonical_title": "Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5/3...Nf6",
                "section_title": "Overview",
                "section_index": 0,
                "part_index": 0,
            },
        ],
        "lichess_stats": {"source": "lichess-opening-explorer", "games": 240000},
        "recommended_moves": [],
        "stockfish": None,
        "fallbacks": ["youtube_search_fallback"],
    }


def test_coach_context_artifact_roundtrip_preserves_user_question() -> None:
    context = build_coach_context(
        tree_context=OpeningTreeContext(current=RUY, children=(BERLIN,)),
        question="Pourquoi jouer Nf3 ?",
        intent="explain_current_position",
    )

    restored = CoachContext.from_artifact(context.to_artifact())

    assert restored.question == "Pourquoi jouer Nf3 ?"
    assert restored.intent == "explain_current_position"
    assert restored.to_artifact()["intent"] == "explain_current_position"


def test_coach_context_out_of_theory_makes_stockfish_authoritative() -> None:
    coach_context = build_coach_context(
        tree_context=OpeningTreeContext(
            state="out_of_theory",
            current=None,
            fallback_opening_name="Italian and Spanish Game family",
        ),
        stockfish={"status": "ok", "best_move": "d2d4", "score": {"type": "cp", "value": 31}},
        fallbacks=("opening_not_matched", "stockfish_evaluation"),
    )

    artifact = coach_context.to_artifact()

    assert artifact["current_position"] == {
        "state": "out_of_theory",
        "opening_name": "Italian and Spanish Game family",
        "eco_code": None,
        "pgn": None,
        "fen": None,
    }
    assert artifact["current_prose"] == []
    assert artifact["candidate_continuations"] == []
    assert artifact["stockfish"] == {
        "status": "ok",
        "best_move": "d2d4",
        "score": {"type": "cp", "value": 31},
    }
    assert artifact["fallbacks"] == ["opening_not_matched", "stockfish_evaluation"]


def test_coach_child_prose_without_entry_move_is_rejected() -> None:
    with pytest.raises(ValueError, match="child coach prose requires entry_move"):
        CoachProsePassage(
            text="Berlin prose must be conditional.",
            relation_to_position="child",
            source_chunk_id="chunk-berlin",
        )


def test_coach_current_prose_cannot_carry_child_entry_move() -> None:
    with pytest.raises(ValueError, match="current coach prose cannot carry entry_move"):
        CoachProsePassage(
            text="Ruy Lopez current prose.",
            relation_to_position="current",
            entry_move="Nf6",
            source_chunk_id="chunk-ruy",
        )


def test_build_coach_context_derives_missing_child_entry_move_from_node() -> None:
    context = build_coach_context(
        tree_context=OpeningTreeContext(current=RUY, children=(BERLIN,)),
        retrieved_contexts=(
            RetrievedContext(
                chunk_id="chunk-child-derived",
                text="Berlin continuation.",
                source="wikibooks",
                source_url="https://example.test/berlin",
                license_or_terms="CC BY-SA 4.0",
                page_id="berlin",
                canonical_title="Berlin",
                section_index=0,
                part_index=0,
                section_title="Overview",
                score=0.8,
                relation_to_position="child",
                opening_node_id="berlin-node",
            ),
        ),
    )

    assert context.candidate_continuations[0].entry_move == "Nf6"
    assert context.candidate_continuations[0].entry_uci == "g8f6"


def test_build_coach_context_routes_supporting_and_history_passages() -> None:
    context = build_coach_context(
        tree_context=OpeningTreeContext(current=RUY),
        retrieved_contexts=(
            RetrievedContext(
                chunk_id="chunk-parent",
                text="Parent context.",
                source="wikibooks",
                source_url="https://example.test/parent",
                license_or_terms="CC BY-SA 4.0",
                page_id="parent",
                canonical_title="Parent",
                section_index=0,
                part_index=0,
                section_title="Context",
                score=0.7,
                relation_to_position="parent",
            ),
            RetrievedContext(
                chunk_id="chunk-history",
                text="Historical context.",
                source="wikibooks",
                source_url="https://example.test/history",
                license_or_terms="CC BY-SA 4.0",
                page_id="history",
                canonical_title="History",
                section_index=0,
                part_index=0,
                section_title="History",
                score=0.7,
                relation_to_position="current",
                is_history=True,
            ),
        ),
    )

    assert [passage.source_chunk_id for passage in context.supporting_prose] == [
        "chunk-parent",
        "chunk-history",
    ]
    assert context.supporting_prose[1].is_history is True
