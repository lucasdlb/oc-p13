from backend.app.core.settings import StockfishSettings
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
        "score": {"type": "cp", "value": 24},
        "depth": 12,
    }


def test_stockfish_service_reports_missing_binary() -> None:
    result = StockfishService(StockfishSettings(binary="/opt/missing-stockfish")).evaluate(
        "rnbqkbnr/pppppppp/8/5N2/8/8/PPPPPPPP/RNBQKB1R b KQkq - 1 1"
    )

    assert result == {"status": "unavailable", "reason": "binary_not_found"}
