import asyncio
import logging
import threading
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api.routes import (
    get_cache_store,
    get_coach_service,
    get_intent_router,
    get_lichess_client,
    get_opening_tree,
    get_rag_service,
    get_run_store,
    get_session_store,
    get_stockfish_service,
    get_youtube_client,
)
from backend.app.core.settings import get_settings
from backend.app.models.analysis import AnalyzePositionRequest, LichessStats, Opening, RecommendedMove, Video
from backend.app.services.analysis import _rating_buckets
from backend.app.services.cache_store import CacheStore
from backend.app.services.coach import ConservativeCoachService
from backend.app.services.coach_stream import stream_coach
from backend.app.services.lichess import LichessExplorerResult
from backend.app.services.intent_router import IntentRouter, IntentRouterError
from backend.app.services.coach import LlmCoachService
from backend.app.services.llm import FakeLLMProvider, LLMProviderError
from backend.app.services.rag import RagRetrievalResult
from backend.app.services.retrieval_contracts import OpeningTreeContext, OpeningTreeNodeContext, RetrievedContext
from backend.app.services.session_store import SessionStore
from backend.app.services.run_store import RunStore
from backend.app.services.youtube import YouTubeSearchResult
from backend.tests.fakes import FakeDatabase


client = TestClient(app)

KINGS_PAWN_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
AFTER_E4_E5_FEN = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
AFTER_E4_D5_FEN = "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
AFTER_NF3_FEN = "rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 1 1"

UNMATCHED_PAYLOAD = {
    "fen": AFTER_NF3_FEN,
    "pgn": "1. Nf3",
    "moves": ["g1f3"],
    "level": "debutant",
}


class SuccessfulLichessClient:
    def fetch_explorer_analysis(self, _moves: list[str]) -> LichessExplorerResult:
        return LichessExplorerResult(
            stats=LichessStats(
                source="lichess-opening-explorer",
                games=100,
                white=0.5,
                draws=0.1,
                black=0.4,
            ),
            opening=Opening(
                eco="B00",
                name="King's Pawn",
                matched=True,
                source="lichess-opening-explorer",
            ),
            recommended_moves=(
                RecommendedMove(
                    uci="e7e5",
                    san="e5",
                    description="Le coup le plus joue selon Lichess Opening Explorer.",
                    source="lichess-opening-explorer",
                    games=60,
                    white=0.6,
                    draws=0.1,
                    black=0.3,
                ),
            ),
            fallback=None,
        )


class LichessMovesOnlyClient:
    def fetch_explorer_analysis(self, _moves: list[str]) -> LichessExplorerResult:
        return LichessExplorerResult(
            stats=LichessStats(
                source="lichess-opening-explorer",
                games=100,
                white=0.5,
                draws=0.1,
                black=0.4,
            ),
            opening=None,
            recommended_moves=(
                RecommendedMove(
                    uci="e7e5",
                    san="e5",
                    description="Le coup le plus joue selon Lichess Opening Explorer.",
                    source="lichess-opening-explorer",
                    games=60,
                    white=0.6,
                    draws=0.1,
                    black=0.3,
                ),
            ),
            fallback=None,
        )


class FallbackLichessClient:
    fallback = "lichess_unavailable"

    def fetch_explorer_analysis(self, _moves: list[str]) -> LichessExplorerResult:
        return LichessExplorerResult(
            stats=LichessStats(
                source="seed-lichess-cache",
                games=1200000,
                white=0.49,
                draws=0.05,
                black=0.46,
            ),
            fallback=self.fallback,
        )


class DisabledLichessClient(FallbackLichessClient):
    fallback = "lichess_disabled"


class SuccessfulStockfishService:
    def evaluate(self, _fen: str, *, multipv: int = 1, depth: int | None = None) -> dict:
        return {
            "status": "ok",
            "best_move": "g1f3",
            "score": {"type": "cp", "value": 24},
            "depth": depth or 12,
            "pv": ("g1f3",),
            "multipv": multipv,
            "variations": [],
        }


class CountingLichessClient(SuccessfulLichessClient):
    def __init__(self) -> None:
        self.calls = 0

    def fetch_explorer_analysis(self, _moves: list[str]) -> LichessExplorerResult:
        self.calls += 1
        return super().fetch_explorer_analysis(_moves)


class CountingStockfishService(SuccessfulStockfishService):
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, _fen: str, *, multipv: int = 1, depth: int | None = None) -> dict:
        self.calls += 1
        return super().evaluate(_fen, multipv=multipv, depth=depth)


class MissingKeyYouTubeClient:
    def search(self, query: str) -> YouTubeSearchResult:
        from backend.app.services.youtube import _fallback_result

        return _fallback_result(query, "youtube_missing_api_key")


RUY_TREE_NODE = OpeningTreeNodeContext(
    node_id="ruy-node",
    eco_code="C60",
    opening_name="Ruy Lopez",
    pgn="1. e4 e5 2. Nf3 Nc6 3. Bb5",
    uci=("e2e4", "e7e5", "g1f3", "b8c6", "f1b5"),
    san=("e4", "e5", "Nf3", "Nc6", "Bb5"),
    fen="ruy-fen",
    epd="ruy-epd",
    depth=5,
)

BERLIN_TREE_NODE = OpeningTreeNodeContext(
    node_id="berlin-node",
    eco_code="C65",
    opening_name="Ruy Lopez: Berlin Defense",
    pgn="1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6",
    uci=("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6"),
    san=("e4", "e5", "Nf3", "Nc6", "Bb5", "Nf6"),
    fen="berlin-fen",
    epd="berlin-epd",
    depth=6,
    entry_move="Nf6",
)


class FakeOpeningTree:
    def context_for_position(self, *, moves: tuple[str, ...], fen: str | None = None) -> OpeningTreeContext:
        return OpeningTreeContext(current=RUY_TREE_NODE, children=(BERLIN_TREE_NODE,))


class FakeOutOfTheoryOpeningTree:
    def context_for_position(self, *, moves: tuple[str, ...], fen: str | None = None) -> OpeningTreeContext:
        return OpeningTreeContext(state="out_of_theory")


class FakeRagService:
    def __init__(self, result: RagRetrievalResult | None = None, *, fail: bool = False) -> None:
        self.result = result or RagRetrievalResult(contexts=())
        self.fail = fail
        self.calls: list[dict] = []

    def retrieve(self, plan, query: str) -> RagRetrievalResult:  # type: ignore[no-untyped-def]
        self.calls.append({"plan": plan, "query": query})
        if self.fail:
            raise RuntimeError("rag unavailable")
        return self.result


class FailingIntentPrimary:
    def classify(self, _context):  # type: ignore[no-untyped-def]
        raise IntentRouterError("provider unavailable")


