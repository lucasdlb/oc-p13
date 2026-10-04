from urllib.parse import quote_plus

import chess
from pydantic import ValidationError

from backend.app.core.settings import RecommendationSettings, get_settings
from backend.app.models.analysis import (
    AnalyzePositionRequest,
    AnalyzePositionResponse,
    LichessStats,
    Opening,
    RagContext,
    RecommendedMove,
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
    OpeningTreeContext,
    RetrievedContext,
    build_coach_context,
)
from backend.app.services.retrieval_plan_builder import build_retrieval_plan
from backend.app.services.session_store import SessionStore, build_move_docs
from backend.app.services.stockfish import StockfishService, engine_version


RATING_BUCKETS = (0, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2500)


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
) -> AnalyzePositionResponse:
    all_settings = get_settings()
    settings = all_settings.recommendations
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
        context = _lichess_context(opening)
    elif local_match.matched:
        opening = local_match.opening
        context = local_match.context
        fallbacks_used.append("demo_opening_seed")
    else:
        opening = local_match.opening
        context = local_match.context
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

    rag_context, rag_fallbacks, tree_context, retrieved_contexts = _retrieve_rag_context(
        request,
        opening,
        context,
        opening_tree,
        intent_router,
        rag_service,
    )
    fallbacks_used.extend(rag_fallbacks)

    stockfish = _run_stockfish_if_needed(
        stockfish_service,
        cache_store,
        request.fen,
        confidence,
        recommended_moves,
        local_match.matched,
        cache_status,
        depth=all_settings.stockfish.depth,
        binary=all_settings.stockfish.binary,
    )
    if stockfish is not None:
        if stockfish["status"] == "ok":
            fallbacks_used.append("stockfish_evaluation")
        else:
            fallbacks_used.append("stockfish_unavailable")

    fallbacks_used.append("youtube_search_fallback")

    query = quote_plus(f"{opening.name} chess opening {request.level}")

    session_id = _sync_session(session_store, request, fallbacks_used)
    coach_context = build_coach_context(
        tree_context=tree_context,
        retrieved_contexts=retrieved_contexts,
        lichess_stats=lichess_result.stats.model_dump(),
        stockfish=stockfish,
        fallbacks=tuple(fallbacks_used),
    )

    try:
        coach_explanation = (coach_service or ConservativeCoachService()).explain(coach_context, level=request.level)
    except CoachFallbackError as exc:
        coach_explanation = exc.text
        fallbacks_used.append(exc.fallback_label)

    response = AnalyzePositionResponse(
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
        rag_context=rag_context,
        coach_explanation=coach_explanation,
        stockfish=stockfish,
        videos=[
            Video(
                title=f"Recherche YouTube: {opening.name} {request.level}",
                url=f"https://www.youtube.com/results?search_query={query}",
                source="youtube-search-fallback",
            )
        ],
        fallbacks_used=fallbacks_used,
        session_id=session_id,
        cache=cache_status,
    )

    if session_id is not None:
        session_store.save_analysis(
            session_id,
            _position_key(request.fen, request.level, ratings),
            request.fen,
            response.model_dump(),
        )

    return response


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

