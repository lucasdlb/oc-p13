import hashlib
import json
import threading
import time
from dataclasses import replace
from urllib.parse import quote_plus

import chess
from pydantic import ValidationError

from backend.app.core.settings import RecommendationSettings, get_settings
from backend.app.models.analysis import (
    AnalysisSnapshot,
    AnalyzePositionRequest,
    AnalyzePositionResponse,
    AnalysisRun,
    CoachExplanationResponse,
    LichessStats,
    Opening,
    RagContextResponse,
    RagContext,
    RecommendedMove,
    StockfishRunResponse,
    Video,
)
from backend.app.services.cache_store import (
    CacheStore,
    lichess_cache_key,
    masters_cache_key,
    stockfish_cache_key,
)
from backend.app.services.coach import CoachFallbackError, CoachService, ConservativeCoachService
from backend.app.services.lichess import (
    LICHESS_SOURCE,
    LichessExplorerClient,
    LichessExplorerResult,
)
from backend.app.services.opening_book import DEMO_OPENING_SOURCE, match_opening
from backend.app.services.intent_router import CandidateMove, IntentRouter, IntentRouterContext, RouterSource
from backend.app.services.opening_tree import OpeningTree
from backend.app.services.rag import RagService
from backend.app.services.retrieval_contracts import (
    CoachContext,
    OpeningTreeContext,
    RetrievedContext,
    build_coach_context,
)
from backend.app.services.retrieval_plan_builder import build_retrieval_plan
from backend.app.services.run_store import RunStore, new_run_id, now_iso as run_now_iso
from backend.app.services.session_store import SessionStore, build_move_docs
from backend.app.services.stockfish import StockfishService, engine_version


RATING_BUCKETS = (0, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2500)

PENDING_COACH_TEXT = (
    "Le coach detaille est en cours de redaction. "
    "Les donnees de l'explorateur sont deja disponibles ci-contre."
)

_EXPLORER_LOCK = threading.Lock()


class AnalysisRunNotFoundError(LookupError):
    """Raised when a progressive endpoint receives an unknown run id."""


def build_explorer_snapshot(
    request: AnalyzePositionRequest,
    lichess_client: LichessExplorerClient,
    cache_store: CacheStore,
    **_unused: object,
) -> AnalysisSnapshot:
    """Produce the fast Explorer facts for a position.

    This function intentionally never calls RAG, Stockfish, or the LLM. The
    returned artifact is the only source family needed by the first response.
    """
    settings = get_settings().recommendations
    local_match = match_opening(request.moves, request.fen)
    ratings = _rating_buckets(request, settings)

    cache_status = {"lichess": "skipped", "masters": "skipped", "stockfish": "skipped"}

    lichess_result = _fetch_lichess_cached(
        cache_store,
        lichess_client,
        request.moves,
        ratings,
        settings.default_moves,
        cache_status,
    )
    masters_result = _fetch_masters_cached(
        cache_store,
        lichess_client,
        request.moves,
        settings.default_moves,
        cache_status,
    )

    fallbacks_used: list[str] = []

    if lichess_result.opening is not None:
        opening = lichess_result.opening
    elif local_match.matched:
        opening = local_match.opening
        fallbacks_used.append("demo_opening_seed")
    else:
        opening = local_match.opening
        fallbacks_used.append("opening_not_matched")

    confidence = _source_confidence(lichess_result.stats.games, settings)

    if lichess_result.recommended_moves:
        recommended_moves = _rank_moves(
            lichess_result.recommended_moves,
            total_games=lichess_result.stats.games,
            fen=request.fen,
            settings=settings,
        )
    else:
        recommended_moves = list(local_match.recommended_moves)

    if lichess_result.fallback:
        fallbacks_used.append(lichess_result.fallback)

    if masters_result.fallback:
        fallbacks_used.append(masters_result.fallback)

    fallbacks_used.append("youtube_search_fallback")

    query = quote_plus(f"{opening.name} chess opening {request.level}")
    videos = [
        Video(
            title=f"Recherche YouTube: {opening.name} {request.level}",
            url=f"https://www.youtube.com/results?search_query={query}",
            source="youtube-search-fallback",
        )
    ]

    return AnalysisSnapshot(
        opening=opening,
        recommended_moves=recommended_moves,
        masters_moves=_rank_moves(
            masters_result.recommended_moves,
            total_games=masters_result.stats.games,
            fen=request.fen,
            settings=settings,
        ),
        masters_stats=masters_result.stats,
        lichess_stats=lichess_result.stats,
        source_confidence=confidence,
        rag_context=[],
        stockfish=None,
        videos=videos,
        fallbacks_used=fallbacks_used,
        cache=cache_status,
        coach_context={},
    )


