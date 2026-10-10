"""Idempotent Stockfish analysis for a persisted analysis run."""

import time
import threading
from typing import Any

from backend.app.core.settings import StockfishSettings
from backend.app.models.analysis import AnalysisSnapshot, RecommendedMove, StockfishRunResponse
from backend.app.services.cache_store import CacheStore, stockfish_cache_key
from backend.app.services.run_store import RunStore
from backend.app.services.stockfish import StockfishService, engine_version


class _StockfishFlight:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: dict | None = None
        self.error: BaseException | None = None


_FLIGHTS: dict[str, _StockfishFlight] = {}
_FLIGHTS_LOCK = threading.Lock()


class StockfishRunService:
    """Coordinate claim, cache, evaluation and persistence for Stockfish."""

    def __init__(self, settings: StockfishSettings) -> None:
        self._settings = settings

    def analyze(
        self,
        run_id: str,
        run_store: RunStore,
        stockfish_service: StockfishService,
        cache_store: CacheStore,
    ) -> StockfishRunResponse:
        run = _require_run(run_store, run_id)
        if run.stockfish_status in {"generated", "fallback", "skipped"}:
            return _response(run.stockfish_result, run.stockfish_status, run.stockfish_fallbacks)

        if not run_store.claim_family(run_id, "stockfish"):
            current = _wait_for_stockfish(run_store, run_id) or _require_run(run_store, run_id)
            if current.stockfish_status == "running":
                # A worker may have disappeared after claiming the family. Do not
                # leave the UI in a permanent pending/running state.
                result = {"status": "unavailable", "reason": "stale_run", "depth": self._settings.depth_for_level(run.level)}
                fallbacks = ["stockfish_unavailable"]
                run_store.save_stockfish_result(run_id, result, "fallback", fallbacks)
                current = _require_run(run_store, run_id)
            return _response(current.stockfish_result, current.stockfish_status, current.stockfish_fallbacks)

        facts = AnalysisSnapshot.model_validate(run.explorer_facts or {})
        recommended_moves = [RecommendedMove.model_validate(move) for move in facts.recommended_moves]
        cache_status = dict(facts.cache)
        fallbacks: list[str] = []
        depth = self._settings.depth_for_level(run.level)
        try:
            requires_stockfish = (run.coach_context_artifact or {}).get("intent") == "compare_moves"
            result = _run_if_needed(
                stockfish_service,
                cache_store,
                run.fen,
                facts.source_confidence,
                recommended_moves,
                facts.opening.matched,
                cache_status,
                depth=depth,
                binary=self._settings.binary,
                force=requires_stockfish,
                multipv=3 if requires_stockfish else 1,
            )
        except Exception:  # noqa: BLE001 - an unavailable engine is a safe fallback
            result = {"status": "unavailable", "reason": "process_error", "depth": depth}

        if result is None:
            status = "skipped"
        elif result.get("status") == "ok":
            status = "generated"
        else:
            status = "fallback"
            fallbacks.append("stockfish_unavailable")
        run_store.save_stockfish_result(run_id, result, status, fallbacks)
        return _response(result, status, fallbacks)


def _response(result: dict[str, Any] | None, status: str, fallbacks: list[str]) -> StockfishRunResponse:
    return StockfishRunResponse(
        stockfish=result,
        stockfish_status=status,
        fallbacks_used=fallbacks,
    )


def _require_run(run_store: RunStore, run_id: str):  # type: ignore[no-untyped-def]
    run = run_store.get_run(run_id)
    if run is None:
        raise LookupError(run_id)
    return run


def _wait_for_stockfish(run_store: RunStore, run_id: str):  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        current = run_store.get_run(run_id)
        if current is None or current.stockfish_status != "running":
            return current
        if current.stockfish_status in {"generated", "fallback", "skipped"}:
            return current
        time.sleep(0.05)
    return run_store.get_run(run_id)


def _run_if_needed(
    stockfish_service: StockfishService,
    cache_store: CacheStore,
    fen: str,
    confidence: dict,
    recommended_moves: list[RecommendedMove],
    local_opening_matched: bool,
    cache_status: dict,
    depth: int,
    binary: str,
    force: bool = False,
    multipv: int = 1,
) -> dict | None:
    key = stockfish_cache_key(fen, depth, engine_version(binary), multipv)
    if cache_store.available():
        cached = cache_store.get_stockfish(key)
        if isinstance(cached, dict) and cached.get("status") == "ok":
            cache_status["stockfish"] = "hit"
            return cached

    with _FLIGHTS_LOCK:
        flight = _FLIGHTS.get(key)
        owner = flight is None
        if owner:
            flight = _StockfishFlight()
            _FLIGHTS[key] = flight

    if not owner:
        flight.done.wait()
        if flight.error is not None:
            raise flight.error
        cache_status["stockfish"] = "shared"
        return flight.result

    try:
        result = stockfish_service.evaluate(fen, multipv=multipv, depth=depth)
        cache_status["stockfish"] = "miss" if cache_store.available() else "skipped"
        if isinstance(result, dict) and result.get("status") == "ok" and cache_store.available():
            cache_store.set_stockfish(key, result)
        flight.result = result
        return result
    except BaseException as exc:
        flight.error = exc
        raise
    finally:
        flight.done.set()
        with _FLIGHTS_LOCK:
            if _FLIGHTS.get(key) is flight:
                del _FLIGHTS[key]
