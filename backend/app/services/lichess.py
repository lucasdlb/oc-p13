from dataclasses import dataclass
from types import TracebackType

import httpx
from pydantic import BaseModel, ValidationError

from backend.app.core.settings import LichessSettings
from backend.app.models.analysis import LichessStats, Opening, RecommendedMove


LICHESS_SOURCE = "lichess-opening-explorer"
SEED_LICHESS_SOURCE = "seed-lichess-cache"
CONNECT_TIMEOUT_SECONDS = 2.0


class LichessOpeningPayload(BaseModel):
    eco: str
    name: str


class LichessMovePayload(BaseModel):
    uci: str
    san: str
    averageRating: int | None = None
    white: int
    draws: int
    black: int


class LichessExplorerPayload(BaseModel):
    white: int
    draws: int
    black: int
    opening: LichessOpeningPayload | None = None
    moves: list[LichessMovePayload] = []


@dataclass(frozen=True)
class LichessExplorerResult:
    stats: LichessStats
    opening: Opening | None = None
    recommended_moves: tuple[RecommendedMove, ...] = ()
    fallback: str | None = None


class LichessExplorerClient:
    def __init__(
        self,
        settings: LichessSettings,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self._owns_http_client = http_client is None
        self.http_client = http_client or httpx.Client(
            timeout=httpx.Timeout(settings.timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS)
        )

    def __enter__(self) -> "LichessExplorerClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_http_client:
            self.http_client.close()

    def fetch_explorer_analysis(
        self,
        moves: list[str],
        ratings: list[int] | None = None,
        move_count: int | None = None,
    ) -> LichessExplorerResult:
        if not self.settings.enabled:
            return _seed_result("lichess_disabled")

        if not self.settings.token:
            return _seed_result("lichess_missing_token")

        try:
            response = self.http_client.get(
                f"{self.settings.base_url.rstrip('/')}/lichess",
                params=_params(moves, ratings, move_count, include_variant=True),
                headers={"Authorization": f"Bearer {self.settings.token.get_secret_value()}"},
            )
            response.raise_for_status()
            payload = LichessExplorerPayload.model_validate(response.json())
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                return _seed_result("lichess_unauthorized")
            return _seed_result("lichess_unavailable")
        except (httpx.HTTPError, ValueError, ValidationError):
            return _seed_result("lichess_unavailable")

        total = payload.white + payload.draws + payload.black
        if total <= 0:
            return _seed_result("lichess_empty_stats")

        return LichessExplorerResult(
            stats=LichessStats(
                source=LICHESS_SOURCE,
                games=total,
                white=round(payload.white / total, 4),
                draws=round(payload.draws / total, 4),
                black=round(payload.black / total, 4),
            ),
            opening=_to_opening(payload.opening),
            recommended_moves=_to_recommended_moves(payload.moves),
        )

    def fetch_masters_analysis(
        self,
        moves: list[str],
        move_count: int | None = None,
    ) -> LichessExplorerResult:
        if not self.settings.enabled:
            return _empty_result("masters_disabled")

        if not self.settings.token:
            return _empty_result("masters_missing_token")

        try:
            response = self.http_client.get(
                f"{self.settings.base_url.rstrip('/')}/masters",
                params=_params(moves, ratings=None, move_count=move_count, include_variant=False),
                headers={"Authorization": f"Bearer {self.settings.token.get_secret_value()}"},
            )
            response.raise_for_status()
            payload = LichessExplorerPayload.model_validate(response.json())
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                return _empty_result("masters_unauthorized")
            return _empty_result("masters_unavailable")
        except (httpx.HTTPError, ValueError, ValidationError):
            return _empty_result("masters_unavailable")

        total = payload.white + payload.draws + payload.black
        if total <= 0:
            return _empty_result("masters_empty_stats")

        return LichessExplorerResult(
            stats=LichessStats(
                source="masters-opening-explorer",
                games=total,
                white=round(payload.white / total, 4),
                draws=round(payload.draws / total, 4),
                black=round(payload.black / total, 4),
            ),
            opening=_to_opening(payload.opening),
            recommended_moves=_to_recommended_moves(payload.moves, source="masters-opening-explorer"),
        )


def _params(
    moves: list[str],
    ratings: list[int] | None,
    move_count: int | None,
    include_variant: bool,
) -> dict[str, str | int]:
    params: dict[str, str | int] = {"play": ",".join(moves)}
    if include_variant:
        params["variant"] = "standard"
    if ratings:
        params["ratings"] = ",".join(str(rating) for rating in ratings)
    if move_count is not None:
        params["moves"] = move_count
    return params


def _to_opening(payload: LichessOpeningPayload | None) -> Opening | None:
    if payload is None:
        return None
    return Opening(
        eco=payload.eco,
        name=payload.name,
        matched=True,
        source=LICHESS_SOURCE,
    )


def _to_recommended_moves(
    payload: list[LichessMovePayload],
    source: str = LICHESS_SOURCE,
) -> tuple[RecommendedMove, ...]:
    recommended_moves: list[RecommendedMove] = []
    for rank, move in enumerate(payload, start=1):
        games = move.white + move.draws + move.black
        if games <= 0:
            continue
        recommended_moves.append(
            RecommendedMove(
                uci=move.uci,
                san=move.san,
                description=_move_description(rank),
                source=source,
                games=games,
                white=round(move.white / games, 4),
                draws=round(move.draws / games, 4),
                black=round(move.black / games, 4),
                average_rating=move.averageRating,
            )
        )
    return tuple(recommended_moves)


def _move_description(rank: int) -> str:
    if rank == 1:
        return "Le coup le plus joue selon Lichess Opening Explorer."
    return "Coup populaire selon Lichess Opening Explorer."


def _seed_result(fallback: str) -> LichessExplorerResult:
    return LichessExplorerResult(
        stats=LichessStats(
            source=SEED_LICHESS_SOURCE,
            games=1200000,
            white=0.49,
            draws=0.05,
            black=0.46,
        ),
        fallback=fallback,
    )


def _empty_result(fallback: str) -> LichessExplorerResult:
    return LichessExplorerResult(
        stats=LichessStats(
            source="masters-opening-explorer",
            games=0,
            white=0,
            draws=0,
            black=0,
        ),
        fallback=fallback,
    )
