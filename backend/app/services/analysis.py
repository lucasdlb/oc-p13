from urllib.parse import quote_plus

from backend.app.models.analysis import (
    AnalyzePositionRequest,
    AnalyzePositionResponse,
    Opening,
    RagContext,
    RecommendedMove,
    Video,
)
from backend.app.services.lichess import LICHESS_SOURCE, LichessExplorerClient
from backend.app.services.opening_book import DEMO_OPENING_SOURCE, match_opening


def analyze_position(
    request: AnalyzePositionRequest,
    lichess_client: LichessExplorerClient,
) -> AnalyzePositionResponse:
    local_match = match_opening(request.moves, request.fen)
    lichess_result = lichess_client.fetch_explorer_analysis(request.moves)

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

    if lichess_result.recommended_moves:
        recommended_moves = list(lichess_result.recommended_moves)
    else:
        recommended_moves = list(local_match.recommended_moves)

    if lichess_result.fallback:
        fallbacks_used.append(lichess_result.fallback)

    fallbacks_used.append("youtube_search_fallback")

    query = quote_plus(f"{opening.name} chess opening {request.level}")

    return AnalyzePositionResponse(
        opening=opening,
        recommended_moves=recommended_moves,
        lichess_stats=lichess_result.stats,
        rag_context=[
            RagContext(
                text=context,
                source=_rag_source(opening),
                url=None,
            )
        ],
        coach_explanation=_coach_explanation(opening, request.level, recommended_moves, context),
        stockfish=None,
        videos=[
            Video(
                title=f"Recherche YouTube: {opening.name} {request.level}",
                url=f"https://www.youtube.com/results?search_query={query}",
                source="youtube-search-fallback",
            )
        ],
        fallbacks_used=fallbacks_used,
    )


def _lichess_context(opening: Opening) -> str:
    return f"Lichess Opening Explorer identifie la ligne comme {opening.eco} {opening.name}."


def _rag_source(opening: Opening) -> str:
    if opening.source == LICHESS_SOURCE:
        return LICHESS_SOURCE
    return "demo-pedagogical-seed"


def _coach_explanation(
    opening: Opening,
    level: str,
    recommended_moves: list[RecommendedMove],
    context: str,
) -> str:
    if opening.source == DEMO_OPENING_SOURCE and opening.name == "King's Pawn Game":
        return (
            "Tu as joue 1. e4 : ce coup prend de l'espace au centre et prepare le "
            "developpement rapide des pieces. Les reponses ...e5 et ...c5 sont deux "
            "plans classiques a connaitre."
        )

    if not opening.matched:
        return (
            "Cette position sort du seed local d'ouvertures. Pour la demo, l'etape suivante "
            "sera de declencher Stockfish afin de proposer une evaluation sourcee."
        )

    if opening.source == LICHESS_SOURCE:
        explanation = (
            f"Lichess Opening Explorer identifie l'ouverture {opening.name} "
            f"({opening.eco}), expliquee ici pour un niveau {level}."
        )
        if recommended_moves and recommended_moves[0].games is not None:
            best = recommended_moves[0]
            explanation += (
                f" Le coup le plus joue dans les donnees Lichess est {best.san}, "
                f"present dans {best.games} parties de reference."
            )
        return explanation

    return f"Niveau {level} : {context}"
