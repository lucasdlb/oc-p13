from collections.abc import Iterator

from fastapi import APIRouter, Depends

from backend.app.core.settings import get_settings
from backend.app.models.analysis import AnalyzePositionRequest, AnalyzePositionResponse
from backend.app.services.analysis import analyze_position
from backend.app.services.lichess import LichessExplorerClient


router = APIRouter()


def get_lichess_client() -> Iterator[LichessExplorerClient]:
    with LichessExplorerClient(get_settings().lichess) as lichess_client:
        yield lichess_client


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/analyze-position", response_model=AnalyzePositionResponse)
def analyze_position_endpoint(
    request: AnalyzePositionRequest,
    lichess_client: LichessExplorerClient = Depends(get_lichess_client),
) -> AnalyzePositionResponse:
    return analyze_position(request, lichess_client)
