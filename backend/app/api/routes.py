from functools import lru_cache
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from backend.app.core.settings import get_settings
from backend.app.models.analysis import (
    AnalysisRunRequest,
    AnalyzePositionRequest,
    AnalyzePositionResponse,
    CoachExplanationRequest,
    CoachExplanationResponse,
    RagContextResponse,
    SessionAnalysisRecord,
    SessionMovePayload,
    SessionResponse,
    StockfishRunResponse,
    StockfishEvaluateRequest,
)
from backend.app.services.analysis import (
    AnalysisRunNotFoundError,
    analyze_stockfish_run,
    analyze_position,
    render_run_coach,
    retrieve_rag_for_run,
)
from backend.app.services.coach_stream import stream_coach
from backend.app.services.cache_store import CacheStore, get_cache_store
from backend.app.services.coach import CoachService
from backend.app.services.intent_router import IntentRouter, JevIntentClassifier
from backend.app.services.lichess import LichessExplorerClient
from backend.app.services.opening_tree import DEFAULT_OUTPUT_DIR, OpeningTree, OpeningTreeError
from backend.app.services.rag import RagService
from backend.app.services.session_store import SessionStore, get_session_store, now_iso
from backend.app.services.stockfish import StockfishService
from backend.app.services.run_store import RunStore, get_run_store


router = APIRouter()
logger = logging.getLogger("backend.api")


def get_lichess_client(request: Request) -> LichessExplorerClient:
    return request.app.state.lichess_client


def get_coach_service(request: Request) -> CoachService:
    return request.app.state.coach_service


def get_rag_service(request: Request) -> RagService:
    return request.app.state.rag_service


def get_stockfish_service() -> StockfishService:
    return StockfishService(get_settings().stockfish)


@lru_cache
def get_opening_tree() -> OpeningTree | None:
    try:
        return OpeningTree.from_snapshot_dir(DEFAULT_OUTPUT_DIR)
    except OpeningTreeError as exc:
        logger.warning("OpeningTree unavailable for RAG retrieval: %s", exc)
        return None


@lru_cache
def get_intent_router() -> IntentRouter:
    settings = get_settings().typesafe
    primary = JevIntentClassifier(settings=settings) if settings.enabled else None
    return IntentRouter(primary=primary, medium_confidence=settings.medium_confidence)


