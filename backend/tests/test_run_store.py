from backend.app.models.analysis import AnalysisRun
from backend.app.services.run_store import RunStore
from backend.tests.fakes import FakeDatabase


def make_run() -> AnalysisRun:
    return AnalysisRun(
        run_id="run-1",
        session_id="session-1",
        analysis_key="key-1",
        request_fingerprint="fingerprint-1",
        fen="8/8/8/8/8/8/8/4K3 w - - 0 1",
        pgn="Position initiale",
        moves=["e2e4"],
        level="debutant",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def test_run_store_creates_reads_and_finds_by_fingerprint() -> None:
    store = RunStore(FakeDatabase())
    run = make_run()

    created = store.create_run(run)

    assert created == run
    assert store.get_run("run-1") == run
    assert store.get_by_fingerprint("session-1", "fingerprint-1") == run


def test_run_store_updates_families_without_overwriting_other_facts() -> None:
    store = RunStore(FakeDatabase())
    store.create_run(make_run())

    assert store.save_explorer_facts("run-1", {"opening": {"name": "King's Pawn"}})
    assert store.claim_family("run-1", "stockfish")
    assert store.save_stockfish_result("run-1", {"status": "ok"}, "generated")
    assert store.claim_family("run-1", "rag")
    assert store.save_rag_context("run-1", [], {"state": "matched"}, [], "fallback", ["rag_unavailable"])

    updated = store.get_run("run-1")
    assert updated is not None
    assert updated.explorer_facts == {"opening": {"name": "King's Pawn"}}
    assert updated.stockfish_result == {"status": "ok"}
    assert updated.stockfish_status == "generated"
    assert updated.rag_status == "fallback"
    assert updated.rag_fallbacks == ["rag_unavailable"]


def test_run_store_claim_is_atomic_for_a_family() -> None:
    store = RunStore(FakeDatabase())
    store.create_run(make_run())

    assert store.claim_family("run-1", "coach") is True
    assert store.claim_family("run-1", "coach") is False


def test_run_store_names_fingerprint_index_for_existing_databases() -> None:
    database = FakeDatabase()

    RunStore(database)

    indexes = database.collections["analysis_runs"].indexes
    fingerprint_index = next(
        options for field, options in indexes if isinstance(field, list)
    )
    assert fingerprint_index["unique"] is True
    assert fingerprint_index["name"] == "analysis_runs_session_fingerprint_unique"
