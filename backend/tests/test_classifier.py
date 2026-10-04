from backend.app.ingestion.classifier import (
    _classify_intent,
    _classify_side,
    classify_page,
    find_duplicates,
)


WIKITEXT = """{{Chess Opening Theory/Position
|Ruy López / Spanish game
|responses=<br>
* [[/3...a6|3...a6 · Morphy's defence]]
}}
== 3. Bb5 · Ruy López or Spanish game ==

3. Bb5 is known as the Ruy López opening or Spanish game. White threatens to trade off Black's c6 knight, the defender of e5, so indirectly threatens to win the pawn.

== History ==

The opening is named after Ruy López de Segura, a Spanish priest who described it in his 1561 book.

== Theory table ==

{{Chess Opening Theory/Table}}

== References ==

{{reflist}}
"""


def test_classify_intent_lead_is_intro() -> None:
    assert _classify_intent("3. Bb5 · Ruy López or Spanish game", 0) == "intro"


def test_classify_intent_history() -> None:
    assert _classify_intent("History", 1) == "history"


def test_classify_intent_move_title_candidate() -> None:
    assert _classify_intent("3...Nf6", 1) == "candidate_move"
    assert _classify_intent("3. Nc3", 1) == "candidate_move"


def test_classify_intent_teaching_plan_headings() -> None:
    assert _classify_intent("Accept the gambit", 1) == "plan"
    assert _classify_intent("Develop a bishop", 1) == "plan"
    assert _classify_intent("Open the position", 1) == "plan"


def test_classify_intent_named_variation_headings() -> None:
    assert _classify_intent("Morphy defence", 1) == "variation"
    assert _classify_intent("Exchange Variation", 1) == "variation"
    assert _classify_intent("Two Knights attack", 1) == "variation"


def test_classify_intent_trap_and_mistake() -> None:
    assert _classify_intent("Traps", 1) == "trap"
    assert _classify_intent("Bad moves", 1) == "mistake"


def test_classify_intent_defaults_to_misc() -> None:
    assert _classify_intent("Some uncertain heading", 1) == "misc"


def test_classify_side_from_move_parity() -> None:
    assert _classify_side("3...Nf6") == "black"
    assert _classify_side("3. Bb5 · Ruy López") == "white"
    assert _classify_side("History") is None


def test_classify_page_accepted_with_sections() -> None:
    result = classify_page("Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5", WIKITEXT)
    assert result.status == "accepted"
    intents = {s.intent for s in result.sections}
    assert "history" in intents
    assert all(s.title != "References" for s in result.sections)
    assert all(s.title != "Theory table" for s in result.sections)


def test_classify_page_keeps_ruy_lopez_continuations_as_teaching_prose() -> None:
    prose = " ".join(["White keeps pressure on e5 and prepares c3 and d4."] * 8)
    morphy = " ".join(["The Morphy defence asks the bishop to choose a square."] * 8)
    result = classify_page(
        "Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5",
        f"== 3. Bb5 · Ruy Lopez ==\n{prose}\n\n=== Morphy defence ===\n{morphy}",
    )

    assert result.status == "accepted"
    assert [(section.title, section.intent) for section in result.sections] == [
        ("3. Bb5 · Ruy Lopez", "intro"),
        ("Morphy defence", "variation"),
    ]
    assert all(section.is_misc is False for section in result.sections)


def test_classify_page_rejects_utility_navigation() -> None:
    result = classify_page("Chess Opening Theory/Super theory table", "{{#invoke:Chess/maximal|run|...}}")
    assert result.status == "rejected"
    assert result.reason == "utility_navigation_page"


def test_classify_page_rejects_eco_volume_index() -> None:
    result = classify_page("Chess Opening Theory/ECO volume A", ":A00: Uncommon Openings: 1. e4")
    assert result.status == "rejected"
    assert result.reason == "utility_navigation_page"


def test_classify_page_rejects_no_prose() -> None:
    result = classify_page("Chess Opening Theory/1. e4/1...c5", "== Theory table ==\n{{Chess Opening Theory/Table}}")
    assert result.status == "rejected"
    assert result.reason in {"no_pedagogical_prose", "low_value_prose"}


def test_is_history_is_misc_derived() -> None:
    result = classify_page("Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5", WIKITEXT)
    history = [s for s in result.sections if s.intent == "history"]
    assert history and history[0].is_history is True and history[0].is_misc is False


def test_find_duplicates_exact() -> None:
    sections = [
        ("p1", "The history of the opening is long and rich.", "History"),
        ("p2", "The history of the opening is long and rich.", "History"),
        ("p3", "An entirely different paragraph about plans.", "Plans"),
    ]
    exact, near = find_duplicates(sections)
    assert len(exact) == 1
    assert {r["page_id"] for r in exact[0]} == {"p1", "p2"}


def test_find_duplicates_near() -> None:
    base = (
        "The Ruy Lopez is one of the oldest and most deeply analyzed chess openings in history. "
        "White's third move attacks the knight that defends the e5 pawn, and the resulting positions "
        "have been studied for over five hundred years by generations of masters and theorists. "
        "Players of all levels encounter this opening regularly, and a solid understanding of its "
        "plans and typical pawn structures is essential for any serious student of the game."
    )
    tweaked = base.replace("five hundred", "six hundred")
    sections = [
        ("p1", base, "History"),
        ("p2", tweaked, "History"),
        ("p3", "Black castles kingside and prepares to attack on the queenside.", "Plan"),
    ]
    exact, near = find_duplicates(sections)
    assert exact == []
    assert len(near) == 1
    assert {near[0]["a"]["page_id"], near[0]["b"]["page_id"]} == {"p1", "p2"}
