import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api.routes import get_lichess_client
from backend.app.models.analysis import LichessStats, Opening, RecommendedMove
from backend.app.services.lichess import LichessExplorerResult


client = TestClient(app)


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


@pytest.fixture(autouse=True)
def hermetic_lichess_client() -> Iterator[None]:
    app.dependency_overrides[get_lichess_client] = lambda: DisabledLichessClient()
    yield
    app.dependency_overrides.clear()


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


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
            "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
            "pgn": "1. e4",
            "moves": ["e2e4"],
            "level": "debutant",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
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
            },
        ],
        "lichess_stats": {
            "source": "seed-lichess-cache",
            "games": 1200000,
            "white": 0.49,
            "draws": 0.05,
            "black": 0.46,
        },
        "rag_context": [
                {
                    "text": "Apres 1. e4, les blancs occupent le centre et liberent la dame et le fou roi.",
                    "source": "demo-pedagogical-seed",
                    "url": None,
                }
        ],
        "coach_explanation": "Tu as joue 1. e4 : ce coup prend de l'espace au centre et prepare le developpement rapide des pieces. Les reponses ...e5 et ...c5 sont deux plans classiques a connaitre.",
        "stockfish": None,
        "videos": [
            {
                "title": "Recherche YouTube: King's Pawn Game debutant",
                "url": "https://www.youtube.com/results?search_query=King%27s+Pawn+Game+chess+opening+debutant",
                "source": "youtube-search-fallback",
            }
        ],
        "fallbacks_used": ["demo_opening_seed", "lichess_disabled", "youtube_search_fallback"],
    }


def test_analyze_position_uses_lichess_stats_when_available() -> None:
    app.dependency_overrides[get_lichess_client] = lambda: SuccessfulLichessClient()
    response = client.post(
        "/api/analyze-position",
        json={
            "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
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


def test_analyze_position_uses_lichess_moves_when_opening_is_missing() -> None:
    app.dependency_overrides[get_lichess_client] = lambda: LichessMovesOnlyClient()
    response = client.post(
        "/api/analyze-position",
        json={
            "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
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
        }
    ]


def test_analyze_position_uses_lichess_moves_when_local_opening_unknown() -> None:
    app.dependency_overrides[get_lichess_client] = lambda: LichessMovesOnlyClient()
    response = client.post(
        "/api/analyze-position",
        json={
            "fen": "rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 1 1",
            "pgn": "1. Nf3",
            "moves": ["g1f3"],
            "level": "debutant",
        },
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
            "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
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
        json={
            "fen": "rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 1 1",
            "pgn": "1. Nf3",
            "moves": ["g1f3"],
            "level": "debutant",
        },
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
        }
    ]
    assert body["rag_context"] == [
        {
            "text": "Lichess Opening Explorer identifie la ligne comme B00 King's Pawn.",
            "source": "lichess-opening-explorer",
            "url": None,
        }
    ]
    assert "opening_not_matched" not in body["fallbacks_used"]
    assert "demo_opening_seed" not in body["fallbacks_used"]
    assert "youtube_search_fallback" in body["fallbacks_used"]


def test_analyze_position_prefers_lichess_opening_over_local_seed() -> None:
    app.dependency_overrides[get_lichess_client] = lambda: SuccessfulLichessClient()
    response = client.post(
        "/api/analyze-position",
        json={
            "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
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
    assert body["coach_explanation"] == (
        "Lichess Opening Explorer identifie l'ouverture King's Pawn (B00), "
        "expliquee ici pour un niveau intermediaire. Le coup le plus joue dans les "
        "donnees Lichess est e5, present dans 60 parties de reference."
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
        json={
            "fen": "rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 1 1",
            "pgn": "1. Nf3",
            "moves": ["g1f3"],
            "level": "debutant",
        },
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


def test_analyze_position_rejects_unknown_level() -> None:
    response = client.post(
        "/api/analyze-position",
        json={
            "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
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
