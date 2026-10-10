"""Explorer family service.

The Explorer owns opening matching, Lichess/Masters lookups, caching and the
fast snapshot returned before RAG, Stockfish and coach synthesis run.
"""

from pydantic import ValidationError

from backend.app.core.settings import RecommendationSettings
from backend.app.models.analysis import AnalysisSnapshot, AnalyzePositionRequest, LichessStats, Opening, RecommendedMove, Video
from backend.app.services.cache_store import CacheStore, lichess_cache_key, masters_cache_key
from backend.app.services.lichess import LichessExplorerClient, LichessExplorerResult
from backend.app.services.opening_book import DEMO_OPENING_SOURCE, match_opening
from backend.app.services.youtube import YouTubeClient, search_videos


class ExplorerService:
    """Build deterministic Explorer facts with injected external adapters."""

    def __init__(self, settings: RecommendationSettings) -> None:
        self._settings = settings

    def build_snapshot(
        self,
        request: AnalyzePositionRequest,
        lichess_client: LichessExplorerClient,
        cache_store: CacheStore,
        youtube_client: YouTubeClient | None = None,
    ) -> AnalysisSnapshot:
        local_match = match_opening(request.moves, request.fen)
        ratings = rating_buckets(request, self._settings)
        cache_status = {"lichess": "skipped", "masters": "skipped", "stockfish": "skipped"}
        lichess_result = _fetch_lichess_cached(
            cache_store, lichess_client, request.moves, ratings,
            self._settings.default_moves, cache_status,
        )
        masters_result = _fetch_masters_cached(
            cache_store, lichess_client, request.moves,
            self._settings.default_moves, cache_status,
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

        confidence = _source_confidence(lichess_result.stats.games, self._settings)
        recommended_moves = (
            _rank_moves(
                lichess_result.recommended_moves,
                total_games=lichess_result.stats.games,
                fen=request.fen,
                settings=self._settings,
            )
            if lichess_result.recommended_moves
            else list(local_match.recommended_moves)
        )
        if lichess_result.fallback:
            fallbacks_used.append(lichess_result.fallback)
        if masters_result.fallback:
            fallbacks_used.append(masters_result.fallback)
        if youtube_client is not None and opening.matched:
            videos, video_fallbacks, video_cache = search_videos(
                opening.name, request.level, youtube_client, cache_store
            )
            fallbacks_used.extend(video_fallbacks)
            cache_status["videos"] = video_cache
        else:
            videos, video_fallbacks = _video_fallback(opening.name, request.level)
            fallbacks_used.extend(video_fallbacks)
            cache_status["videos"] = "skipped"
        return AnalysisSnapshot(
            opening=opening,
            recommended_moves=recommended_moves,
            masters_moves=_rank_moves(
                masters_result.recommended_moves,
                total_games=masters_result.stats.games,
                fen=request.fen,
                settings=self._settings,
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


def rating_buckets(request: AnalyzePositionRequest, settings: RecommendationSettings) -> list[int]:
    preset = settings.rating_presets.get(request.level)
    minimum = request.rating_min if request.rating_min is not None else preset.min if preset else 0
    maximum = request.rating_max if request.rating_max is not None else preset.max if preset else 2500
    buckets = (0, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2500)
    if minimum > maximum:
        minimum, maximum = maximum, minimum
    if minimum == maximum:
        return [minimum] if minimum in buckets else []
    return [bucket for bucket in buckets if minimum <= bucket < maximum]


def _video_fallback(opening: str, level: str) -> tuple[list[Video], list[str]]:
    from urllib.parse import quote_plus

    query = f"{opening} chess opening tutorial explanation {level}"
    return [
        Video(
            title=f"Recherche YouTube: {opening} {level}",
            url=f"https://www.youtube.com/results?search_query={quote_plus(query)}",
            source="youtube-search-fallback",
        )
    ], ["youtube_search_fallback"]


def _fetch_lichess(
    client: LichessExplorerClient,
    moves: list[str],
    ratings: list[int],
    move_count: int,
) -> LichessExplorerResult:
    try:
        return client.fetch_explorer_analysis(moves, ratings=ratings, move_count=move_count)
    except TypeError:
        return client.fetch_explorer_analysis(moves)


def _fetch_masters(client: LichessExplorerClient, moves: list[str], move_count: int) -> LichessExplorerResult:
    fetch_masters = getattr(client, "fetch_masters_analysis", None)
    if fetch_masters is None:
        return LichessExplorerResult(
            stats=LichessStats(source="masters-opening-explorer", games=0, white=0, draws=0, black=0),
            fallback="masters_unavailable",
        )
    try:
        return fetch_masters(moves, move_count=move_count)
    except TypeError:
        return fetch_masters(moves)


def _fetch_lichess_cached(cache: CacheStore, client: LichessExplorerClient, moves: list[str], ratings: list[int], move_count: int, status: dict) -> LichessExplorerResult:
    key = lichess_cache_key(moves, ratings)
    if cache.available():
        cached = _result_from_payload(cache.get_lichess(key))
        if cached is not None:
            status["lichess"] = "hit"
            return cached
    result = _fetch_lichess(client, moves, ratings, move_count)
    status["lichess"] = "miss" if cache.available() else "skipped"
    if result.fallback is None and cache.available():
        cache.set_lichess(key, _result_to_payload(result))
    return result


def _fetch_masters_cached(cache: CacheStore, client: LichessExplorerClient, moves: list[str], move_count: int, status: dict) -> LichessExplorerResult:
    key = masters_cache_key(moves)
    if cache.available():
        cached = _result_from_payload(cache.get_masters(key))
        if cached is not None:
            status["masters"] = "hit"
            return cached
    result = _fetch_masters(client, moves, move_count)
    status["masters"] = "miss" if cache.available() else "skipped"
    if result.fallback is None and cache.available():
        cache.set_masters(key, _result_to_payload(result))
    return result


def _result_to_payload(result: LichessExplorerResult) -> dict:
    return {
        "stats": result.stats.model_dump(),
        "opening": result.opening.model_dump() if result.opening else None,
        "recommended_moves": [move.model_dump() for move in result.recommended_moves],
    }


def _result_from_payload(payload: dict) -> LichessExplorerResult | None:
    if not isinstance(payload, dict):
        return None
    try:
        return LichessExplorerResult(
            stats=LichessStats.model_validate(payload["stats"]),
            opening=Opening.model_validate(payload["opening"]) if payload.get("opening") else None,
            recommended_moves=tuple(RecommendedMove.model_validate(move) for move in payload.get("recommended_moves", [])),
        )
    except (KeyError, TypeError, ValueError, ValidationError):
        return None


def _source_confidence(total_games: int, settings: RecommendationSettings) -> dict:
    enough_games = total_games >= settings.min_position_games
    return {
        "total_games": total_games,
        "min_position_games": settings.min_position_games,
        "min_move_share": settings.min_move_share,
        "low_confidence": not enough_games,
        "reason": None if enough_games else "position_sample_too_small",
    }


def _rank_moves(moves: tuple[RecommendedMove, ...], total_games: int, fen: str, settings: RecommendationSettings) -> list[RecommendedMove]:
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
        ranked.append(move.model_copy(update={"move_share": move_share, "relevant": relevant, "badges": badges}))
    return sorted(ranked, key=lambda move: _move_rank_key(move, side), reverse=True)


def _source_badge(source: str) -> str:
    if source == "lichess-opening-explorer":
        return "Lichess"
    if source == "masters-opening-explorer":
        return "Masters"
    if source == DEMO_OPENING_SOURCE:
        return "Seed"
    return source


def _move_rank_key(move: RecommendedMove, side: str) -> tuple[int, float, int]:
    chance = getattr(move, side)
    return (1 if move.relevant and chance is not None else 0, chance or 0, move.games or 0)
