"""YouTube search adapter with a visible, deterministic fallback."""

from urllib.parse import quote_plus
import re

import httpx
from pydantic import BaseModel, ValidationError

from backend.app.core.settings import YouTubeSettings
from backend.app.models.analysis import Video
from backend.app.services.cache_store import CacheStore, videos_cache_key


YOUTUBE_SOURCE = "youtube-data-api"
YOUTUBE_FALLBACK_SOURCE = "youtube-search-fallback"


class YouTubeItemId(BaseModel):
    videoId: str


class YouTubeSnippet(BaseModel):
    title: str
    description: str = ""
    channelTitle: str = ""
    publishedAt: str | None = None
    thumbnails: dict = {}


class YouTubeContentDetails(BaseModel):
    duration: str


class YouTubeStatistics(BaseModel):
    viewCount: str | None = None


class YouTubeVideoDetails(BaseModel):
    id: str
    contentDetails: YouTubeContentDetails
    statistics: YouTubeStatistics = YouTubeStatistics()


class YouTubeVideoDetailsPayload(BaseModel):
    items: list[YouTubeVideoDetails] = []


class YouTubeSearchItem(BaseModel):
    id: YouTubeItemId
    snippet: YouTubeSnippet


class YouTubeSearchPayload(BaseModel):
    items: list[YouTubeSearchItem] = []


class YouTubeSearchResult:
    def __init__(self, videos: list[Video], fallback: str | None = None) -> None:
        self.videos = videos
        self.fallback = fallback


class YouTubeClient:
    def __init__(
        self,
        settings: YouTubeSettings,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self._owns_http_client = http_client is None
        self.http_client = http_client or httpx.Client(timeout=settings.timeout_seconds)

    def close(self) -> None:
        if self._owns_http_client:
            self.http_client.close()

    def search(self, query: str) -> YouTubeSearchResult:
        if not self.settings.enabled:
            return _fallback_result(query, "youtube_disabled")
        if not self.settings.api_key:
            return _fallback_result(query, "youtube_missing_api_key")

        try:
            response = self.http_client.get(
                f"{self.settings.base_url.rstrip('/')}/search",
                params={
                    "part": "snippet",
                    "q": query,
                    "type": "video",
                    "maxResults": self.settings.max_results,
                    "relevanceLanguage": self.settings.relevance_language,
                    "order": "relevance",
                    "key": self.settings.api_key.get_secret_value(),
                },
            )
            if response.status_code in {401, 403}:
                return _fallback_result(query, "youtube_quota_or_authorization")
            response.raise_for_status()
            payload = YouTubeSearchPayload.model_validate(response.json())
        except (httpx.HTTPError, ValueError, ValidationError):
            return _fallback_result(query, "youtube_unavailable")

        videos = self._enrich_videos(payload.items)
        if not videos:
            return _fallback_result(query, "youtube_empty_results")
        return YouTubeSearchResult(videos)

    def _enrich_videos(self, items: list[YouTubeSearchItem]) -> list[Video]:
        videos = {
            item.id.videoId: Video(
                title=item.snippet.title,
                url=f"https://www.youtube.com/watch?v={item.id.videoId}",
                source=YOUTUBE_SOURCE,
                channel_title=item.snippet.channelTitle or None,
                thumbnail_url=_thumbnail_url(item.snippet.thumbnails),
                published_at=item.snippet.publishedAt,
                description=item.snippet.description or None,
            )
            for item in items
        }
        if not videos:
            return []

        try:
            response = self.http_client.get(
                f"{self.settings.base_url.rstrip('/')}/videos",
                params={
                    "part": "contentDetails,statistics",
                    "id": ",".join(videos),
                    "key": self.settings.api_key.get_secret_value(),  # type: ignore[union-attr]
                },
            )
            response.raise_for_status()
            details = YouTubeVideoDetailsPayload.model_validate(response.json())
        except (httpx.HTTPError, ValueError, ValidationError):
            return list(videos.values())

        enriched: list[Video] = []
        for detail in details.items:
            video = videos.get(detail.id)
            if video is None:
                continue
            duration = _parse_duration(detail.contentDetails.duration)
            if duration < 60:
                continue
            enriched.append(
                video.model_copy(
                    update={
                        "duration_seconds": duration,
                        "view_count": _parse_count(detail.statistics.viewCount),
                    }
                )
            )
        return enriched


def search_videos(
    opening: str,
    level: str,
    client: YouTubeClient,
    cache_store: CacheStore,
) -> tuple[list[Video], list[str], str]:
    query = f"{opening.strip()} chess opening tutorial explanation {level}"
    key = videos_cache_key(query)
    if cache_store.available():
        cached = cache_store.get_videos(key)
        if isinstance(cached, list):
            try:
                return [Video.model_validate(video) for video in cached], [], "hit"
            except (TypeError, ValueError, ValidationError):
                pass

    result = client.search(query)
    if result.fallback is None and cache_store.available():
        cache_store.set_videos(key, [video.model_dump() for video in result.videos])
        return result.videos, [], "miss"
    return result.videos, [result.fallback] if result.fallback else [], "skipped"


def _fallback_result(query: str, reason: str) -> YouTubeSearchResult:
    encoded_query = quote_plus(query)
    return YouTubeSearchResult(
        [
            Video(
                title=f"Recherche YouTube: {query}",
                url=f"https://www.youtube.com/results?search_query={encoded_query}",
                source=YOUTUBE_FALLBACK_SOURCE,
            )
        ],
        reason,
    )


def _thumbnail_url(thumbnails: dict) -> str | None:
    for name in ("high", "medium", "default"):
        thumbnail = thumbnails.get(name)
        if isinstance(thumbnail, dict) and isinstance(thumbnail.get("url"), str):
            return thumbnail["url"]
    return None


def _parse_duration(value: str) -> int:
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        return 0
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _parse_count(value: str | None) -> int | None:
    if value is None or not value.isdigit():
        return None
    return int(value)