@pytest.fixture(autouse=True)
def hermetic_lichess_client() -> Iterator[None]:
    app.dependency_overrides[get_lichess_client] = lambda: DisabledLichessClient()
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def hermetic_stores() -> Iterator[FakeDatabase]:
    database = FakeDatabase()
    app.dependency_overrides[get_cache_store] = lambda: CacheStore(
        database=database,
        settings=get_settings().mongodb,
    )
    app.dependency_overrides[get_session_store] = lambda: SessionStore(database=database)
    app.dependency_overrides[get_run_store] = lambda: RunStore(database=database)
    yield database


@pytest.fixture(autouse=True)
def hermetic_rag() -> Iterator[None]:
    app.dependency_overrides[get_opening_tree] = lambda: None
    app.dependency_overrides[get_intent_router] = lambda: None
    app.dependency_overrides[get_rag_service] = lambda: None
    yield


@pytest.fixture(autouse=True)
def hermetic_coach_service() -> Iterator[None]:
    app.dependency_overrides[get_coach_service] = lambda: ConservativeCoachService()
    yield


@pytest.fixture(autouse=True)
def hermetic_youtube_client() -> Iterator[None]:
    app.dependency_overrides[get_youtube_client] = lambda: MissingKeyYouTubeClient()
    yield


def _post_analysis(payload: dict) -> dict:
    response = client.post("/api/analyze-position", json=payload)
    assert response.status_code == 200
    return response.json()


def test_get_videos_returns_api_results() -> None:
    class SuccessfulYouTubeClient:
        def search(self, _query: str) -> YouTubeSearchResult:
            return YouTubeSearchResult(
                [Video(title="Ruy Lopez explained", url="https://www.youtube.com/watch?v=abc123", source="youtube-data-api")]
            )

    app.dependency_overrides[get_youtube_client] = lambda: SuccessfulYouTubeClient()

    response = client.get("/api/videos", params={"opening": "Ruy Lopez", "level": "debutant"})

    assert response.status_code == 200
    assert response.json() == {
        "videos": [
            {
                "title": "Ruy Lopez explained",
                "url": "https://www.youtube.com/watch?v=abc123",
                "source": "youtube-data-api",
                "channel_title": None,
                "thumbnail_url": None,
                "published_at": None,
                "description": None,
                "duration_seconds": None,
                "view_count": None,
            }
        ],
        "fallbacks_used": [],
        "cache": "miss",
    }


def test_get_videos_validates_level() -> None:
    response = client.get("/api/videos", params={"opening": "Ruy Lopez", "level": "expert"})

    assert response.status_code == 422


def _get_session(session_id: str) -> dict:
    response = client.get(f"/api/sessions/{session_id}")
    assert response.status_code == 200
    return response.json()


def _fetch_coach(run_id_or_session_id: str, analysis_key_or_level: str, level: str | None = None) -> dict:
    if level is None:
        run_id = run_id_or_session_id
        coach_level = analysis_key_or_level
    else:
        session = _get_session(run_id_or_session_id)
        record = next(
            record
            for record in session["analyses"]
            if record["position_key"] == analysis_key_or_level
        )
        run_id = record["facts"]["run_id"]
        coach_level = level
    response = client.post(
        "/api/coach-explanation",
        json={"run_id": run_id, "level": coach_level},
    )
    assert response.status_code == 200
    return response.json()


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


def test_rating_range_excludes_partially_overlapping_upper_group() -> None:
    request = AnalyzePositionRequest(
        fen=KINGS_PAWN_FEN,
        pgn="1. e4",
        moves=["e2e4"],
        level="debutant",
        rating_min=1000,
        rating_max=1400,
    )

    assert _rating_buckets(request, get_settings().recommendations) == [1000, 1200]


def test_equal_rating_bounds_select_the_matching_group() -> None:
    request = AnalyzePositionRequest(
        fen=KINGS_PAWN_FEN,
        pgn="1. e4",
        moves=["e2e4"],
        level="debutant",
        rating_min=1400,
        rating_max=1400,
    )

    assert _rating_buckets(request, get_settings().recommendations) == [1400]


