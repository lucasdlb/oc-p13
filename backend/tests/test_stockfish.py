import threading

from backend.app.core.settings import StockfishSettings
from backend.app.models.analysis import RecommendedMove
from backend.app.services.stockfish_run import _run_if_needed
from backend.app.services.stockfish import StockfishService


def test_stockfish_service_parses_uci_evaluation(tmp_path) -> None:
    engine = tmp_path / "stockfish"
    engine.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "for line in sys.stdin:\n"
        "    if line.startswith('go '):\n"
        "        print('info depth 12 score cp 24', flush=True)\n"
        "        print('bestmove g1f3', flush=True)\n"
        "        break\n"
    )
    engine.chmod(0o755)

    result = StockfishService(StockfishSettings(binary=str(engine))).evaluate(
        "rnbqkbnr/pppppppp/8/5N2/8/8/PPPPPPPP/RNBQKB1R b KQkq - 1 1"
    )

    assert result == {
        "status": "ok",
        "best_move": "g1f3",
        "score": {"type": "cp", "value": -24},
        "depth": 12,
        "pv": ("g1f3",),
        "multipv": 1,
        "variations": [],
    }


def test_stockfish_service_reports_missing_binary() -> None:
    result = StockfishService(StockfishSettings(binary="/opt/missing-stockfish")).evaluate(
        "rnbqkbnr/pppppppp/8/5N2/8/8/PPPPPPPP/RNBQKB1R b KQkq - 1 1"
    )

    assert result == {"status": "unavailable", "reason": "binary_not_found", "depth": 12}


def test_stockfish_service_parses_multipv_and_normalizes_black_scores(tmp_path) -> None:
    engine = tmp_path / "stockfish-multipv"
    engine.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "for line in sys.stdin:\n"
        "    if line.startswith('go '):\n"
        "        print('info depth 12 multipv 1 score cp 30 pv e7e5 g1f3', flush=True)\n"
        "        print('info depth 12 multipv 2 score cp -10 pv d7d5', flush=True)\n"
        "        print('bestmove e7e5', flush=True)\n"
        "        break\n"
    )
    engine.chmod(0o755)

    result = StockfishService(StockfishSettings(binary=str(engine))).evaluate(
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        multipv=3,
    )

    assert result["score"] == {"type": "cp", "value": -30}
    assert result["pv"] == ("e7e5", "g1f3")
    assert result["multipv"] == 3
    assert result["variations"][1]["score"] == {"type": "cp", "value": 10}


def test_compare_moves_forces_multipv_even_with_confident_opening_data() -> None:
    class FakeStockfish:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def evaluate(self, _fen: str, *, multipv: int = 1, depth: int | None = None) -> dict:
            self.calls.append(multipv)
            return {"status": "ok", "multipv": multipv}

    class UnavailableCache:
        def available(self) -> bool:
            return False

    service = FakeStockfish()
    result = _run_if_needed(
        service,
        UnavailableCache(),
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        {"low_confidence": False},
        [RecommendedMove(uci="e2e4", san="e4", description="", source="test", relevant=True)],
        True,
        {},
        depth=12,
        binary="stockfish",
        force=True,
        multipv=3,
    )

    assert result == {"status": "ok", "multipv": 3}
    assert service.calls == [3]


def test_stockfish_runs_for_confident_theoretical_positions() -> None:
    class FakeStockfish:
        def __init__(self) -> None:
            self.calls = 0

        def evaluate(self, _fen: str, *, multipv: int = 1, depth: int | None = None) -> dict:
            self.calls += 1
            return {"status": "ok", "multipv": multipv, "depth": depth}

    class UnavailableCache:
        def available(self) -> bool:
            return False

    service = FakeStockfish()
    result = _run_if_needed(
        service,
        UnavailableCache(),
        "rnbqkbnr/pppppppp/8/5N2/8/8/PPPPPPPP/RNBQKB1R b KQkq - 1 1",
        {"low_confidence": False},
        [RecommendedMove(uci="g8f6", san="Nf6", description="", source="test", relevant=True)],
        True,
        {},
        depth=12,
        binary="stockfish",
    )

    assert result == {"status": "ok", "multipv": 1, "depth": 12}
    assert service.calls == 1


def test_stockfish_runs_when_theoretical_data_has_low_confidence() -> None:
    class FakeStockfish:
        def __init__(self) -> None:
            self.calls = 0

        def evaluate(self, _fen: str, *, multipv: int = 1, depth: int | None = None) -> dict:
            self.calls += 1
            return {"status": "ok", "multipv": multipv, "depth": depth}

    class UnavailableCache:
        def available(self) -> bool:
            return False

    service = FakeStockfish()
    result = _run_if_needed(
        service,
        UnavailableCache(),
        "rnbqkbnr/pppppppp/8/5N2/8/8/PPPPPPPP/RNBQKB1R b KQkq - 1 1",
        {"low_confidence": True},
        [RecommendedMove(uci="g8f6", san="Nf6", description="", source="test", relevant=True)],
        True,
        {},
        depth=12,
        binary="stockfish",
    )

    assert result == {"status": "ok", "multipv": 1, "depth": 12}
    assert service.calls == 1


def test_concurrent_requests_for_same_engine_key_share_one_evaluation() -> None:
    class BlockingStockfish:
        def __init__(self) -> None:
            self.calls = 0
            self.started = threading.Event()
            self.release = threading.Event()

        def evaluate(self, _fen: str, *, multipv: int = 1, depth: int | None = None) -> dict:
            self.calls += 1
            self.started.set()
            self.release.wait(timeout=2)
            return {"status": "ok", "multipv": multipv, "depth": depth}

    class UnavailableCache:
        def available(self) -> bool:
            return False

    service = BlockingStockfish()
    cache = UnavailableCache()
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    results: list[dict | None] = []

    def run() -> None:
        results.append(
            _run_if_needed(
                service,
                cache,
                fen,
                {},
                [],
                True,
                {},
                depth=12,
                binary="stockfish",
            )
        )

    first = threading.Thread(target=run)
    second = threading.Thread(target=run)
    first.start()
    assert service.started.wait(timeout=2)
    second.start()
    service.release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert service.calls == 1
    assert results == [
        {"status": "ok", "multipv": 1, "depth": 12},
        {"status": "ok", "multipv": 1, "depth": 12},
    ]