def build_analysis_snapshot(
    request: AnalyzePositionRequest,
    lichess_client: LichessExplorerClient,
    stockfish_service: StockfishService,
    cache_store: CacheStore,
    opening_tree: OpeningTree | None = None,
    intent_router: IntentRouter | None = None,
    rag_service: RagService | None = None,
) -> AnalysisSnapshot:
    """Compatibility wrapper for callers migrating to the Explorer seam."""
    return build_explorer_snapshot(
        request,
        lichess_client,
        cache_store,
        stockfish_service=stockfish_service,
        opening_tree=opening_tree,
        intent_router=intent_router,
        rag_service=rag_service,
    )


def analyze_position(
    request: AnalyzePositionRequest,
    lichess_client: LichessExplorerClient,
    stockfish_service: StockfishService,
    cache_store: CacheStore,
    session_store: SessionStore,
    opening_tree: OpeningTree | None = None,
    intent_router: IntentRouter | None = None,
    rag_service: RagService | None = None,
    coach_service: CoachService | None = None,
    run_store: RunStore | None = None,
) -> AnalyzePositionResponse:
    """Return Explorer facts immediately and persist a progressive run."""
    all_settings = get_settings()
    settings = all_settings.recommendations
    ratings = _rating_buckets(request, settings)
    position_key = _position_key(request.fen, request.level, ratings)
    fingerprint = request_fingerprint(request)
    with _EXPLORER_LOCK:
        session_fallbacks: list[str] = []
        session_id = _sync_session(session_store, request, session_fallbacks)
        run = run_store.get_by_fingerprint(session_id, fingerprint) if run_store else None

        if run is None and run_store and run_store.available():
            run = run_store.create_run(
                AnalysisRun(
                    run_id=new_run_id(),
                    session_id=session_id,
                    analysis_key=position_key,
                    request_fingerprint=fingerprint,
                    fen=request.fen,
                    pgn=request.pgn,
                    moves=list(request.moves),
                    level=request.level,
                    question=request.question,
                    rating_min=request.rating_min,
                    rating_max=request.rating_max,
                    created_at=run_now_iso(),
                    updated_at=run_now_iso(),
                )
            )

        if run is not None and run.explorer_facts:
            snapshot = AnalysisSnapshot.model_validate(run.explorer_facts)
            if session_id:
                session_store.save_analysis_snapshot(
                    session_id,
                    position_key,
                    request.fen,
                    {**snapshot.model_dump(), "run_id": run.run_id},
                )
            return _explorer_response(snapshot, run.run_id, run, analysis_key=position_key)

        if run is not None and run_store and not run_store.claim_family(run.run_id, "explorer"):
            run = _wait_for_explorer(run_store, run.run_id)
            if run is not None and run.explorer_facts:
                snapshot = AnalysisSnapshot.model_validate(run.explorer_facts)
                if session_id:
                    session_store.save_analysis_snapshot(
                        session_id,
                        position_key,
                        request.fen,
                        {**snapshot.model_dump(), "run_id": run.run_id},
                    )
                return _explorer_response(snapshot, run.run_id, run, analysis_key=position_key)

    snapshot = build_explorer_snapshot(
        request,
        lichess_client,
        cache_store,
        stockfish_service=stockfish_service,
        opening_tree=opening_tree,
        intent_router=intent_router,
        rag_service=rag_service,
    )
    fallbacks_used = [*session_fallbacks, *snapshot.fallbacks_used]
    if fallbacks_used != snapshot.fallbacks_used:
        snapshot = snapshot.model_copy(update={"fallbacks_used": fallbacks_used})

    run_id: str | None = run.run_id if run is not None else None
    if run_store and run is not None and run_store.available():
        run_store.save_explorer_facts(run.run_id, snapshot.model_dump())
        run = run_store.get_run(run.run_id) or run

    if session_id:
        session_store.save_analysis_snapshot(
            session_id,
            position_key,
            request.fen,
            {**snapshot.model_dump(), "run_id": run_id},
        )

    return _explorer_response(
        snapshot,
        run_id,
        run,
        analysis_key=position_key,
        session_id=session_id,
    )