LichessClientDep = Annotated[LichessExplorerClient, Depends(get_lichess_client)]
CoachServiceDep = Annotated[CoachService, Depends(get_coach_service)]
RagServiceDep = Annotated[RagService, Depends(get_rag_service)]
RunStoreDep = Annotated[RunStore, Depends(get_run_store)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/analyze-position", response_model=AnalyzePositionResponse)
def analyze_position_endpoint(
    request: AnalyzePositionRequest,
    lichess_client: LichessClientDep,
    run_store: RunStoreDep,
    stockfish_service: StockfishService = Depends(get_stockfish_service),
    cache_store: CacheStore = Depends(get_cache_store),
    session_store: SessionStore = Depends(get_session_store),
    opening_tree: OpeningTree | None = Depends(get_opening_tree),
    intent_router: IntentRouter | None = Depends(get_intent_router),
) -> AnalyzePositionResponse:
    return analyze_position(
        request,
        lichess_client,
        stockfish_service,
        cache_store,
        session_store,
        opening_tree,
        intent_router,
        None,
        None,
        run_store,
    )


@router.post("/api/coach-explanation", response_model=CoachExplanationResponse)
def coach_explanation_endpoint(
    request: CoachExplanationRequest,
    coach_service: CoachServiceDep,
    run_store: RunStoreDep,
) -> CoachExplanationResponse:
    try:
        return render_run_coach(
            run_id=request.run_id,
            level=request.level,
            coach_service=coach_service,
            run_store=run_store,
        )
    except AnalysisRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Analysis run not found") from exc


@router.get(
    "/api/analysis-runs/{run_id}/coach/stream",
    response_class=EventSourceResponse,
    response_model=None,
)
async def coach_stream_endpoint(
    run_id: str,
    request: Request,
    coach_service: CoachServiceDep,
    run_store: RunStoreDep,
) -> AsyncIterator[ServerSentEvent]:
    run = run_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    async for event in stream_coach(request, run, run_store, coach_service, run.level):
        yield event


@router.post("/api/stockfish/analyze-run", response_model=StockfishRunResponse)
def stockfish_run_endpoint(
    request: AnalysisRunRequest,
    run_store: RunStoreDep,
    stockfish_service: StockfishService = Depends(get_stockfish_service),
    cache_store: CacheStore = Depends(get_cache_store),
) -> StockfishRunResponse:
    try:
        return analyze_stockfish_run(request.run_id, run_store, stockfish_service, cache_store)
    except AnalysisRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Analysis run not found") from exc


@router.post("/api/rag-context", response_model=RagContextResponse)
def rag_context_endpoint(
    request: AnalysisRunRequest,
    run_store: RunStoreDep,
    opening_tree: OpeningTree | None = Depends(get_opening_tree),
    intent_router: IntentRouter | None = Depends(get_intent_router),
    rag_service: RagService | None = Depends(get_rag_service),
) -> RagContextResponse:
    try:
        return retrieve_rag_for_run(
            request.run_id,
            run_store,
            opening_tree,
            intent_router,
            rag_service,
        )
    except AnalysisRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Analysis run not found") from exc


@router.post("/api/stockfish/evaluate")
def evaluate_stockfish_endpoint(
    request: StockfishEvaluateRequest,
    stockfish_service: StockfishService = Depends(get_stockfish_service),
) -> dict:
    return stockfish_service.evaluate(request.fen)


@router.post("/api/sessions", response_model=SessionResponse)
def create_session_endpoint(
    session_store: SessionStore = Depends(get_session_store),
) -> SessionResponse:
    if not session_store.available():
        raise HTTPException(status_code=503, detail="MongoDB sessions unavailable")

    session = session_store.create_session()
    if session is None:
        raise HTTPException(status_code=503, detail="MongoDB sessions unavailable")
    return SessionResponse.model_validate(session)


@router.get("/api/sessions/{session_id}", response_model=SessionResponse)
def get_session_endpoint(
    session_id: str,
    session_store: SessionStore = Depends(get_session_store),
) -> SessionResponse:
    if not session_store.available():
        raise HTTPException(status_code=503, detail="MongoDB sessions unavailable")

    session = session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session inconnue")
    return SessionResponse.model_validate(session)


@router.post("/api/sessions/{session_id}/moves", response_model=SessionResponse)
def append_move_endpoint(
    session_id: str,
    payload: SessionMovePayload,
    session_store: SessionStore = Depends(get_session_store),
) -> SessionResponse:
    if not session_store.available():
        raise HTTPException(status_code=503, detail="MongoDB sessions unavailable")

    session = session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session inconnue")

    expected_ply = len(session["moves"]) + 1
    if payload.ply != expected_ply:
        raise HTTPException(
            status_code=409,
            detail=f"Coup non continu : ply attendu {expected_ply}, recu {payload.ply}",
        )

    move = {
        "ply": payload.ply,
        "uci": payload.uci.lower(),
        "san": payload.san,
        "fen": payload.fen,
        "pgn": _pgn_after_move(session["moves"], payload.san),
        "created_at": now_iso(),
    }
    if not session_store.append_move(session_id, move):
        raise HTTPException(status_code=503, detail="MongoDB sessions unavailable")

    updated = session_store.get_session(session_id)
    if updated is None:
        raise HTTPException(status_code=503, detail="MongoDB sessions unavailable")
    return SessionResponse.model_validate(updated)


@router.post("/api/sessions/{session_id}/end", response_model=SessionResponse)
def end_session_endpoint(
    session_id: str,
    session_store: SessionStore = Depends(get_session_store),
) -> SessionResponse:
    if not session_store.available():
        raise HTTPException(status_code=503, detail="MongoDB sessions unavailable")

    session = session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session inconnue")

    if not session_store.end_session(session_id):
        raise HTTPException(status_code=503, detail="MongoDB sessions unavailable")

    updated = session_store.get_session(session_id)
    if updated is None:
        raise HTTPException(status_code=503, detail="MongoDB sessions unavailable")
    return SessionResponse.model_validate(updated)


@router.get("/api/sessions/{session_id}/analyses", response_model=list[SessionAnalysisRecord])
def list_session_analyses_endpoint(
    session_id: str,
    session_store: SessionStore = Depends(get_session_store),
) -> list[SessionAnalysisRecord]:
    if not session_store.available():
        raise HTTPException(status_code=503, detail="MongoDB sessions unavailable")

    session = session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session inconnue")

    return [SessionAnalysisRecord.model_validate(record) for record in session["analyses"]]


def _pgn_after_move(moves: list[dict], san: str) -> str:
    sans = [move["san"] for move in moves] + [san]
    parts: list[str] = []
    for index, move_san in enumerate(sans):
        if index % 2 == 0:
            parts.append(f"{index // 2 + 1}. {move_san}")
        else:
            parts[-1] = f"{parts[-1]} {move_san}"
    return " ".join(parts)
