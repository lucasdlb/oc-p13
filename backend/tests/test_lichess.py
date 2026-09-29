import httpx

from backend.app.core.settings import LichessSettings
from backend.app.models.analysis import Opening, RecommendedMove
from backend.app.services.lichess import LichessExplorerClient


def test_lichess_client_maps_explorer_analysis() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.url.params["variant"] == "standard"
        assert request.url.params["play"] == "e2e4,e7e5"
        return httpx.Response(
            200,
            json={
                "white": 50,
                "draws": 10,
                "black": 40,
                "opening": {"eco": "C20", "name": "King's Pawn Game"},
                "moves": [
                    {"uci": "g8f6", "san": "Nf6", "white": 20, "draws": 5, "black": 25},
                    {"uci": "b8c6", "san": "Nc6", "white": 10, "draws": 2, "black": 8},
                    {"uci": "a7a6", "san": "a6", "white": 0, "draws": 0, "black": 0},
                ],
            },
        )

    client = LichessExplorerClient(
        LichessSettings(enabled=True, token="test-token"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.fetch_explorer_analysis(["e2e4", "e7e5"])

    assert result.stats.model_dump() == {
        "source": "lichess-opening-explorer",
        "games": 100,
        "white": 0.5,
        "draws": 0.1,
        "black": 0.4,
    }
    assert result.fallback is None
    assert result.opening == Opening(
        eco="C20",
        name="King's Pawn Game",
        matched=True,
        source="lichess-opening-explorer",
    )
    assert result.recommended_moves == (
        RecommendedMove(
            uci="g8f6",
            san="Nf6",
            description="Le coup le plus joue selon Lichess Opening Explorer.",
            source="lichess-opening-explorer",
            games=50,
            white=0.4,
            draws=0.1,
            black=0.5,
        ),
        RecommendedMove(
            uci="b8c6",
            san="Nc6",
            description="Coup populaire selon Lichess Opening Explorer.",
            source="lichess-opening-explorer",
            games=20,
            white=0.5,
            draws=0.1,
            black=0.4,
        ),
    )


def test_lichess_client_maps_analysis_without_opening() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "white": 50,
                "draws": 10,
                "black": 40,
                "opening": None,
                "moves": [],
            },
        )

    client = LichessExplorerClient(
        LichessSettings(enabled=True, token="test-token"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.fetch_explorer_analysis(["e2e4", "d7d5"])

    assert result.stats.source == "lichess-opening-explorer"
    assert result.opening is None
    assert result.recommended_moves == ()
    assert result.fallback is None


def test_lichess_client_returns_seed_fallback_when_disabled() -> None:
    client = LichessExplorerClient(LichessSettings(enabled=False))

    result = client.fetch_explorer_analysis(["e2e4"])

    assert result.stats.source == "seed-lichess-cache"
    assert result.opening is None
    assert result.recommended_moves == ()
    assert result.fallback == "lichess_disabled"


def test_lichess_client_returns_seed_fallback_when_token_is_missing() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Lichess should not be called without a token")

    client = LichessExplorerClient(
        LichessSettings(enabled=True, token=None),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.fetch_explorer_analysis(["e2e4"])

    assert result.stats.source == "seed-lichess-cache"
    assert result.fallback == "lichess_missing_token"


def test_lichess_client_returns_seed_fallback_on_http_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "unavailable"})

    client = LichessExplorerClient(
        LichessSettings(enabled=True, token="test-token"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.fetch_explorer_analysis(["e2e4"])

    assert result.stats.source == "seed-lichess-cache"
    assert result.opening is None
    assert result.fallback == "lichess_unavailable"


def test_lichess_client_returns_specific_fallback_on_unauthorized() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized")

    client = LichessExplorerClient(
        LichessSettings(enabled=True, token="test-token"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.fetch_explorer_analysis(["e2e4"])

    assert result.stats.source == "seed-lichess-cache"
    assert result.fallback == "lichess_unauthorized"


def test_lichess_client_returns_seed_fallback_on_empty_stats() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"white": 0, "draws": 0, "black": 0})

    client = LichessExplorerClient(
        LichessSettings(enabled=True, token="test-token"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.fetch_explorer_analysis(["e2e4"])

    assert result.stats.source == "seed-lichess-cache"
    assert result.fallback == "lichess_empty_stats"


def test_lichess_client_returns_seed_fallback_on_timeout() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    client = LichessExplorerClient(
        LichessSettings(enabled=True, token="test-token"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.fetch_explorer_analysis(["e2e4"])

    assert result.stats.source == "seed-lichess-cache"
    assert result.fallback == "lichess_unavailable"


def test_lichess_client_uses_structured_timeout() -> None:
    with LichessExplorerClient(
        LichessSettings(enabled=True, token="test-token", timeout_seconds=3.0)
    ) as client:
        timeout = client.http_client.timeout

    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 2.0
    assert timeout.read == 3.0
    assert timeout.write == 3.0
    assert timeout.pool == 3.0


def test_lichess_client_closes_owned_http_client_on_exit() -> None:
    with LichessExplorerClient(LichessSettings(enabled=True, token="test-token")) as client:
        assert not client.http_client.is_closed

    assert client.http_client.is_closed


def test_lichess_client_keeps_injected_http_client_open_on_exit() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"white": 1, "draws": 0, "black": 0})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))

    with LichessExplorerClient(
        LichessSettings(enabled=True, token="test-token"),
        http_client=http_client,
    ) as client:
        assert not client.http_client.is_closed

    assert not http_client.is_closed
    http_client.close()