def test_health_reuses_incoming_request_id() -> None:
    response = client.get("/health", headers={"X-Request-ID": "test-request-id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-id"


def test_http_request_log_contains_structured_context(caplog) -> None:  # type: ignore[no-untyped-def]
    with caplog.at_level(logging.INFO, logger="backend.request"):
        response = client.get("/health", headers={"X-Request-ID": "log-test-id"})

    assert response.status_code == 200

    request_logs = [
        record
        for record in caplog.records
        if record.name == "backend.request"
        and record.getMessage() == "HTTP request completed"
    ]
    assert request_logs

    record = request_logs[-1]
    assert record.request_id == "log-test-id"
    assert record.method == "GET"
    assert record.path == "/health"
    assert record.status_code == 200
    assert isinstance(record.duration_ms, float)


def test_analyze_position_returns_documented_contract() -> None:
    response = client.post(
        "/api/analyze-position",
        json={
            "fen": KINGS_PAWN_FEN,
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "debutant",
        },
    )

    assert response.status_code == 200
    body = response.json()
    session_id = body.pop("session_id")
    assert isinstance(session_id, str) and session_id
    body.pop("run_id")
    body.pop("explorer_status")
    body.pop("stockfish_status")
    body.pop("rag_status")
    assert body == {
        "opening": {
            "eco": "B00",
            "name": "King's Pawn Game",
            "matched": True,
            "source": "demo-opening-seed",
        },
        "recommended_moves": [
            {
                "uci": "e7e5",
                "san": "...e5",
                "description": "Conteste le centre et ouvre les diagonales des pieces noires.",
                "source": "demo-opening-seed",
                "games": None,
                "white": None,
                "draws": None,
                "black": None,
                "average_rating": None,
                "move_share": None,
                "relevant": True,
                "badges": [],
            },
            {
                "uci": "c7c5",
                "san": "...c5",
                "description": "Transforme la partie en Sicilienne avec un jeu asymetrique.",
                "source": "demo-opening-seed",
                "games": None,
                "white": None,
                "draws": None,
                "black": None,
                "average_rating": None,
                "move_share": None,
                "relevant": True,
                "badges": [],
            },
        ],
        "masters_moves": [],
        "masters_stats": {
            "source": "masters-opening-explorer",
            "games": 0,
            "white": 0.0,
            "draws": 0.0,
            "black": 0.0,
        },
        "lichess_stats": {
            "source": "seed-lichess-cache",
            "games": 1200000,
            "white": 0.49,
            "draws": 0.05,
            "black": 0.46,
        },
        "source_confidence": {
            "total_games": 1200000,
            "min_position_games": 100,
            "min_move_share": 0.001,
            "low_confidence": False,
            "reason": None,
        },
        "rag_context": [],
        "coach_explanation": "",
        "coach_status": "pending",
        "analysis_key": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1|debutant|1000,1200",
        "stockfish": None,
        "videos": [
            {
                "title": "Recherche YouTube: King's Pawn Game chess opening tutorial explanation debutant",
                "url": "https://www.youtube.com/results?search_query=King%27s+Pawn+Game+chess+opening+tutorial+explanation+debutant",
                "source": "youtube-search-fallback",
                "channel_title": None,
                "thumbnail_url": None,
                "published_at": None,
                "description": None,
                "duration_seconds": None,
                "view_count": None,
            }
        ],
        "fallbacks_used": [
            "demo_opening_seed",
            "lichess_disabled",
            "masters_unavailable",
            "youtube_missing_api_key",
        ],
        "cache": {"lichess": "miss", "masters": "miss", "stockfish": "skipped", "videos": "skipped"},
    }


def test_analyze_position_uses_lichess_stats_when_available() -> None:
    app.dependency_overrides[get_lichess_client] = lambda: SuccessfulLichessClient()
    response = client.post(
        "/api/analyze-position",
        json={
            "fen": KINGS_PAWN_FEN,
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "debutant",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["lichess_stats"] == {
        "source": "lichess-opening-explorer",
        "games": 100,
        "white": 0.5,
        "draws": 0.1,
        "black": 0.4,
    }
    assert "lichess_disabled" not in body["fallbacks_used"]
    assert "lichess_unavailable" not in body["fallbacks_used"]
    assert body["cache"]["lichess"] == "miss"


def test_analyze_position_returns_masters_stats_when_available() -> None:
    class MastersClient(SuccessfulLichessClient):
        def fetch_masters_analysis(self, _moves: list[str]) -> LichessExplorerResult:
            return LichessExplorerResult(
                stats=LichessStats(
                    source="masters-opening-explorer",
                    games=50,
                    white=0.42,
                    draws=0.28,
                    black=0.30,
                ),
                recommended_moves=(
                    RecommendedMove(
                        uci="g8f6",
                        san="Nf6",
                        description="Coup populaire selon Lichess Opening Explorer.",
                        source="masters-opening-explorer",
                        games=25,
                        white=0.4,
                        draws=0.3,
                        black=0.3,
                    ),
                ),
            )

    app.dependency_overrides[get_lichess_client] = lambda: MastersClient()
    response = client.post(
        "/api/analyze-position",
        json={
            "fen": KINGS_PAWN_FEN,
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "debutant",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["masters_stats"] == {
        "source": "masters-opening-explorer",
        "games": 50,
        "white": 0.42,
        "draws": 0.28,
        "black": 0.3,
    }
    assert body["masters_moves"][0]["games"] == 25
    assert body["cache"]["masters"] == "miss"

    replay = _post_analysis(
        {
            "fen": KINGS_PAWN_FEN,
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "debutant",
        }
    )
    assert replay["cache"]["masters"] == "hit"
    assert replay["masters_stats"] == body["masters_stats"]


def test_analyze_position_uses_lichess_moves_when_opening_is_missing() -> None:
    app.dependency_overrides[get_lichess_client] = lambda: LichessMovesOnlyClient()
    response = client.post(
        "/api/analyze-position",
        json={
            "fen": KINGS_PAWN_FEN,
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "debutant",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["opening"]["name"] == "King's Pawn Game"
    assert body["opening"]["source"] == "demo-opening-seed"
    assert "demo_opening_seed" in body["fallbacks_used"]
    assert body["recommended_moves"] == [
        {
            "uci": "e7e5",
            "san": "e5",
            "description": "Le coup le plus joue selon Lichess Opening Explorer.",
            "source": "lichess-opening-explorer",
            "games": 60,
            "white": 0.6,
            "draws": 0.1,
            "black": 0.3,
            "average_rating": None,
            "move_share": 0.6,
            "relevant": True,
            "badges": ["Lichess"],
        }
    ]


def test_analyze_position_uses_lichess_moves_when_local_opening_unknown() -> None:
    app.dependency_overrides[get_lichess_client] = lambda: LichessMovesOnlyClient()
    response = client.post(
        "/api/analyze-position",
        json=UNMATCHED_PAYLOAD,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["opening"]["matched"] is False
    assert "opening_not_matched" in body["fallbacks_used"]
    assert body["recommended_moves"][0]["source"] == "lichess-opening-explorer"
    assert body["recommended_moves"][0]["games"] == 60


def test_analyze_position_reports_lichess_fallback() -> None:
    app.dependency_overrides[get_lichess_client] = lambda: FallbackLichessClient()
    response = client.post(
        "/api/analyze-position",
        json={
            "fen": KINGS_PAWN_FEN,
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "debutant",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["lichess_stats"]["source"] == "seed-lichess-cache"
    assert body["opening"]["source"] == "demo-opening-seed"
    assert "demo_opening_seed" in body["fallbacks_used"]
    assert "lichess_unavailable" in body["fallbacks_used"]


def test_analyze_position_uses_lichess_opening_when_local_seed_unknown() -> None:
    app.dependency_overrides[get_lichess_client] = lambda: SuccessfulLichessClient()
    response = client.post(
        "/api/analyze-position",
        json=UNMATCHED_PAYLOAD,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["opening"] == {
        "eco": "B00",
        "name": "King's Pawn",
        "matched": True,
        "source": "lichess-opening-explorer",
    }
    assert body["recommended_moves"] == [
        {
            "uci": "e7e5",
            "san": "e5",
            "description": "Le coup le plus joue selon Lichess Opening Explorer.",
            "source": "lichess-opening-explorer",
            "games": 60,
            "white": 0.6,
            "draws": 0.1,
            "black": 0.3,
            "average_rating": None,
            "move_share": 0.6,
            "relevant": True,
            "badges": ["Lichess"],
        }
    ]
    assert body["rag_context"] == []
    assert "opening_not_matched" not in body["fallbacks_used"]
    assert "demo_opening_seed" not in body["fallbacks_used"]
    assert "youtube_missing_api_key" in body["fallbacks_used"]


def test_out_of_theory_state_removes_lichess_fallback_rag_context() -> None:
    app.dependency_overrides[get_lichess_client] = lambda: SuccessfulLichessClient()
    app.dependency_overrides[get_opening_tree] = lambda: FakeOutOfTheoryOpeningTree()
    app.dependency_overrides[get_intent_router] = lambda: IntentRouter()
    app.dependency_overrides[get_rag_service] = lambda: FakeRagService(RagRetrievalResult(contexts=()))

    response = client.post(
        "/api/analyze-position",
        json=UNMATCHED_PAYLOAD,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["opening"]["source"] == "lichess-opening-explorer"
    assert body["recommended_moves"][0]["source"] == "lichess-opening-explorer"
    assert body["rag_context"] == []

    rag_response = client.post("/api/rag-context", json={"run_id": body["run_id"]})

    assert rag_response.status_code == 200
    assert rag_response.json()["rag_context"] == []


def test_lichess_opening_is_used_as_fallback_rag_context_when_matched() -> None:
    app.dependency_overrides[get_lichess_client] = lambda: SuccessfulLichessClient()

    response = client.post(
        "/api/analyze-position",
        json=UNMATCHED_PAYLOAD,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["opening"]["source"] == "lichess-opening-explorer"

    rag_response = client.post("/api/rag-context", json={"run_id": body["run_id"]})

    assert rag_response.status_code == 200
    rag_context = rag_response.json()["rag_context"]
    assert rag_context[0]["source"] == "lichess-opening-explorer"
    assert rag_context[0]["opening_name"] == "King's Pawn"


def test_analyze_position_maps_retrieved_rag_context_with_source_attribution() -> None:
    rag_service = FakeRagService(
        RagRetrievalResult(
            contexts=(
                RetrievedContext(
                    chunk_id="chunk-1",
                    text="Ruy Lopez plans focus on central pressure and quick development.",
                    source="wikibooks",
                    source_url="https://en.wikibooks.org/wiki/Chess_Opening_Theory/1._e4/1...e5/2._Nf3/2...Nc6/3._Bb5",
                    license_or_terms="CC BY-SA 4.0",
                    page_id="wikibooks::Ruy_Lopez",
                    canonical_title="Ruy Lopez",
                    section_index=2,
                    part_index=0,
                    section_title="Plans",
                    score=0.87,
                    relation_to_position="current",
                    opening_node_id="ruy-node",
                    eco_code="C60",
                    opening_name="Ruy Lopez",
                    intent="plan",
                ),
            )
        )
    )
    app.dependency_overrides[get_opening_tree] = lambda: FakeOpeningTree()
    app.dependency_overrides[get_intent_router] = lambda: IntentRouter()
    app.dependency_overrides[get_rag_service] = lambda: rag_service

    body = _post_analysis(
        {
            "fen": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 2 3",
            "pgn": "1. e4 e5 2. Nf3 Nc6 3. Bb5",
            "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"],
            "level": "intermediaire",
        }
    )

    assert body["rag_context"] == []
    rag_response = client.post("/api/rag-context", json={"run_id": body["run_id"]})
    assert rag_response.status_code == 200
    assert rag_response.json()["rag_context"] == [
        {
            "text": "Ruy Lopez plans focus on central pressure and quick development.",
            "source": "wikibooks",
            "url": "https://en.wikibooks.org/wiki/Chess_Opening_Theory/1._e4/1...e5/2._Nf3/2...Nc6/3._Bb5",
            "chunk_id": "chunk-1",
            "license_or_terms": "CC BY-SA 4.0",
            "page_id": "wikibooks::Ruy_Lopez",
            "section_index": 2,
            "part_index": 0,
            "section_title": "Plans",
            "relation_to_position": "current",
            "entry_move": None,
            "opening_name": "Ruy Lopez",
            "eco_code": "C60",
        }
    ]
    assert body["coach_status"] == "pending"
    coach = _fetch_coach(body["session_id"], body["analysis_key"], "intermediaire")
    assert "Dans la position actuelle" in coach["explanation"]
    assert "Ruy Lopez plans focus on central pressure and quick development." in coach["explanation"]
    assert "[source: Plans, CC BY-SA 4.0]" in coach["explanation"]
    assert rag_service.calls
    assert "rag_unavailable" not in rag_response.json()["fallbacks_used"]


def test_analyze_position_question_can_trigger_next_move_child_retrieval() -> None:
    rag_service = FakeRagService(
        RagRetrievalResult(
            contexts=(
                RetrievedContext(
                    chunk_id="berlin-child",
                    text="After ...Nf6, the Berlin is a possible continuation.",
                    source="wikibooks",
                    source_url="https://en.wikibooks.org/wiki/Chess_Opening_Theory/Ruy_Lopez",
                    license_or_terms="CC BY-SA 4.0",
                    page_id="wikibooks::Ruy_Lopez",
                    canonical_title="Ruy Lopez",
                    section_index=3,
                    part_index=0,
                    section_title="Berlin Defense",
                    score=0.82,
                    relation_to_position="child",
                    entry_move="Nf6",
                    opening_node_id="berlin-node",
                    eco_code="C65",
                    opening_name="Ruy Lopez: Berlin Defense",
                    intent="variation",
                ),
            )
        )
    )
    app.dependency_overrides[get_opening_tree] = lambda: FakeOpeningTree()
    app.dependency_overrides[get_intent_router] = lambda: IntentRouter()
    app.dependency_overrides[get_rag_service] = lambda: rag_service

    body = _post_analysis(
        {
            "fen": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 2 3",
            "pgn": "1. e4 e5 2. Nf3 Nc6 3. Bb5",
            "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"],
            "level": "intermediaire",
            "question": "Que peuvent jouer les Noirs ?",
        }
    )

    rag_response = client.post("/api/rag-context", json={"run_id": body["run_id"]})
    assert rag_response.status_code == 200
    call = rag_service.calls[0]
    assert call["plan"].intent == "ask_next_moves"
    assert any(bucket.relation_to_position == "child" for bucket in call["plan"].buckets)
    assert "Question: Que peuvent jouer les Noirs ?" in call["query"]
    assert rag_response.json()["rag_context"][0]["relation_to_position"] == "child"
    assert rag_response.json()["rag_context"][0]["entry_move"] == "Nf6"
    coach = _fetch_coach(body["session_id"], body["analysis_key"], "intermediaire")
    assert "Si le camp au trait joue Nf6" in coach["explanation"]
    assert "After ...Nf6, the Berlin is a possible continuation." in coach["explanation"]
    assert "Dans la position actuelle" not in coach["explanation"]


def test_analyze_position_reports_intent_router_provider_unavailable_fallback() -> None:
    rag_service = FakeRagService(
        RagRetrievalResult(
            contexts=(
                RetrievedContext(
                    chunk_id="berlin-child",
                    text="After ...Nf6, the Berlin is a possible continuation.",
                    source="wikibooks",
                    source_url="https://en.wikibooks.org/wiki/Chess_Opening_Theory/Ruy_Lopez",
                    license_or_terms="CC BY-SA 4.0",
                    page_id="wikibooks::Ruy_Lopez",
                    canonical_title="Ruy Lopez",
                    section_index=3,
                    part_index=0,
                    section_title="Berlin Defense",
                    score=0.82,
                    relation_to_position="child",
                    entry_move="Nf6",
                    opening_node_id="berlin-node",
                    eco_code="C65",
                    opening_name="Ruy Lopez: Berlin Defense",
                    intent="variation",
                ),
            )
        )
    )
    app.dependency_overrides[get_opening_tree] = lambda: FakeOpeningTree()
    app.dependency_overrides[get_intent_router] = lambda: IntentRouter(primary=FailingIntentPrimary())
    app.dependency_overrides[get_rag_service] = lambda: rag_service

    body = _post_analysis(
        {
            "fen": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 2 3",
            "pgn": "1. e4 e5 2. Nf3 Nc6 3. Bb5",
            "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"],
            "level": "intermediaire",
            "question": "Que peuvent jouer les Noirs ?",
        }
    )

    rag_response = client.post("/api/rag-context", json={"run_id": body["run_id"]})
    assert rag_response.status_code == 200
    call = rag_service.calls[0]
    assert call["plan"].intent == "ask_next_moves"
    assert any(bucket.relation_to_position == "child" for bucket in call["plan"].buckets)
    assert rag_response.json()["rag_context"][0]["relation_to_position"] == "child"
    assert "intent_router_provider_unavailable" in rag_response.json()["fallbacks_used"]
    assert "rag_unavailable" not in rag_response.json()["fallbacks_used"]


def test_analyze_position_question_can_trigger_specific_candidate_retrieval() -> None:
    rag_service = FakeRagService(
        RagRetrievalResult(
            contexts=(
                RetrievedContext(
                    chunk_id="berlin-specific",
                    text="The Berlin Defense begins with ...Nf6.",
                    source="wikibooks",
                    source_url="https://en.wikibooks.org/wiki/Chess_Opening_Theory/Ruy_Lopez",
                    license_or_terms="CC BY-SA 4.0",
                    page_id="wikibooks::Ruy_Lopez",
                    canonical_title="Ruy Lopez",
                    section_index=3,
                    part_index=0,
                    section_title="Berlin Defense",
                    score=0.84,
                    relation_to_position="child",
                    entry_move="Nf6",
                    opening_node_id="berlin-node",
                    eco_code="C65",
                    opening_name="Ruy Lopez: Berlin Defense",
                    intent="variation",
                ),
            )
        )
    )
    app.dependency_overrides[get_opening_tree] = lambda: FakeOpeningTree()
    app.dependency_overrides[get_intent_router] = lambda: IntentRouter()
    app.dependency_overrides[get_rag_service] = lambda: rag_service

    body = _post_analysis(
        {
            "fen": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 2 3",
            "pgn": "1. e4 e5 2. Nf3 Nc6 3. Bb5",
            "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"],
            "level": "intermediaire",
            "question": "Et ...Nf6 ?",
        }
    )

    rag_response = client.post("/api/rag-context", json={"run_id": body["run_id"]})
    assert rag_response.status_code == 200
    call = rag_service.calls[0]
    assert call["plan"].intent == "ask_specific_candidate"
    child_buckets = [bucket for bucket in call["plan"].buckets if bucket.relation_to_position == "child"]
    assert child_buckets[0].node_ids == ("berlin-node",)
    assert child_buckets[0].entry_move == "Nf6"
    assert "Question: Et ...Nf6 ?" in call["query"]
    assert rag_response.json()["rag_context"][0]["relation_to_position"] == "child"
    assert rag_response.json()["rag_context"][0]["entry_move"] == "Nf6"


def test_analyze_position_keeps_questions_in_distinct_run_identities() -> None:
    rag_service = FakeRagService(RagRetrievalResult(contexts=()))
    app.dependency_overrides[get_opening_tree] = lambda: FakeOpeningTree()
    app.dependency_overrides[get_intent_router] = lambda: IntentRouter()
    app.dependency_overrides[get_rag_service] = lambda: rag_service

    payload = {
        "fen": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 2 3",
        "pgn": "1. e4 e5 2. Nf3 Nc6 3. Bb5",
        "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"],
        "level": "intermediaire",
        "question": "Que peuvent jouer les Noirs ?",
    }
    first = _post_analysis(payload)
    second = _post_analysis(
        {
            **payload,
            "question": "Pourquoi ce coup est-il bon ?",
            "session_id": first["session_id"],
        }
    )

    assert first["run_id"] != second["run_id"]

    first_rag = client.post("/api/rag-context", json={"run_id": first["run_id"]})
    second_rag = client.post("/api/rag-context", json={"run_id": second["run_id"]})
    assert first_rag.status_code == 200
    assert second_rag.status_code == 200
    assert "Question: Que peuvent jouer les Noirs ?" in rag_service.calls[0]["query"]
    assert "Question: Pourquoi ce coup est-il bon ?" in rag_service.calls[1]["query"]


def test_analyze_position_keeps_success_when_rag_retrieval_fails() -> None:
    app.dependency_overrides[get_opening_tree] = lambda: FakeOpeningTree()
    app.dependency_overrides[get_intent_router] = lambda: IntentRouter()
    app.dependency_overrides[get_rag_service] = lambda: FakeRagService(fail=True)

    body = _post_analysis(
        {
            "fen": KINGS_PAWN_FEN,
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "debutant",
        }
    )

    assert body["opening"]["name"] == "King's Pawn Game"
    rag_response = client.post("/api/rag-context", json={"run_id": body["run_id"]})
    assert rag_response.status_code == 200
    assert rag_response.json()["rag_context"] == [
        {
            "text": "Apres 1. e4, les blancs occupent le centre et liberent la dame et le fou roi.",
            "source": "demo-pedagogical-seed",
            "url": None,
            "chunk_id": None,
            "license_or_terms": None,
            "page_id": None,
            "section_index": None,
            "part_index": None,
            "section_title": None,
            "relation_to_position": "fallback",
            "entry_move": None,
            "opening_name": "King's Pawn Game",
            "eco_code": "B00",
        }
    ]
    assert body["coach_status"] == "pending"
    coach = _fetch_coach(body["session_id"], body["analysis_key"], "debutant")
    assert coach["explanation"] == (
        "Je n'ai pas assez de contexte source pour formuler une explication fiable. "
            "Je peux seulement signaler la ligne identifiée : King's Pawn Game."
    )
    assert "occupe le centre" not in coach["explanation"]
    assert "rag_unavailable" in rag_response.json()["fallbacks_used"]


def test_analyze_position_prefers_lichess_opening_over_local_seed() -> None:
    app.dependency_overrides[get_lichess_client] = lambda: SuccessfulLichessClient()
    response = client.post(
        "/api/analyze-position",
        json={
            "fen": KINGS_PAWN_FEN,
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "intermediaire",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["opening"]["name"] == "King's Pawn"
    assert body["opening"]["source"] == "lichess-opening-explorer"
    assert body["recommended_moves"][0]["games"] == 60
    assert "demo_opening_seed" not in body["fallbacks_used"]
    coach = _fetch_coach(body["session_id"], body["analysis_key"], "intermediaire")
    assert coach["explanation"] == (
        "Je n'ai pas assez de contexte source pour formuler une explication fiable. "
            "Je peux seulement signaler la ligne identifiée : King's Pawn."
    )


def test_analyze_position_matches_ruy_lopez_exact_line() -> None:
    response = client.post(
        "/api/analyze-position",
        json={
            "fen": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 2 3",
            "pgn": "1. e4 e5 2. Nf3 Nc6 3. Bb5",
            "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"],
            "level": "intermediaire",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["opening"] == {
        "eco": "C60",
        "name": "Ruy Lopez",
        "matched": True,
        "source": "demo-opening-seed",
    }
    assert body["recommended_moves"][0]["uci"] == "a7a6"
    assert "demo_opening_seed" in body["fallbacks_used"]


def test_analyze_position_uses_most_specific_known_prefix() -> None:
    response = client.post(
        "/api/analyze-position",
        json={
            "fen": "r1bqkbnr/pppp1ppp/2n5/1B2p3/3PP3/5N2/PPP2PPP/RNBQK2R b KQkq - 0 3",
            "pgn": "1. e4 e5 2. Nf3 Nc6 3. d4 Bb5",
            "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "d2d4", "f1b5"],
            "level": "avance",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["opening"]["name"] == "Italian and Spanish Game family"
    assert body["opening"]["matched"] is True


def test_analyze_position_reports_unmatched_opening() -> None:
    response = client.post(
        "/api/analyze-position",
        json=UNMATCHED_PAYLOAD,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["opening"] == {
        "eco": "?",
        "name": "Ouverture inconnue",
        "matched": False,
        "source": "local-opening-matcher",
    }
    assert "opening_not_matched" in body["fallbacks_used"]


def test_analyze_position_runs_stockfish_for_unmatched_position() -> None:
    app.dependency_overrides[get_stockfish_service] = lambda: SuccessfulStockfishService()

    body = _post_analysis(UNMATCHED_PAYLOAD)
    response = client.post("/api/stockfish/analyze-run", json={"run_id": body["run_id"]})

    assert response.status_code == 200
    assert response.json()["stockfish"] == {
        "status": "ok",
        "best_move": "g1f3",
        "score": {"type": "cp", "value": 24},
        "depth": 12,
        "pv": ["g1f3"],
        "multipv": 1,
        "variations": [],
    }


def test_analyze_position_rejects_unknown_level() -> None:
    response = client.post(
        "/api/analyze-position",
        json={
            "fen": KINGS_PAWN_FEN,
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "expert",
        },
    )

    assert response.status_code == 422


def test_analyze_position_rejects_invalid_fen() -> None:
    response = client.post(
        "/api/analyze-position",
        json={
            "fen": "not-a-fen",
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "debutant",
        },
    )

    assert response.status_code == 422


def test_stockfish_endpoint_returns_evaluation() -> None:
    app.dependency_overrides[get_stockfish_service] = lambda: SuccessfulStockfishService()

    response = client.post(
        "/api/stockfish/evaluate",
        json={
            "fen": AFTER_NF3_FEN,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "best_move": "g1f3",
        "score": {"type": "cp", "value": 24},
        "depth": 12,
        "pv": ["g1f3"],
        "multipv": 1,
        "variations": [],
    }


def test_analyze_position_serves_lichess_from_cache_on_second_call() -> None:
    counting = CountingLichessClient()
    app.dependency_overrides[get_lichess_client] = lambda: counting
    payload = {
        "fen": KINGS_PAWN_FEN,
        "pgn": "1. e4",
        "moves": ["e2e4"],
        "level": "debutant",
    }

    first = _post_analysis(payload)

    assert first["cache"]["lichess"] == "miss"
    assert counting.calls == 1

    second = _post_analysis(payload)

    assert second["cache"]["lichess"] == "hit"
    assert counting.calls == 1
    assert second["lichess_stats"] == first["lichess_stats"]
    assert second["opening"] == first["opening"]
    assert second["recommended_moves"] == first["recommended_moves"]


def test_analyze_position_does_not_cache_lichess_fallback_responses() -> None:
    counting = CountingFallbackLichessClient()
    app.dependency_overrides[get_lichess_client] = lambda: counting
    payload = {
        "fen": KINGS_PAWN_FEN,
        "pgn": "1. e4",
        "moves": ["e2e4"],
        "level": "debutant",
    }

    first = _post_analysis(payload)
    second = _post_analysis(payload)

    assert first["cache"]["lichess"] == "miss"
    assert second["cache"]["lichess"] == "miss"
    assert counting.calls == 2
    assert "lichess_unavailable" in second["fallbacks_used"]


def test_analyze_position_serves_stockfish_from_cache_on_second_call() -> None:
    counting = CountingStockfishService()
    app.dependency_overrides[get_stockfish_service] = lambda: counting

    first = _post_analysis(UNMATCHED_PAYLOAD)
    first_stockfish = client.post(
        "/api/stockfish/analyze-run", json={"run_id": first["run_id"]}
    ).json()
    second = client.post(
        "/api/stockfish/analyze-run", json={"run_id": first["run_id"]}
    ).json()

    assert first_stockfish["stockfish_status"] == "generated"
    assert second["stockfish_status"] == "generated"
    assert counting.calls == 1
    assert second["stockfish"] == first_stockfish["stockfish"]


def test_progressive_endpoints_are_isolated_and_idempotent() -> None:
    lichess = CountingFallbackLichessClient()
    stockfish = CountingStockfishService()
    rag_service = FakeRagService(RagRetrievalResult(contexts=()))
    app.dependency_overrides[get_lichess_client] = lambda: lichess
    app.dependency_overrides[get_stockfish_service] = lambda: stockfish
    app.dependency_overrides[get_opening_tree] = lambda: FakeOpeningTree()
    app.dependency_overrides[get_intent_router] = lambda: IntentRouter()
    app.dependency_overrides[get_rag_service] = lambda: rag_service

    body = _post_analysis(UNMATCHED_PAYLOAD)
    assert body["run_id"]
    assert stockfish.calls == 0
    assert rag_service.calls == []

    same_run = _post_analysis({**UNMATCHED_PAYLOAD, "session_id": body["session_id"]})
    assert same_run["run_id"] == body["run_id"]
    assert lichess.calls == 1

    first_stockfish = client.post(
        "/api/stockfish/analyze-run", json={"run_id": body["run_id"]}
    )
    second_stockfish = client.post(
        "/api/stockfish/analyze-run", json={"run_id": body["run_id"]}
    )
    assert first_stockfish.status_code == 200
    assert second_stockfish.json() == first_stockfish.json()
    assert stockfish.calls == 1

    first_rag = client.post("/api/rag-context", json={"run_id": body["run_id"]})
    second_rag = client.post("/api/rag-context", json={"run_id": body["run_id"]})
    assert first_rag.status_code == 200
    assert second_rag.json() == first_rag.json()
    assert len(rag_service.calls) == 1

    replay = _post_analysis({**UNMATCHED_PAYLOAD, "session_id": body["session_id"]})
    assert replay["stockfish"] == first_stockfish.json()["stockfish"]
    assert replay["rag_context"] == first_rag.json()["rag_context"]

    first_coach = client.post(
        "/api/coach-explanation",
        json={"run_id": body["run_id"], "level": "debutant"},
    )
    second_coach = client.post(
        "/api/coach-explanation",
        json={"run_id": body["run_id"], "level": "debutant"},
    )
    assert first_coach.status_code == 200
    assert second_coach.json() == first_coach.json()


def test_coach_stream_emits_tokens_and_persists_the_complete_text() -> None:
    provider = FakeLLMProvider(response="Explication progressive. [source: seed, demo]")
    app.dependency_overrides[get_coach_service] = lambda: LlmCoachService(provider=provider)
    body = _post_analysis(
        {
            "fen": KINGS_PAWN_FEN,
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "debutant",
        }
    )

    with client.stream("GET", f"/api/analysis-runs/{body['run_id']}/coach/stream") as response:
        assert response.status_code == 200
        stream = "".join(response.iter_text())

    assert "event: start" in stream
    assert "event: token" in stream
    assert "event: done" in stream
    assert "Explication progressive." in stream
    assert len(provider.prompts) == 1

    with client.stream("GET", f"/api/analysis-runs/{body['run_id']}/coach/stream") as response:
        replay_stream = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: done" in replay_stream
    assert "Explication progressive. [source: seed, demo]" in replay_stream
    assert len(provider.prompts) == 1

    replay = client.post(
        "/api/coach-explanation",
        json={"run_id": body["run_id"], "level": "debutant"},
    )
    assert replay.status_code == 200
    assert replay.json()["explanation"] == "Explication progressive. [source: seed, demo]"
    assert len(provider.prompts) == 1


def test_coach_stream_disconnect_resets_run_to_pending(hermetic_stores: FakeDatabase) -> None:
    body = _post_analysis(UNMATCHED_PAYLOAD)
    run_store = RunStore(database=hermetic_stores)
    run = run_store.get_run(body["run_id"])
    assert run is not None

    class DisconnectingRequest:
        async def is_disconnected(self) -> bool:
            return True

    class BlockingCoach:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.released = threading.Event()
            self.finished = threading.Event()

        def stream_explain(self, _context: object, *, level: str) -> Iterator[str]:
            del level
            self.started.set()
            try:
                yield "partial "
                self.released.wait(timeout=2)
                yield "completion"
            finally:
                self.finished.set()

    coach = BlockingCoach()

    async def consume_until_disconnect() -> None:
        events = stream_coach(
            DisconnectingRequest(),
            run,
            run_store,
            coach,
            run.level,
        )
        first = await anext(events)
        assert first.event == "start"
        assert await asyncio.to_thread(coach.started.wait, 1)
        token = await anext(events)
        assert token.event == "token"
        with pytest.raises(asyncio.CancelledError):
            await anext(events)
        coach.released.set()
        assert await asyncio.to_thread(coach.finished.wait, 1)

    asyncio.run(consume_until_disconnect())

    updated = run_store.get_run(run.run_id)
    assert updated is not None
    assert updated.coach_status == "pending"


def test_coach_stream_reports_error_instead_of_emitting_pending_placeholder(
    hermetic_stores: FakeDatabase,
) -> None:
    body = _post_analysis(UNMATCHED_PAYLOAD)
    run_store = RunStore(database=hermetic_stores)
    run = run_store.get_run(body["run_id"])
    assert run is not None

    class NonClaimingRunStore(RunStore):
        def claim_family(self, _run_id: str, _family: str) -> bool:
            return False

    unavailable_store = NonClaimingRunStore(database=hermetic_stores)

    async def collect_events() -> list:
        events = stream_coach(
            object(),
            run,
            unavailable_store,
            ConservativeCoachService(),
            run.level,
        )
        return [await anext(events), await anext(events)]

    events = asyncio.run(collect_events())

    assert [event.event for event in events] == ["start", "error"]
    assert "en cours de redaction" not in str(events[1].data)


def test_coach_explanation_reuses_stored_facts_without_calling_lichess_or_stockfish() -> None:
    counting_lichess = CountingLichessClient()
    counting_stockfish = CountingStockfishService()
    app.dependency_overrides[get_lichess_client] = lambda: counting_lichess
    app.dependency_overrides[get_stockfish_service] = lambda: counting_stockfish

    body = _post_analysis(UNMATCHED_PAYLOAD)
    assert body["coach_status"] == "pending"
    lichess_calls_after_analysis = counting_lichess.calls
    stockfish_calls_after_analysis = counting_stockfish.calls

    coach = _fetch_coach(body["session_id"], body["analysis_key"], "debutant")

    assert "explication" in coach["explanation"].lower() or "Je n'ai pas assez" in coach["explanation"]
    assert counting_lichess.calls == lichess_calls_after_analysis
    assert counting_stockfish.calls == stockfish_calls_after_analysis


def test_analyze_position_creates_session_lazily_with_first_analyzed_move() -> None:
    body = _post_analysis(
        {
            "fen": KINGS_PAWN_FEN,
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "debutant",
        }
    )

    session = _get_session(body["session_id"])
    assert session["status"] == "active"
    assert session["ended_at"] is None
    assert [move["uci"] for move in session["moves"]] == ["e2e4"]
    assert session["moves"][0]["ply"] == 1
    assert session["moves"][0]["san"] == "e4"
    assert session["moves"][0]["fen"] == KINGS_PAWN_FEN
    assert session["moves"][0]["pgn"] == "1. e4"
    assert len(session["analyses"]) == 1
    assert session["analyses"][0]["fen"] == KINGS_PAWN_FEN
    assert session["analyses"][0]["facts"]["opening"]["name"] == "King's Pawn Game"


def test_analyze_position_appends_moves_to_the_same_session() -> None:
    first = _post_analysis(
        {
            "fen": KINGS_PAWN_FEN,
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "debutant",
        }
    )

    second = _post_analysis(
        {
            "fen": AFTER_E4_E5_FEN,
            "pgn": "1. e4 e5",
            "moves": ["e2e4", "e7e5"],
            "level": "debutant",
            "session_id": first["session_id"],
        }
    )

    assert second["session_id"] == first["session_id"]

    session = _get_session(first["session_id"])
    assert [move["uci"] for move in session["moves"]] == ["e2e4", "e7e5"]
    assert [move["ply"] for move in session["moves"]] == [1, 2]
    assert session["moves"][1]["san"] == "e5"
    assert session["moves"][1]["pgn"] == "1. e4 e5"


def test_navigation_request_does_not_truncate_the_session_line() -> None:
    first = _post_analysis(
        {
            "fen": AFTER_E4_E5_FEN,
            "pgn": "1. e4 e5",
            "moves": ["e2e4", "e7e5"],
            "level": "debutant",
        }
    )

    navigation = _post_analysis(
        {
            "fen": KINGS_PAWN_FEN,
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "debutant",
            "session_id": first["session_id"],
        }
    )

    assert navigation["session_id"] == first["session_id"]
    session = _get_session(first["session_id"])
    assert [move["uci"] for move in session["moves"]] == ["e2e4", "e7e5"]


def test_new_move_after_going_back_discards_the_future_variation() -> None:
    first = _post_analysis(
        {
            "fen": AFTER_E4_E5_FEN,
            "pgn": "1. e4 e5",
            "moves": ["e2e4", "e7e5"],
            "level": "debutant",
        }
    )

    branch = _post_analysis(
        {
            "fen": AFTER_E4_D5_FEN,
            "pgn": "1. e4 d5",
            "moves": ["e2e4", "d7d5"],
            "level": "debutant",
            "session_id": first["session_id"],
        }
    )

    assert branch["session_id"] == first["session_id"]
    session = _get_session(first["session_id"])
    assert [move["uci"] for move in session["moves"]] == ["e2e4", "d7d5"]
    assert session["moves"][1]["san"] == "d5"


def test_analyze_position_degrades_when_mongo_unavailable() -> None:
    app.dependency_overrides[get_cache_store] = lambda: CacheStore(
        database=None,
        settings=get_settings().mongodb,
    )
    app.dependency_overrides[get_session_store] = lambda: SessionStore(database=None)

    body = _post_analysis(
        {
            "fen": KINGS_PAWN_FEN,
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "debutant",
        }
    )

    assert body["session_id"] is None
    assert "mongo_sessions_unavailable" in body["fallbacks_used"]
    assert body["cache"] == {
        "lichess": "skipped",
        "masters": "skipped",
        "stockfish": "skipped",
        "videos": "skipped",
    }
    assert body["opening"]["matched"] is True


def test_session_endpoints_roundtrip() -> None:
    created = client.post("/api/sessions")

    assert created.status_code == 200
    session_id = created.json()["id"]
    assert created.json()["status"] == "active"
    assert created.json()["moves"] == []

    move = client.post(
        f"/api/sessions/{session_id}/moves",
        json={"ply": 1, "uci": "e2e4", "san": "e4", "fen": KINGS_PAWN_FEN},
    )

    assert move.status_code == 200
    assert [stored["uci"] for stored in move.json()["moves"]] == ["e2e4"]
    assert move.json()["moves"][0]["pgn"] == "1. e4"

    conflict = client.post(
        f"/api/sessions/{session_id}/moves",
        json={"ply": 3, "uci": "e7e5", "san": "e5", "fen": AFTER_E4_E5_FEN},
    )

    assert conflict.status_code == 409

    analysis = client.post(
        "/api/analyze-position",
        json={
            "fen": KINGS_PAWN_FEN,
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "debutant",
            "session_id": session_id,
        },
    )

    assert analysis.status_code == 200
    assert analysis.json()["session_id"] == session_id

    session = client.get(f"/api/sessions/{session_id}")
    assert session.status_code == 200
    assert len(session.json()["analyses"]) == 1

    ended = client.post(f"/api/sessions/{session_id}/end")

    assert ended.status_code == 200
    assert ended.json()["status"] == "ended"
    assert ended.json()["ended_at"] is not None

    missing = client.get("/api/sessions/000000000000000000000099")
    assert missing.status_code == 404


def test_session_endpoints_report_mongo_unavailability() -> None:
    app.dependency_overrides[get_session_store] = lambda: SessionStore(database=None)

    assert client.post("/api/sessions").status_code == 503
    assert client.get("/api/sessions/000000000000000000000001").status_code == 503


class CountingFallbackLichessClient(FallbackLichessClient):
    def __init__(self) -> None:
        self.calls = 0

    def fetch_explorer_analysis(self, _moves: list[str]) -> LichessExplorerResult:
        self.calls += 1
        return super().fetch_explorer_analysis(_moves)


def test_analyze_position_uses_llm_coach_when_configured() -> None:
    app.dependency_overrides[get_lichess_client] = lambda: SuccessfulLichessClient()
    app.dependency_overrides[get_coach_service] = lambda: LlmCoachService(
        provider=FakeLLMProvider(response="Explication LLM. [source: King's Pawn, CC BY-SA 4.0]")
    )

    data = _post_analysis({
        "fen": KINGS_PAWN_FEN,
        "pgn": "1. e4",
        "moves": ["e2e4"],
        "level": "debutant",
    })

    assert data["coach_status"] == "pending"
    coach = _fetch_coach(data["session_id"], data["analysis_key"], "debutant")
    assert coach["explanation"] == "Explication LLM. [source: King's Pawn, CC BY-SA 4.0]"
    assert coach["coach_status"] == "generated"
    assert "llm_coach_unavailable" not in coach["fallbacks_used"]


def test_analyze_position_accepts_llm_without_citations() -> None:
    app.dependency_overrides[get_lichess_client] = lambda: SuccessfulLichessClient()
    app.dependency_overrides[get_coach_service] = lambda: LlmCoachService(
        provider=FakeLLMProvider(response="Explication sans citation.")
    )

    data = _post_analysis({
        "fen": KINGS_PAWN_FEN,
        "pgn": "1. e4",
        "moves": ["e2e4"],
        "level": "debutant",
    })

    coach = _fetch_coach(data["session_id"], data["analysis_key"], "debutant")
    assert coach["explanation"] == "Explication sans citation."
    assert coach["coach_status"] == "generated"
    assert "llm_coach_unavailable" not in coach["fallbacks_used"]


def test_analyze_position_falls_back_on_llm_provider_error() -> None:
    app.dependency_overrides[get_lichess_client] = lambda: SuccessfulLichessClient()
    app.dependency_overrides[get_coach_service] = lambda: LlmCoachService(
        provider=FakeLLMProvider(responses=[LLMProviderError("ollama down")])
    )

    data = _post_analysis({
        "fen": KINGS_PAWN_FEN,
        "pgn": "1. e4",
        "moves": ["e2e4"],
        "level": "debutant",
    })

    coach = _fetch_coach(data["session_id"], data["analysis_key"], "debutant")
    assert "llm_coach_unavailable" in coach["fallbacks_used"]
    assert "Je n'ai pas assez de contexte source" in coach["explanation"]
