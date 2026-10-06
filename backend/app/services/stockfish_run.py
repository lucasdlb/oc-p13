"""Idempotent Stockfish analysis for a persisted analysis run."""

import time
from typing import Any

from backend.app.core.settings import StockfishSettings
from backend.app.models.analysis import AnalysisSnapshot, RecommendedMove, StockfishRunResponse
from backend.app.services.cache_store import CacheStore, stockfish_cache_key
from backend.app.services.run_store import RunStore
from backend.app.services.stockfish import StockfishService, engine_version


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
            return _response(current.stockfish_result, current.stockfish_status, current.stockfish_fallbacks)

        facts = AnalysisSnapshot.model_validate(run.explorer_facts or {})
        recommended_moves = [RecommendedMove.model_validate(move) for move in facts.recommended_moves]
        cache_status = dict(facts.cache)
        fallbacks: list[str] = []
        try:
            result = _run_if_needed(
                stockfish_service,
                cache_store,
                run.fen,
                facts.source_confidence,
                recommended_moves,
                facts.opening.matched,
                cache_status,
                depth=self._settings.depth,
                binary=self._settings.binary,
            )
        except Exception:  # noqa: BLE001 - an unavailable engine is a safe fallback
            result = {"status": "unavailable"}

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
) -> dict | None:
    has_relevant_move = any(move.relevant for move in recommended_moves)
    if local_opening_matched and recommended_moves and not confidence["low_confidence"] and has_relevant_move:
        cache_status["stockfish"] = "skipped"
        return None
    if confidence["low_confidence"] or not has_relevant_move:
        key = stockfish_cache_key(fen, depth, engine_version(binary))
        if cache_store.available():
            cached = cache_store.get_stockfish(key)
            if isinstance(cached, dict) and cached.get("status") == "ok":
                cache_status["stockfish"] = "hit"
                return cached
        result = stockfish_service.evaluate(fen)
        cache_status["stockfish"] = "miss" if cache_store.available() else "skipped"
        if isinstance(result, dict) and result.get("status") == "ok" and cache_store.available():
            cache_store.set_stockfish(key, result)
        return result
    cache_status["stockfish"] = "skipped"
    return None
