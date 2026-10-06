from functools import lru_cache
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from backend.app.composition import (
    RuntimeServices,
    default_langgraph_enabled,
    default_intent_router,
    default_opening_tree,
    default_stockfish_service,
)
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
from backend.app.services.cache_store import CacheStore, get_cache_store as _legacy_get_cache_store
from backend.app.services.coach import CoachService
from backend.app.services.intent_router import IntentRouter, JevIntentClassifier
from backend.app.services.lichess import LichessExplorerClient
from backend.app.services.opening_tree import DEFAULT_OUTPUT_DIR, OpeningTree, OpeningTreeError
from backend.app.services.rag import RagService
from backend.app.services.session_store import SessionStore, get_session_store as _legacy_get_session_store, now_iso
from backend.app.services.stockfish import StockfishService
from backend.app.services.run_store import RunStore, get_run_store as _legacy_get_run_store
from backend.app.orchestration.explorer_graph import (
    ExplorerGraphDependencies,
    run_explorer_graph,
)
from backend.app.orchestration.rag_graph import RagGraphDependencies, run_rag_graph
from backend.app.orchestration.coach_graph import CoachGraphDependencies, run_coach_graph


router = APIRouter()
logger = logging.getLogger("backend.api")


def get_lichess_client(request: Request) -> LichessExplorerClient:
    return get_runtime(request).lichess_client


def get_coach_service(request: Request) -> CoachService:
    return get_runtime(request).coach_service


def get_rag_service(request: Request) -> RagService:
    return get_runtime(request).rag_service


def get_runtime(request: Request) -> RuntimeServices:
    return request.app.state.runtime


def is_langgraph_enabled(request: Request) -> bool:
    runtime = getattr(request.app.state, "runtime", None)
    return runtime.langgraph_enabled if runtime is not None else default_langgraph_enabled()


def get_cache_store(request: Request) -> CacheStore:
    runtime = getattr(request.app.state, "runtime", None)
    return runtime.cache_store if runtime is not None else _legacy_get_cache_store()


def get_session_store(request: Request) -> SessionStore:
    runtime = getattr(request.app.state, "runtime", None)
    return runtime.session_store if runtime is not None else _legacy_get_session_store()


def get_run_store(request: Request) -> RunStore:
    runtime = getattr(request.app.state, "runtime", None)
    return runtime.run_store if runtime is not None else _legacy_get_run_store()


def get_stockfish_service(request: Request) -> StockfishService:
    runtime = getattr(request.app.state, "runtime", None)
    return runtime.stockfish_service if runtime is not None else default_stockfish_service()


def get_opening_tree(request: Request) -> OpeningTree | None:
    runtime = getattr(request.app.state, "runtime", None)
    return runtime.opening_tree if runtime is not None else default_opening_tree()


def get_intent_router(request: Request) -> IntentRouter:
    runtime = getattr(request.app.state, "runtime", None)
    return runtime.intent_router if runtime is not None else default_intent_router()


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
    http_request: Request,
    lichess_client: LichessClientDep,
    run_store: RunStoreDep,
    stockfish_service: StockfishService = Depends(get_stockfish_service),
    cache_store: CacheStore = Depends(get_cache_store),
    session_store: SessionStore = Depends(get_session_store),
    opening_tree: OpeningTree | None = Depends(get_opening_tree),
    intent_router: IntentRouter | None = Depends(get_intent_router),
) -> AnalyzePositionResponse:
    dependencies = ExplorerGraphDependencies(
        lichess_client=lichess_client,
        stockfish_service=stockfish_service,
        cache_store=cache_store,
        session_store=session_store,
        opening_tree=opening_tree,
        intent_router=intent_router,
        rag_service=None,
        coach_service=None,
        run_store=run_store,
    )
    if is_langgraph_enabled(http_request):
        return run_explorer_graph(request, dependencies)
    return analyze_position(
        request,
        dependencies.lichess_client,
        dependencies.stockfish_service,
        dependencies.cache_store,
        dependencies.session_store,
        dependencies.opening_tree,
        dependencies.intent_router,
        dependencies.rag_service,
        dependencies.coach_service,
        dependencies.run_store,
    )


@router.post("/api/coach-explanation", response_model=CoachExplanationResponse)
def coach_explanation_endpoint(
    request: CoachExplanationRequest,
    http_request: Request,
    coach_service: CoachServiceDep,
    run_store: RunStoreDep,
) -> CoachExplanationResponse:
    try:
        if is_langgraph_enabled(http_request):
            return run_coach_graph(
                request.run_id,
                request.level,
                CoachGraphDependencies(coach_service=coach_service, run_store=run_store),
            )
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
    http_request: Request,
    run_store: RunStoreDep,
    opening_tree: OpeningTree | None = Depends(get_opening_tree),
    intent_router: IntentRouter | None = Depends(get_intent_router),
    rag_service: RagService | None = Depends(get_rag_service),
) -> RagContextResponse:
    try:
        if is_langgraph_enabled(http_request):
            return run_rag_graph(
                request.run_id,
                RagGraphDependencies(
                    run_store=run_store,
                    opening_tree=opening_tree,
                    intent_router=intent_router,
                    rag_service=rag_service,
                ),
            )
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
