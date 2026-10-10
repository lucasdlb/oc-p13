import httpx

from backend.app.core.settings import YouTubeSettings
from backend.app.services.cache_store import CacheStore
from backend.app.services.youtube import YouTubeClient, search_videos
from backend.tests.fakes import FakeDatabase


def test_youtube_client_maps_search_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/videos"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "abc123",
                            "contentDetails": {"duration": "PT8M"},
                            "statistics": {"viewCount": "1200"},
                        }
                    ]
                },
            )
        assert request.url.params["q"] == "Ruy Lopez chess opening debutant"
        assert request.url.params["type"] == "video"
        assert request.url.params["key"] == "test-key"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": {"videoId": "abc123"},
                        "snippet": {
                            "title": "Ruy Lopez explained",
                            "channelTitle": "Chess Channel",
                            "publishedAt": "2025-01-01T00:00:00Z",
                            "description": "An explanation.",
                            "thumbnails": {"high": {"url": "https://img.test/abc.jpg"}},
                        },
                    }
                ]
            },
        )

    client = YouTubeClient(
        YouTubeSettings(enabled=True, api_key="test-key"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.search("Ruy Lopez chess opening debutant")

    assert result.fallback is None
    assert result.videos[0].model_dump() == {
        "title": "Ruy Lopez explained",
        "url": "https://www.youtube.com/watch?v=abc123",
        "source": "youtube-data-api",
        "channel_title": "Chess Channel",
        "thumbnail_url": "https://img.test/abc.jpg",
        "published_at": "2025-01-01T00:00:00Z",
        "description": "An explanation.",
        "duration_seconds": 480,
        "view_count": 1200,
    }


def test_search_videos_uses_cache_after_success() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path.endswith("/videos"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "abc123",
                            "contentDetails": {"duration": "PT5M"},
                            "statistics": {"viewCount": "20"},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "items": [{"id": {"videoId": "abc123"}, "snippet": {"title": "Ruy Lopez"}}]
            },
        )

    client = YouTubeClient(
        YouTubeSettings(enabled=True, api_key="test-key"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    cache = CacheStore(FakeDatabase())

    first = search_videos("Ruy Lopez", "debutant", client, cache)
    second = search_videos("Ruy Lopez", "debutant", client, cache)

    assert first[2] == "miss"
    assert second[2] == "hit"
    assert calls == 2


def test_youtube_client_returns_search_fallback_without_key() -> None:
    client = YouTubeClient(YouTubeSettings(enabled=True))

    result = client.search("Ruy Lopez chess opening debutant")

    assert result.fallback == "youtube_missing_api_key"
    assert result.videos[0].source == "youtube-search-fallback"


def test_youtube_client_filters_short_videos() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/videos"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "short-id",
                            "contentDetails": {"duration": "PT45S"},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={"items": [{"id": {"videoId": "short-id"}, "snippet": {"title": "Short"}}]},
        )

    client = YouTubeClient(
        YouTubeSettings(enabled=True, api_key="test-key"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.search("Ruy Lopez chess opening tutorial explanation debutant")

    assert result.fallback == "youtube_empty_results"
    assert result.videos[0].source == "youtube-search-fallback"