def request_fingerprint(request: AnalyzePositionRequest) -> str:
    payload = request.model_dump(exclude={"session_id"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _explorer_response(
    snapshot: AnalysisSnapshot,
    run_id: str | None,
    run: object | None,
    *,
    analysis_key: str,
    session_id: str | None = None,
) -> AnalyzePositionResponse:
    statuses = {
        "explorer_status": getattr(run, "explorer_status", "generated"),
        "stockfish_status": getattr(run, "stockfish_status", "pending"),
        "rag_status": getattr(run, "rag_status", "pending"),
        "coach_status": getattr(run, "coach_status", "pending"),
    }
    coach_result = getattr(run, "coach_result", None)
    stored_rag_context = getattr(run, "rag_context", None)
    stored_stockfish = getattr(run, "stockfish_result", None)
    stored_fallbacks = [
        *getattr(run, "stockfish_fallbacks", []),
        *getattr(run, "rag_fallbacks", []),
    ]
    rag_context = (
        [RagContext.model_validate(context) for context in stored_rag_context]
        if stored_rag_context
        else snapshot.rag_context
    )
    coach_explanation = (
        coach_result.get("explanation", PENDING_COACH_TEXT)
        if isinstance(coach_result, dict)
        else PENDING_COACH_TEXT
    )
    return AnalyzePositionResponse(
        opening=snapshot.opening,
        recommended_moves=snapshot.recommended_moves,
        masters_moves=snapshot.masters_moves,
        masters_stats=snapshot.masters_stats,
        lichess_stats=snapshot.lichess_stats,
        source_confidence=snapshot.source_confidence,
        rag_context=rag_context,
        coach_explanation=coach_explanation,
        coach_status=statuses["coach_status"],
        analysis_key=getattr(run, "analysis_key", analysis_key) or analysis_key,
        stockfish=stored_stockfish,
        videos=snapshot.videos,
        fallbacks_used=list(dict.fromkeys([*snapshot.fallbacks_used, *stored_fallbacks])),
        session_id=getattr(run, "session_id", session_id) or session_id,
        cache=snapshot.cache,
        run_id=run_id,
        explorer_status=statuses["explorer_status"],
        stockfish_status=statuses["stockfish_status"],
        rag_status=statuses["rag_status"],
    )


def render_coach_explanation(
    session_id: str,
    analysis_key: str,
    level: str,
    coach_service: CoachService,
    session_store: SessionStore,
) -> CoachExplanationResponse:
    """Render the coach explanation from a stored snapshot.

    This endpoint does not call Lichess, Stockfish or Milvus. It reads the
    previously stored facts and asks the LLM to synthesize the explanation.
    The result is cached in the session so repeated calls are instant.
    """
    record = session_store.get_analysis_record(session_id, analysis_key)
    if record is None:
        raise ValueError(f"Analysis record not found for key {analysis_key}")

    existing_status = record.get("coach_status")
    existing_explanation = record.get("coach_explanation")
    if existing_status in ("generated", "fallback") and existing_explanation:
        return CoachExplanationResponse(
            explanation=existing_explanation,
            coach_status=existing_status,
            fallbacks_used=list(record.get("coach_fallbacks", [])),
        )

    facts = record.get("facts", {})
    coach_context = CoachContext.from_artifact(facts.get("coach_context", {}))

    explanation, status, fallbacks = _render_coach(
        coach_context,
        level,
        coach_service,
    )

    session_store.save_coach_explanation(
        session_id,
        analysis_key,
        explanation,
        status,
        fallbacks,
    )

    return CoachExplanationResponse(
        explanation=explanation,
        coach_status=status,
        fallbacks_used=fallbacks,
    )


def _render_coach(
    coach_context: CoachContext,
    level: str,
    coach_service: CoachService | None,
) -> tuple[str, str, list[str]]:
    """Render coach text and return (explanation, status, extra_fallbacks)."""
    try:
        text = (coach_service or ConservativeCoachService()).explain(coach_context, level=level)
    except CoachFallbackError as exc:
        return exc.text, "fallback", [exc.fallback_label]
    return text, "generated", []


def analyze_stockfish_run(
    run_id: str,
    run_store: RunStore,
    stockfish_service: StockfishService,
    cache_store: CacheStore,
) -> StockfishRunResponse:
    run = _require_run(run_store, run_id)
    if run.stockfish_status in {"generated", "fallback", "skipped"}:
        return StockfishRunResponse(
            stockfish=run.stockfish_result,
            stockfish_status=run.stockfish_status,
            fallbacks_used=run.stockfish_fallbacks,
        )

    if not run_store.claim_family(run_id, "stockfish"):
        current = _wait_for_family(run_store, run_id, "stockfish") or _require_run(run_store, run_id)
        return StockfishRunResponse(
            stockfish=current.stockfish_result,
            stockfish_status=current.stockfish_status,
            fallbacks_used=current.stockfish_fallbacks,
        )

    facts = AnalysisSnapshot.model_validate(run.explorer_facts or {})
    recommended_moves = [RecommendedMove.model_validate(move) for move in facts.recommended_moves]
    cache_status = dict(facts.cache)
    settings = get_settings()
    fallbacks: list[str] = []
    try:
        result = _run_stockfish_if_needed(
            stockfish_service,
            cache_store,
            run.fen,
            facts.source_confidence,
            recommended_moves,
            facts.opening.matched,
            cache_status,
            depth=settings.stockfish.depth,
            binary=settings.stockfish.binary,
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
    return StockfishRunResponse(
        stockfish=result,
        stockfish_status=status,
        fallbacks_used=fallbacks,
    )


def retrieve_rag_for_run(
    run_id: str,
    run_store: RunStore,
    opening_tree: OpeningTree | None,
    intent_router: IntentRouter | None,
    rag_service: RagService | None,
) -> RagContextResponse:
    run = _require_run(run_store, run_id)
    if run.rag_status in {"generated", "fallback", "skipped"}:
        return RagContextResponse(
            rag_context=[RagContext.model_validate(context) for context in run.rag_context],
            rag_status=run.rag_status,
            fallbacks_used=run.rag_fallbacks,
        )

    if not run_store.claim_family(run_id, "rag"):
        current = _wait_for_family(run_store, run_id, "rag") or _require_run(run_store, run_id)
        return RagContextResponse(
            rag_context=[RagContext.model_validate(context) for context in current.rag_context],
            rag_status=current.rag_status,
            fallbacks_used=current.rag_fallbacks,
        )

    facts = AnalysisSnapshot.model_validate(run.explorer_facts or {})
    request = AnalyzePositionRequest(
        fen=run.fen,
        pgn=run.pgn,
        moves=run.moves,
        level=run.level,
        question=run.question,
        rating_min=run.rating_min,
        rating_max=run.rating_max,
    )
    local_match = match_opening(run.moves, run.fen)
    fallback_text = (
        _lichess_context(facts.opening)
        if facts.opening.source == LICHESS_SOURCE
        else local_match.context
    )
    fallbacks: list[str] = []
    if opening_tree is None or intent_router is None or rag_service is None:
        rag_context = [_fallback_rag_context(facts.opening, fallback_text)]
        tree_context = _fallback_tree_context(facts.opening)
        retrieved_contexts: tuple[RetrievedContext, ...] = ()
        fallbacks.append("rag_unavailable")
    else:
        rag_context, fallbacks, tree_context, retrieved_contexts = _retrieve_rag_context(
            request,
            facts.opening,
            fallback_text,
            opening_tree,
            intent_router,
            rag_service,
        )

    lichess_stats = facts.lichess_stats.model_dump() if isinstance(facts.lichess_stats, LichessStats) else facts.lichess_stats
    coach_context = build_coach_context(
        tree_context=tree_context,
        question=request.question,
        retrieved_contexts=retrieved_contexts,
        lichess_stats=lichess_stats,
        recommended_moves=[move.model_dump() for move in facts.recommended_moves],
        stockfish=None,
        fallbacks=tuple([*facts.fallbacks_used, *fallbacks]),
    )
    status = "generated" if retrieved_contexts and not fallbacks else "fallback"
    run_store.save_rag_context(
        run_id,
        [context.model_dump() for context in rag_context],
        tree_context.to_artifact(),
        [context.to_artifact() for context in retrieved_contexts],
        status,
        fallbacks,
        coach_context.to_artifact(),
    )
    return RagContextResponse(
        rag_context=rag_context,
        rag_status=status,
        fallbacks_used=fallbacks,
    )


def render_run_coach(
    run_id: str,
    level: str,
    coach_service: CoachService,
    run_store: RunStore,
) -> CoachExplanationResponse:
    run = _require_run(run_store, run_id)
    if run.coach_status in {"generated", "fallback"} and run.coach_result:
        return CoachExplanationResponse(
            explanation=run.coach_result.get("explanation", PENDING_COACH_TEXT),
            coach_status=run.coach_status,
            fallbacks_used=list(run.coach_result.get("fallbacks_used", [])),
        )

    if not run_store.claim_family(run_id, "coach"):
        current = _wait_for_family(run_store, run_id, "coach") or _require_run(run_store, run_id)
        result = current.coach_result or {}
        return CoachExplanationResponse(
            explanation=result.get("explanation", PENDING_COACH_TEXT),
            coach_status=current.coach_status,
            fallbacks_used=list(result.get("fallbacks_used", [])),
        )

    context = coach_context_for_run(run)
    explanation, status, fallbacks = _render_coach(context, level, coach_service)
    run_store.save_coach_result(run_id, explanation, status, fallbacks)
    return CoachExplanationResponse(
        explanation=explanation,
        coach_status=status,
        fallbacks_used=fallbacks,
    )


def coach_context_for_run(run: AnalysisRun) -> CoachContext:
    """Build a coach context entirely from persisted run artifacts."""
    context = _coach_context_for_run(run)
    return replace(
        context,
        question=run.question,
        stockfish=run.stockfish_result,
        fallbacks=tuple(
            [
                *(context.fallbacks or ()),
                *run.stockfish_fallbacks,
                *run.rag_fallbacks,
            ]
        ),
    )


def _coach_context_for_run(run: AnalysisRun) -> CoachContext:
    if run.coach_context_artifact:
        return CoachContext.from_artifact(run.coach_context_artifact)
    facts = AnalysisSnapshot.model_validate(run.explorer_facts or {})
    tree_context = _fallback_tree_context(facts.opening)
    lichess_stats = facts.lichess_stats.model_dump() if isinstance(facts.lichess_stats, LichessStats) else facts.lichess_stats
    return build_coach_context(
        tree_context=tree_context,
        question=run.question,
        lichess_stats=lichess_stats,
        recommended_moves=[move.model_dump() for move in facts.recommended_moves],
        stockfish=run.stockfish_result,
        fallbacks=tuple([*facts.fallbacks_used, *run.rag_fallbacks, *run.stockfish_fallbacks]),
    )


def _require_run(run_store: RunStore, run_id: str) -> AnalysisRun:
    run = run_store.get_run(run_id)
    if run is None:
        raise AnalysisRunNotFoundError(run_id)
    return run


def _wait_for_explorer(run_store: RunStore, run_id: str) -> AnalysisRun | None:
    return _wait_for_family(run_store, run_id, "explorer")


def _wait_for_family(
    run_store: RunStore,
    run_id: str,
    family: str,
) -> AnalysisRun | None:
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        current = run_store.get_run(run_id)
        if current is None or getattr(current, f"{family}_status") != "running":
            return current
        if family == "explorer" and current.explorer_facts:
            return current
        if family == "stockfish" and current.stockfish_status in {"generated", "fallback", "skipped"}:
            return current
        if family == "rag" and current.rag_status in {"generated", "fallback", "skipped"}:
            return current
        if family == "coach" and current.coach_status in {"generated", "fallback"}:
            return current
        time.sleep(0.05)
    return run_store.get_run(run_id)


def _rating_buckets(
    request: AnalyzePositionRequest,
    settings: RecommendationSettings,
) -> list[int]:
    preset = settings.rating_presets.get(request.level)
    minimum = request.rating_min if request.rating_min is not None else preset.min if preset else 0
    maximum = request.rating_max if request.rating_max is not None else preset.max if preset else 2500
    if minimum > maximum:
        minimum, maximum = maximum, minimum
    if minimum == maximum:
        return [minimum] if minimum in RATING_BUCKETS else []
    return [bucket for bucket in RATING_BUCKETS if minimum <= bucket < maximum]


def _fetch_lichess(
    lichess_client: LichessExplorerClient,
    moves: list[str],
    ratings: list[int],
    move_count: int,
):
    try:
        return lichess_client.fetch_explorer_analysis(
            moves,
            ratings=ratings,
            move_count=move_count,
        )
    except TypeError:
        return lichess_client.fetch_explorer_analysis(moves)


def _fetch_masters(
    lichess_client: LichessExplorerClient,
    moves: list[str],
    move_count: int,
):
    fetch_masters = getattr(lichess_client, "fetch_masters_analysis", None)
    if fetch_masters is None:
        return LichessExplorerResult(
            stats=LichessStats(source="masters-opening-explorer", games=0, white=0, draws=0, black=0),
            fallback="masters_unavailable",
        )
    try:
        return fetch_masters(moves, move_count=move_count)
    except TypeError:
        return fetch_masters(moves)


def _fetch_lichess_cached(
    cache_store: CacheStore,
    lichess_client: LichessExplorerClient,
    moves: list[str],
    ratings: list[int],
    move_count: int,
    cache_status: dict,
):
    key = lichess_cache_key(moves, ratings)
    if cache_store.available():
        cached = _lichess_result_from_payload(cache_store.get_lichess(key))
        if cached is not None:
            cache_status["lichess"] = "hit"
            return cached

    result = _fetch_lichess(lichess_client, moves, ratings, move_count)
    cache_status["lichess"] = "miss" if cache_store.available() else "skipped"
    if result.fallback is None and cache_store.available():
        cache_store.set_lichess(key, _lichess_result_to_payload(result))
    return result


def _fetch_masters_cached(
    cache_store: CacheStore,
    lichess_client: LichessExplorerClient,
    moves: list[str],
    move_count: int,
    cache_status: dict,
):
    key = masters_cache_key(moves)
    if cache_store.available():
        cached = _lichess_result_from_payload(cache_store.get_masters(key))
        if cached is not None:
            cache_status["masters"] = "hit"
            return cached

    result = _fetch_masters(lichess_client, moves, move_count)
    cache_status["masters"] = "miss" if cache_store.available() else "skipped"
    if result.fallback is None and cache_store.available():
        cache_store.set_masters(key, _lichess_result_to_payload(result))
    return result


def _lichess_result_to_payload(result: LichessExplorerResult) -> dict:
    return {
        "stats": result.stats.model_dump(),
        "opening": result.opening.model_dump() if result.opening else None,
        "recommended_moves": [move.model_dump() for move in result.recommended_moves],
    }


def _lichess_result_from_payload(payload: dict) -> LichessExplorerResult | None:
    if not isinstance(payload, dict):
        return None
    try:
        return LichessExplorerResult(
            stats=LichessStats.model_validate(payload["stats"]),
            opening=Opening.model_validate(payload["opening"]) if payload.get("opening") else None,
            recommended_moves=tuple(
                RecommendedMove.model_validate(move)
                for move in payload.get("recommended_moves", [])
            ),
        )
    except (KeyError, TypeError, ValueError, ValidationError):
        return None


def _sync_session(
    session_store: SessionStore,
    request: AnalyzePositionRequest,
    fallbacks_used: list[str],
) -> str | None:
    if not session_store.available():
        fallbacks_used.append("mongo_sessions_unavailable")
        return None

    session = session_store.get_session(request.session_id) if request.session_id else None
    if session is None:
        session = session_store.create_session()
    if session is None:
        fallbacks_used.append("mongo_sessions_unavailable")
        return None

    _sync_moves(session_store, session, request)
    return session["id"]


def _sync_moves(
    session_store: SessionStore,
    session: dict,
    request: AnalyzePositionRequest,
) -> None:
    session_moves = [str(move.get("uci", "")) for move in session.get("moves", [])]
    request_moves = [move.lower() for move in request.moves]
    prefix = _common_prefix_length(session_moves, request_moves)

    if len(request_moves) <= prefix:
        return

    moves = build_move_docs(request.moves)
    if moves is not None:
        session_store.set_moves(session["id"], moves)


def _common_prefix_length(left: list[str], right: list[str]) -> int:
    prefix = 0
    for a, b in zip(left, right):
        if a != b:
            break
        prefix += 1
    return prefix


def _position_key(fen: str, level: str, ratings: list[int]) -> str:
    normalized_fen = chess.Board(fen).fen()
    return f"{normalized_fen}|{level}|{','.join(str(rating) for rating in ratings)}"


def _source_confidence(total_games: int, settings: RecommendationSettings) -> dict:
    enough_games = total_games >= settings.min_position_games
    return {
        "total_games": total_games,
        "min_position_games": settings.min_position_games,
        "min_move_share": settings.min_move_share,
        "low_confidence": not enough_games,
        "reason": None if enough_games else "position_sample_too_small",
    }


def _rank_moves(
    moves: tuple[RecommendedMove, ...],
    total_games: int,
    fen: str,
    settings: RecommendationSettings,
) -> list[RecommendedMove]:
    side = "black" if fen.split(" ")[1] == "b" else "white"
    ranked: list[RecommendedMove] = []
    for move in moves:
        move_share = round((move.games or 0) / total_games, 6) if total_games > 0 else None
        relevant = move_share is not None and move_share >= settings.min_move_share
        badges = [_source_badge(move.source)]
        if move.average_rating is not None:
            badges.append(f"Elo {move.average_rating}")
        if not relevant:
            badges.append("Faible ech.")
        ranked.append(
            move.model_copy(
                update={
                    "move_share": move_share,
                    "relevant": relevant,
                    "badges": badges,
                }
            )
        )

    return sorted(ranked, key=lambda move: _move_rank_key(move, side), reverse=True)


def _source_badge(source: str) -> str:
    if source == LICHESS_SOURCE:
        return "Lichess"
    if source == "masters-opening-explorer":
        return "Masters"
    if source == DEMO_OPENING_SOURCE:
        return "Seed"
    return source


def _move_rank_key(move: RecommendedMove, side: str) -> tuple[int, float, int]:
    chance = getattr(move, side)
    return (
        1 if move.relevant and chance is not None else 0,
        chance or 0,
        move.games or 0,
    )


def _run_stockfish_if_needed(
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
    if (
        local_opening_matched
        and recommended_moves
        and not confidence["low_confidence"]
        and has_relevant_move
    ):
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


def _retrieve_rag_context(
    request: AnalyzePositionRequest,
    opening: Opening,
    fallback_text: str,
    opening_tree: OpeningTree | None,
    intent_router: IntentRouter | None,
    rag_service: RagService | None,
) -> tuple[list[RagContext], list[str], OpeningTreeContext, tuple[RetrievedContext, ...]]:
    fallback_context = _fallback_rag_context(opening, fallback_text)
    fallback_tree_context = _fallback_tree_context(opening)
    if opening_tree is None or intent_router is None or rag_service is None:
        return [fallback_context], [], fallback_tree_context, ()

    try:
        tree_context = opening_tree.context_for_position(moves=tuple(request.moves), fen=request.fen)
        decision = intent_router.classify(_intent_context(request, tree_context))
        plan = build_retrieval_plan(tree_context, decision)
        result = rag_service.retrieve(plan, _rag_query(request, opening, tree_context))
    except Exception:  # noqa: BLE001 - RAG must not break the analysis endpoint
        return [fallback_context], ["rag_unavailable"], fallback_tree_context, ()

    fallbacks = [
        *_intent_router_fallback_labels(decision.source),
        *[_rag_fallback_label(reason) for reason in result.fallback_reasons],
    ]
    contexts = [_retrieved_context_to_api(context) for context in result.contexts]
    if not contexts:
        return [fallback_context], fallbacks, tree_context, ()

    return contexts, fallbacks, tree_context, result.contexts


def _fallback_tree_context(opening: Opening) -> OpeningTreeContext:
    return OpeningTreeContext(
        state="matched" if opening.matched else "out_of_theory",
        fallback_opening_name=opening.name if opening.matched else None,
    )


def _intent_context(request: AnalyzePositionRequest, tree_context: OpeningTreeContext) -> IntentRouterContext:
    current = tree_context.current
    return IntentRouterContext(
        question=request.question,
        level=request.level,
        moves=tuple(request.moves),
        fen=request.fen,
        current_opening_name=current.opening_name if current else None,
        current_eco=current.eco_code if current else None,
        current_node_id=current.node_id if current else None,
        legal_child_moves=tuple(_candidate_move(child) for child in tree_context.children),
    )


def _candidate_move(child) -> CandidateMove:  # type: ignore[no-untyped-def]
    return CandidateMove(
        san=child.entry_move or (child.san[-1] if child.san else ""),
        uci=child.uci[-1] if child.uci else None,
        opening_name=child.opening_name,
        eco_code=child.eco_code,
        opening_node_id=child.node_id,
    )


def _rag_query(
    request: AnalyzePositionRequest,
    opening: Opening,
    tree_context: OpeningTreeContext,
) -> str:
    parts = [
        f"Opening: {opening.eco} {opening.name}",
        f"Level: {request.level}",
        f"PGN: {request.pgn}",
        "Intent: explain plans and ideas for the current opening position",
    ]
    if request.question:
        parts.insert(0, f"Question: {request.question}")
    if tree_context.current is not None:
        parts.append(f"Current node: {tree_context.current.opening_name}")
    return "\n".join(parts)


def _retrieved_context_to_api(context: RetrievedContext) -> RagContext:
    return RagContext(
        text=context.text,
        source=context.source,
        url=context.source_url,
        chunk_id=context.chunk_id,
        license_or_terms=context.license_or_terms,
        page_id=context.page_id,
        section_index=context.section_index,
        part_index=context.part_index,
        section_title=context.section_title,
        relation_to_position=context.relation_to_position,
        entry_move=context.entry_move,
        opening_name=context.opening_name,
        eco_code=context.eco_code,
    )


def _fallback_rag_context(opening: Opening, text: str) -> RagContext:
    return RagContext(
        text=text,
        source=_rag_source(opening),
        url=None,
        relation_to_position="fallback",
        opening_name=opening.name,
        eco_code=opening.eco,
    )


def _rag_fallback_label(reason: str) -> str:
    if reason == "rag_embedding_unavailable":
        return "ollama_unavailable"
    if reason == "rag_store_unavailable":
        return "milvus_unavailable"
    return reason or "rag_unavailable"


def _intent_router_fallback_labels(source: RouterSource) -> list[str]:
    if source == "fallback_after_provider_error":
        return ["intent_router_provider_unavailable"]
    if source == "fallback_after_low_confidence":
        return ["intent_router_low_confidence"]
    if source == "fallback_after_invalid_response":
        return ["intent_router_invalid_response"]
    return []


def _lichess_context(opening: Opening) -> str:
    return f"Lichess Opening Explorer identifie la ligne comme {opening.eco} {opening.name}."


def _rag_source(opening: Opening) -> str:
    if opening.source == LICHESS_SOURCE:
        return LICHESS_SOURCE
    return "demo-pedagogical-seed"
