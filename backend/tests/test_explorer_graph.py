from backend.app.models.analysis import AnalyzePositionRequest, AnalyzePositionResponse
from backend.app.orchestration.explorer_graph import (
    ExplorerGraphDependencies,
    run_explorer_graph,
)


def test_explorer_graph_delegates_once_to_analysis_service(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    request = AnalyzePositionRequest(
        fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        pgn="1. e4",
        moves=["e2e4"],
        level="debutant",
    )
    expected = AnalyzePositionResponse(
        opening={"eco": "B00", "name": "Test", "matched": True, "source": "test"},
        recommended_moves=[],
        masters_stats={"source": "test", "games": 0, "white": 0, "draws": 0, "black": 0},
        lichess_stats={},
        rag_context=[],
        coach_explanation="pending",
        stockfish=None,
        videos=[],
        fallbacks_used=[],
    )
    calls = 0

    def fake_analyze(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        assert args[0] == request
        return expected

    monkeypatch.setattr("backend.app.orchestration.explorer_graph.analyze_position", fake_analyze)

    dependencies = ExplorerGraphDependencies(
        lichess_client=object(),  # type: ignore[arg-type]
        stockfish_service=object(),  # type: ignore[arg-type]
        cache_store=object(),  # type: ignore[arg-type]
        session_store=object(),  # type: ignore[arg-type]
        opening_tree=None,
        intent_router=None,
        rag_service=None,
        coach_service=None,
        run_store=object(),  # type: ignore[arg-type]
    )

    assert run_explorer_graph(request, dependencies) == expected
    assert calls == 1
