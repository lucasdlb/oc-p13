from backend.app.services.session_store import (
    SessionStore,
    build_move_docs,
    format_pgn,
)
from backend.tests.fakes import FakeDatabase


KINGS_PAWN_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"


def make_store() -> tuple[SessionStore, FakeDatabase]:
    database = FakeDatabase()
    return SessionStore(database=database), database


def test_create_session_returns_empty_active_session() -> None:
    store, _ = make_store()

    session = store.create_session()

    assert session is not None
    assert session["status"] == "active"
    assert session["ended_at"] is None
    assert session["moves"] == []
    assert session["analyses"] == []
    assert session["started_at"]
    assert store.get_session(session["id"]) == session


def test_get_session_returns_none_for_unknown_or_invalid_id() -> None:
    store, _ = make_store()

    assert store.get_session("000000000000000000000099") is None
    assert store.get_session("not-an-object-id") is None


def test_set_moves_overwrites_and_truncates_the_line() -> None:
    store, _ = make_store()
    session = store.create_session()

    assert store.set_moves(session["id"], build_move_docs(["e2e4", "e7e5"])) is True

    updated = store.get_session(session["id"])
    assert [move["uci"] for move in updated["moves"]] == ["e2e4", "e7e5"]

    assert store.set_moves(session["id"], build_move_docs(["e2e4", "d7d5"])) is True

    branched = store.get_session(session["id"])
    assert [move["uci"] for move in branched["moves"]] == ["e2e4", "d7d5"]


def test_append_move_extends_the_line() -> None:
    store, _ = make_store()
    session = store.create_session()

    store.append_move(
        session["id"],
        {"ply": 1, "uci": "e2e4", "san": "e4", "fen": KINGS_PAWN_FEN, "pgn": "1. e4", "created_at": "now"},
    )

    updated = store.get_session(session["id"])
    assert len(updated["moves"]) == 1
    assert updated["moves"][0]["san"] == "e4"


def test_save_analysis_replaces_the_same_position_key() -> None:
    store, _ = make_store()
    session = store.create_session()

    store.save_analysis(session["id"], "key-1", KINGS_PAWN_FEN, {"coach": "first"})
    store.save_analysis(session["id"], "key-1", KINGS_PAWN_FEN, {"coach": "second"})
    store.save_analysis(session["id"], "key-2", KINGS_PAWN_FEN, {"coach": "other"})

    analyses = store.get_session(session["id"])["analyses"]
    assert len(analyses) == 2
    by_key = {analysis["position_key"]: analysis for analysis in analyses}
    assert by_key["key-1"]["response"] == {"coach": "second"}
    assert by_key["key-2"]["response"] == {"coach": "other"}


def test_end_session_marks_the_session_ended() -> None:
    store, _ = make_store()
    session = store.create_session()

    assert store.end_session(session["id"]) is True

    ended = store.get_session(session["id"])
    assert ended["status"] == "ended"
    assert ended["ended_at"] is not None


def test_degraded_store_never_raises_and_reports_unavailable() -> None:
    store = SessionStore(database=None)

    assert store.available() is False
    assert store.create_session() is None
    assert store.get_session("000000000000000000000001") is None
    assert store.set_moves("000000000000000000000001", []) is False
    assert store.append_move("000000000000000000000001", {}) is False
    assert store.save_analysis("000000000000000000000001", "k", "fen", {}) is False
    assert store.end_session("000000000000000000000001") is False


def test_build_move_docs_replays_the_line_with_san_fen_and_pgn() -> None:
    documents = build_move_docs(["e2e4", "e7e5"])

    assert documents is not None
    assert len(documents) == 2
    assert documents[0]["ply"] == 1
    assert documents[0]["san"] == "e4"
    assert documents[0]["pgn"] == "1. e4"
    assert documents[0]["fen"] == KINGS_PAWN_FEN
    assert documents[1]["ply"] == 2
    assert documents[1]["san"] == "e5"
    assert documents[1]["pgn"] == "1. e4 e5"


def test_build_move_docs_returns_none_for_an_illegal_line() -> None:
    assert build_move_docs(["e2e4", "e2e5"]) is None
    assert build_move_docs(["not-a-move"]) is None


def test_format_pgn_pairs_moves_into_numbered_plys() -> None:
    assert format_pgn([]) == ""
    assert format_pgn(["e4"]) == "1. e4"
    assert format_pgn(["e4", "e5", "Nf3"]) == "1. e4 e5 2. Nf3"
