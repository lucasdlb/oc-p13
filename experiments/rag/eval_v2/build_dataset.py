"""Build the frozen Eval V2 dataset.

The dataset defines the production-shaped judge for retrieval over the full
Wikibooks corpus: cases carry a position/opening, a user intent, and an
``expected_context`` that separates current prose from conditional child prose
and forbidden pollution. The ``test`` split is frozen (its sha256 is stored in
the dataset ``_meta``) so retrieval parameters can be tuned on ``dev`` without
changing the judge.

Run::

    python experiments/rag/eval_v2/build_dataset.py

The output is ``experiments/rag/eval_v2/dataset.json``. The builder is
deterministic: rerunning it produces byte-identical content (the ``frozen_at``
timestamp is not part of the frozen test split, so it may differ across runs).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "dataset.json"

SCHEMA_VERSION = 1

INTENT_VOCABULARY = {
    "explain_current_position": "Explain the current opening/position from its own prose.",
    "ask_next_moves": "Ask what moves are available next (current prose + direct child prose).",
    "ask_specific_candidate": "Ask about one specific candidate move (child prose filtered by entry move).",
    "ask_trap": "Ask whether a line contains a trap or tactical pitfall.",
    "ask_mistake": "Ask about common mistakes / bad moves in a line.",
    "ask_history": "Ask about the history / origin / naming of an opening.",
    "ask_unsupported": "Ask about an opening the corpus cannot source; the coach must not fabricate.",
    "ask_out_of_theory": "Position has left known theory; no book prose is expected.",
    "general_principle": "Ask for general opening principles, not a specific line.",
}

CATEGORY_VOCABULARY = {
    "current_opening_explanation": "Explain the current opening (intro/plan prose only).",
    "next_moves": "Ask which moves are available next.",
    "specific_candidate_move": "Ask about one specific candidate move.",
    "trap": "Ask about a trap or tactical pitfall in a line.",
    "mistake": "Ask about common mistakes / bad moves.",
    "history": "Ask about the history of an opening.",
    "unsupported_opening": "Ask about an opening with no supported source.",
    "out_of_theory": "Position left known theory.",
    "general_principle": "Ask for general opening principles.",
}

SUPPORT_VOCABULARY = {
    "in_theory": "Opening identified in the opening tree; prose expected.",
    "out_of_theory": "Position left the opening tree; last-known opening recorded, no prose expected.",
    "unsupported": "Opening/position has no supported source; the coach must not fabricate.",
}

_SRC = "wikibooks-chess-opening-theory"


def _page(title: str) -> str:
    return f"{_SRC}::{title}"


def _ctx(current: list[str], child: list[str], forbidden: list[str]) -> dict:
    return {
        "current_prose": current,
        "child_prose_allowed": child,
        "forbidden": forbidden,
    }


CASES: list[dict] = [
    # --- current opening explanation -------------------------------------
    {
        "id": "explain-espagnole-001",
        "split": "test",
        "category": "current_opening_explanation",
        "intent": "explain_current_position",
        "support": "in_theory",
        "position": "1. e4 e5 2. Nf3 Nc6 3. Bb5",
        "fen": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
        "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"],
        "current_opening": "Ruy Lopez",
        "current_eco": "C60",
        "opening_node_id": "26f6291ee49df547eebde1dd10325adf0746f3e9c4c102915f2a0de0dd5cd59c",
        "page_id": _page("Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5"),
        "question": "Qu'est-ce que l'ouverture espagnole ? Explique-moi cette position.",
        "expected_context": _ctx(
            ["3. Bb5 · Ruy López or Spanish game"],
            [],
            ["History", "Morphy defence", "Berlin defence", "deep descendant prose"],
        ),
    },
    {
        "id": "explain-italienne-002",
        "split": "dev",
        "category": "current_opening_explanation",
        "intent": "explain_current_position",
        "support": "in_theory",
        "position": "1. e4 e5 2. Nf3 Nc6 3. Bc4",
        "fen": "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
        "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4"],
        "current_opening": "Italian Game",
        "current_eco": "C50",
        "opening_node_id": "cfe1244c3ca2c0eee929847be95aa44b0dd843fefcdc010954e400ab2d8de601",
        "page_id": _page("Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bc4"),
        "question": "Peux-tu m'expliquer l'ouverture italienne ?",
        "expected_context": _ctx(
            ["3. Bc4 · Italian game"],
            [],
            ["History", "Attack e4", "Control g5", "Wild gambits"],
        ),
    },
    {
        "id": "explain-najdorf-003",
        "split": "dev",
        "category": "current_opening_explanation",
        "intent": "explain_current_position",
        "support": "in_theory",
        "position": "1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6",
        "fen": "rnbqkb1r/1p2pppp/p2p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6",
        "moves": ["e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "a7a6"],
        "current_opening": "Sicilian Defense: Najdorf Variation",
        "current_eco": "B90",
        "opening_node_id": "dac5aaa767222091b27968cc6f5240b3d43c382aef4d4fc11c2daeeb372a3045",
        "page_id": _page("Chess Opening Theory/1. e4/1...c5/2. Nf3/2...d6/3. d4/3...cxd4/4. Nxd4/4...Nf6/5. Nc3/5...a6"),
        "question": "C'est quoi la Najdorf ? Explique-moi cette variante.",
        "expected_context": _ctx(
            ["5...a6 · Najdorf variation"],
            [],
            ["History", "Develop a bishop", "Attack on the kingside", "Lock up the queenside"],
        ),
    },
    # --- next moves --------------------------------------------------------
    {
        "id": "next-espagnole-001",
        "split": "test",
        "category": "next_moves",
        "intent": "ask_next_moves",
        "support": "in_theory",
        "position": "1. e4 e5 2. Nf3 Nc6 3. Bb5",
        "fen": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
        "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"],
        "current_opening": "Ruy Lopez",
        "current_eco": "C60",
        "opening_node_id": "26f6291ee49df547eebde1dd10325adf0746f3e9c4c102915f2a0de0dd5cd59c",
        "page_id": _page("Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5"),
        "question": "Que peuvent jouer les Noirs maintenant ?",
        "expected_context": _ctx(
            ["3. Bb5 · Ruy López or Spanish game"],
            [
                "Ruy Lopez: Berlin Defense",
                "Ruy Lopez: Morphy Defense",
                "Ruy Lopez: Classical Variation",
                "Ruy Lopez: Steinitz Defense",
                "Ruy Lopez: Schliemann Defense",
            ],
            ["History", "deep descendant prose (Berlin/Morphy sublines several moves deeper)"],
        ),
    },
    {
        "id": "next-gambit-dame-002",
        "split": "dev",
        "category": "next_moves",
        "intent": "ask_next_moves",
        "support": "in_theory",
        "position": "1. d4 d5 2. c4",
        "fen": "rnbqkbnr/ppp1pppp/8/3p4/2PP4/8/PP2PPPP/RNBQKBNR b KQkq - 0 2",
        "moves": ["d2d4", "d7d5", "c2c4"],
        "current_opening": "Queen's Gambit",
        "current_eco": "D06",
        "opening_node_id": "77bd1796cde64304a5ddc91b1415f9b802d998401eec35306a51412e62826a9d",
        "page_id": _page("Chess Opening Theory/1. d4/1...d5/2. c4"),
        "question": "Que peut faire mon adversaire après 2.c4 ?",
        "expected_context": _ctx(
            ["2. c4 · Queen's gambit"],
            [
                "Queen's Gambit Accepted",
                "Queen's Gambit Declined",
                "Slav Defense",
                "Queen's Gambit Declined: Albin Countergambit",
            ],
            ["deep descendant prose"],
        ),
    },
    {
        "id": "next-sicilienne-003",
        "split": "dev",
        "category": "next_moves",
        "intent": "ask_next_moves",
        "support": "in_theory",
        "position": "1. e4 c5",
        "fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "moves": ["e2e4", "c7c5"],
        "current_opening": "Sicilian Defense",
        "current_eco": "B20",
        "opening_node_id": "875f0b1f41f1a385736f0ef39d6ccb8d2ba853f1c8f6b137f42a76145f748e82",
        "page_id": _page("Chess Opening Theory/1. e4/1...c5"),
        "question": "Comment je dois continuer face à la sicilienne ?",
        "expected_context": _ctx(
            ["1...c5 · Sicilian defence"],
            [
                "Sicilian Defense: Alapin Variation",
                "Sicilian Defense: Closed",
                "Sicilian Defense: Smith-Morra Gambit",
                "Sicilian Defense: McDonnell Attack",
            ],
            ["History", "Bad moves", "deep descendant prose"],
        ),
    },
    # --- specific candidate move -------------------------------------------
    {
        "id": "candidate-morphy-001",
        "split": "test",
        "category": "specific_candidate_move",
        "intent": "ask_specific_candidate",
        "support": "in_theory",
        "position": "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6",
        "fen": "r1bqkbnr/1ppp1ppp/p1n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 4",
        "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"],
        "current_opening": "Ruy Lopez: Morphy Defense",
        "current_eco": "C70",
        "opening_node_id": "2e07325ce750e2ea975138842154a8050bc94562f5702b8066c635fa03489e50",
        "page_id": _page("Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5/3...a6"),
        "question": "Que dois-je faire si mon adversaire joue 3...a6 ?",
        "expected_context": _ctx(
            ["3...a6 · Morphy defence"],
            ["Ruy Lopez: Morphy Defense"],
            ["History", "other Ruy Lopez children (Berlin, Steinitz, ...)", "deep descendant prose"],
        ),
    },
    {
        "id": "candidate-gambit-accepte-002",
        "split": "dev",
        "category": "specific_candidate_move",
        "intent": "ask_specific_candidate",
        "support": "in_theory",
        "position": "1. d4 d5 2. c4 dxc4",
        "fen": "rnbqkbnr/ppp1pppp/8/8/2pP4/8/PP2PPPP/RNBQKBNR w KQkq - 0 3",
        "moves": ["d2d4", "d7d5", "c2c4", "d5c4"],
        "current_opening": "Queen's Gambit Accepted",
        "current_eco": "D20",
        "opening_node_id": "d2e5a6a4eafba7e5bc768ac29d070732085b342d08a74bb5c4fc4f43121b32b0",
        "page_id": _page("Chess Opening Theory/1. d4/1...d5/2. c4/2...dxc4"),
        "question": "Est-ce que je peux prendre le pion avec 2...dxc4 ?",
        "expected_context": _ctx(
            ["2...dxc4 · Queen's Gambit Accepted"],
            ["Queen's Gambit Accepted"],
            ["Queen's Gambit Declined prose", "Slav Defense prose", "deep descendant prose"],
        ),
    },
    # --- trap ---------------------------------------------------------------
    {
        "id": "trap-blackmar-001",
        "split": "test",
        "category": "trap",
        "intent": "ask_trap",
        "support": "in_theory",
        "position": "1. d4 d5 2. e4 dxe4 3. Nc3 c5",
        "fen": "rnbqkbnr/pp2pppp/8/2p5/3Pp3/2N5/PPP2PPP/R1BQKBNR w KQkq - 0 4",
        "moves": ["d2d4", "d7d5", "e2e4", "d5e4", "b1c3", "c7c5"],
        "current_opening": "Blackmar-Diemer Gambit: Reversed Albin Countergambit",
        "current_eco": "D00",
        "opening_node_id": "1156707e870161a66bb5669fee30296180809a93ae8bf1bca387d24ea7703b23",
        "page_id": _page("Chess Opening Theory/1. d4/1...d5/2. e4/2...dxe4/3. Nc3/3...c5"),
        "question": "Y a-t-il un piège que je dois connaître dans cette ligne ?",
        "expected_context": _ctx(
            ["Traps"],
            [],
            ["History", "intro prose unrelated to the trap", "deep descendant prose"],
        ),
    },
    {
        "id": "trap-dutch-002",
        "split": "dev",
        "category": "trap",
        "intent": "ask_trap",
        "support": "in_theory",
        "position": "1. d4 f5 2. Nc3",
        "fen": "rnbqkbnr/ppppp1pp/8/5p2/3P4/2N5/PPP1PPPP/R1BQKBNR b KQkq - 1 2",
        "moves": ["d2d4", "f7f5", "b1c3"],
        "current_opening": "Dutch Defense: Raphael Variation",
        "current_eco": "A80",
        "opening_node_id": "5458ddab136e273490a212be41819a98c3705ef842575e0431b4eb6d1c456df7",
        "page_id": _page("Chess Opening Theory/1. d4/1...f5/2. Nc3"),
        "question": "Quel piège dois-je éviter dans cette position ?",
        "expected_context": _ctx(
            ["Traps"],
            [],
            ["History", "intro prose unrelated to the trap"],
        ),
    },
    # --- mistake ------------------------------------------------------------
    {
        "id": "mistake-sicilienne-001",
        "split": "test",
        "category": "mistake",
        "intent": "ask_mistake",
        "support": "in_theory",
        "position": "1. e4 c5",
        "fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "moves": ["e2e4", "c7c5"],
        "current_opening": "Sicilian Defense",
        "current_eco": "B20",
        "opening_node_id": "875f0b1f41f1a385736f0ef39d6ccb8d2ba853f1c8f6b137f42a76145f748e82",
        "page_id": _page("Chess Opening Theory/1. e4/1...c5"),
        "question": "Quelles sont les erreurs classiques des Noirs dans la sicilienne ?",
        "expected_context": _ctx(
            ["Bad moves", "1...c5 · Sicilian defence"],
            [],
            ["History", "deep descendant prose"],
        ),
    },
    {
        "id": "mistake-scandinave-002",
        "split": "dev",
        "category": "mistake",
        "intent": "ask_mistake",
        "support": "in_theory",
        "position": "1. e4 d5",
        "fen": "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "moves": ["e2e4", "d7d5"],
        "current_opening": "Scandinavian Defense",
        "current_eco": "B01",
        "opening_node_id": "f756ceb6f7161e71fccd2f6670469054a253c89c20d59a67b04474c642bcc856",
        "page_id": _page("Chess Opening Theory/1. e4/1...d5"),
        "question": "Quel est le mauvais coup à éviter après 1.e4 d5 ?",
        "expected_context": _ctx(
            ["Bad moves", "1...d5 · Scandinavian defence"],
            [],
            ["History", "deep descendant prose"],
        ),
    },
    # --- history ------------------------------------------------------------
    {
        "id": "history-espagnole-001",
        "split": "test",
        "category": "history",
        "intent": "ask_history",
        "support": "in_theory",
        "position": "1. e4 e5 2. Nf3 Nc6 3. Bb5",
        "fen": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
        "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"],
        "current_opening": "Ruy Lopez",
        "current_eco": "C60",
        "opening_node_id": "26f6291ee49df547eebde1dd10325adf0746f3e9c4c102915f2a0de0dd5cd59c",
        "page_id": _page("Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bb5"),
        "question": "D'où vient le nom de l'ouverture espagnole ?",
        "expected_context": _ctx(
            ["History"],
            [],
            ["3. Bb5 · Ruy López or Spanish game", "Morphy defence", "Berlin defence", "deep descendant prose"],
        ),
    },
    {
        "id": "history-indienne-roi-002",
        "split": "dev",
        "category": "history",
        "intent": "ask_history",
        "support": "in_theory",
        "position": "1. d4 Nf6 2. c4 g6",
        "fen": "rnbqkb1r/pppppp1p/5np1/8/2PP4/8/PP2PPPP/RNBQKBNR w KQkq - 0 3",
        "moves": ["d2d4", "g8f6", "c2c4", "g7g6"],
        "current_opening": "King's Indian Defense",
        "current_eco": "E60",
        "opening_node_id": "763b4c14df6668c1adb1024841865c48678a44b6a9094b24f59296b6caa4b519",
        "page_id": _page("Chess Opening Theory/1. d4/1...Nf6/2. c4/2...g6"),
        "question": "Quelle est l'histoire de la défense est-indienne ?",
        "expected_context": _ctx(
            ["History"],
            [],
            ["2...g6 · King's Indian defence", "deep descendant prose"],
        ),
    },
    # --- unsupported --------------------------------------------------------
    {
        "id": "unsupported-hobbs-001",
        "split": "test",
        "category": "unsupported_opening",
        "intent": "ask_unsupported",
        "support": "unsupported",
        "position": "1. f4 g5",
        "fen": "rnbqkbnr/pppppp1p/8/6p1/5P2/8/PPPPP1PP/RNBQKBNR w KQkq - 0 2",
        "moves": ["f2f4", "g7g5"],
        "current_opening": "Bird Opening: Hobbs Gambit",
        "current_eco": "A02",
        "opening_node_id": "42fc892336340671947ae3c4226606e2c31a99ff05861d67fb3a2d8e45fa2a7b",
        "page_id": None,
        "question": "Que dois-je savoir sur le gambit Hobbs après 1.f4 g5 ?",
        "expected_context": _ctx([], [], ["fabricated opening facts", "prose from unrelated openings"]),
    },
    {
        "id": "unsupported-blackmar-002",
        "split": "dev",
        "category": "unsupported_opening",
        "intent": "ask_unsupported",
        "support": "unsupported",
        "position": "1. d4 d5 2. e4 dxe4 3. Nc3",
        "fen": "rnbqkbnr/ppp1pppp/8/8/3Pp3/2N5/PPP2PPP/R1BQKBNR w KQkq - 0 3",
        "moves": ["d2d4", "d7d5", "e2e4", "d5e4", "b1c3"],
        "current_opening": None,
        "current_eco": None,
        "opening_node_id": None,
        "page_id": None,
        "question": "Comment s'appelle cette ouverture et comment dois-je continuer ?",
        "expected_context": _ctx([], [], ["fabricated opening facts"]),
    },
    # --- out of theory ------------------------------------------------------
    {
        "id": "outoftheory-wayward-001",
        "split": "test",
        "category": "out_of_theory",
        "intent": "ask_out_of_theory",
        "support": "out_of_theory",
        "position": "1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7",
        "fen": "r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4",
        "moves": ["e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"],
        "current_opening": "King's Pawn Game: Wayward Queen Attack",
        "current_eco": None,
        "opening_node_id": None,
        "page_id": None,
        "question": "Est-ce que 4.Qxf7 est un bon coup pour moi ?",
        "expected_context": _ctx([], [], ["fabricated theory prose", "prose from unrelated openings"]),
    },
    {
        "id": "outoftheory-espagnole-002",
        "split": "dev",
        "category": "out_of_theory",
        "intent": "ask_out_of_theory",
        "support": "out_of_theory",
        "position": "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Bxc6 dxc6 5. Nxe5 Qd4",
        "fen": "r1b1kbnr/1pp2ppp/p1p5/4N3/3qP3/8/PPPP1PPP/RNBQK2R w KQkq - 1 6",
        "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5c6", "d7c6", "f3e5", "d8d4"],
        "current_opening": "Ruy Lopez: Morphy Defense",
        "current_eco": "C70",
        "opening_node_id": None,
        "page_id": None,
        "question": "Est-ce que 5...Qd4 est un bon coup pour moi ?",
        "expected_context": _ctx([], [], ["fabricated theory prose", "prose from unrelated openings"]),
    },
    # --- general principle ---------------------------------------------------
    {
        "id": "principle-developpement-001",
        "split": "test",
        "category": "general_principle",
        "intent": "general_principle",
        "support": "in_theory",
        "position": None,
        "fen": None,
        "moves": [],
        "current_opening": None,
        "current_eco": None,
        "opening_node_id": None,
        "page_id": _page("Chess Opening Theory"),
        "question": "Quels sont les principes généraux d'ouverture que je dois respecter ?",
        "expected_context": _ctx(
            ["Starting position"],
            [],
            ["specific opening prose", "History"],
        ),
    },
    {
        "id": "principle-contre-sicilienne-002",
        "split": "dev",
        "category": "general_principle",
        "intent": "general_principle",
        "support": "in_theory",
        "position": "1. e4 c5",
        "fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "moves": ["e2e4", "c7c5"],
        "current_opening": "Sicilian Defense",
        "current_eco": "B20",
        "opening_node_id": "875f0b1f41f1a385736f0ef39d6ccb8d2ba853f1c8f6b137f42a76145f748e82",
        "page_id": _page("Chess Opening Theory/1. e4/1...c5"),
        "question": "Comment jouer contre la sicilienne quand on est débutant ?",
        "expected_context": _ctx(
            ["1...c5 · Sicilian defence"],
            [],
            ["deep descendant prose", "History", "Bad moves"],
        ),
    },
]


def _test_split_sha256(cases: list[dict]) -> str:
    test_cases = sorted((c for c in cases if c["split"] == "test"), key=lambda c: c["id"])
    canonical = json.dumps(test_cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build() -> dict:
    counts_by_category: dict[str, dict[str, int]] = {}
    for case in CASES:
        counts_by_category.setdefault(case["category"], {"dev": 0, "test": 0})
        counts_by_category[case["category"]][case["split"]] += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "description": (
            "Production-shaped Eval V2 cases for the full Wikibooks corpus. Each case carries a "
            "position/opening, a user intent, and an expected_context that separates current prose "
            "from conditional child prose and forbidden pollution. The test split is frozen."
        ),
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "split_policy": "test split is frozen (see test_split_sha256); dev may be extended during retrieval tuning.",
        "intent_vocabulary": INTENT_VOCABULARY,
        "category_vocabulary": CATEGORY_VOCABULARY,
        "support_vocabulary": SUPPORT_VOCABULARY,
        "case_shape": {
            "id": "stable string id",
            "split": "dev | test",
            "category": "coverage category (see category_vocabulary)",
            "intent": "routed user intent (see intent_vocabulary)",
            "support": "in_theory | out_of_theory | unsupported",
            "position": "SAN movetext, or null",
            "fen": "FEN, or null",
            "moves": "UCI move list (may be empty)",
            "current_opening": "display name, or null",
            "current_eco": "ECO code, or null",
            "opening_node_id": "OpeningTree node id, or null",
            "page_id": "Wikibooks page id for current prose, or null",
            "question": "French natural-language question",
            "expected_context": {
                "current_prose": "section titles expected in the current-node page",
                "child_prose_allowed": "direct-child opening names allowed (conditional)",
                "forbidden": "content that must not be surfaced as the answer",
            },
        },
        "test_split_sha256": _test_split_sha256(CASES),
        "counts": {
            "total": len(CASES),
            "by_split": {
                "dev": sum(1 for c in CASES if c["split"] == "dev"),
                "test": sum(1 for c in CASES if c["split"] == "test"),
            },
            "by_category": counts_by_category,
        },
        "cases": CASES,
    }


def main() -> None:
    dataset = build()
    OUT.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT} ({dataset['counts']['total']} cases)")
    print(f"test split sha256: {dataset['test_split_sha256']}")


if __name__ == "__main__":
    main()
