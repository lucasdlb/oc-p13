from collections.abc import Iterator
from functools import lru_cache
import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.app.core.settings import get_settings
from backend.app.models.analysis import (
    AnalyzePositionRequest,
    AnalyzePositionResponse,
    SessionAnalysisRecord,
    SessionMovePayload,
    SessionResponse,
    StockfishEvaluateRequest,
)
from backend.app.services.analysis import analyze_position
from backend.app.services.cache_store import CacheStore, get_cache_store
from backend.app.services.coach import CoachService, ConservativeCoachService, LlmCoachService
from backend.app.services.llm import OllamaLLMProvider
from backend.app.services.embeddings import OllamaEmbeddingProvider
from backend.app.services.intent_router import IntentRouter, JevIntentClassifier
from backend.app.services.lichess import LichessExplorerClient
from backend.app.services.milvus import MilvusStore
from backend.app.services.opening_tree import DEFAULT_OUTPUT_DIR, OpeningTree, OpeningTreeError
from backend.app.services.rag import RagService
from backend.app.services.session_store import SessionStore, get_session_store, now_iso
from backend.app.services.stockfish import StockfishService


router = APIRouter()
logger = logging.getLogger("backend.api")


def get_lichess_client() -> Iterator[LichessExplorerClient]:
    with LichessExplorerClient(get_settings().lichess) as lichess_client:
        yield lichess_client


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


def get_coach_service() -> Iterator[CoachService]:
    settings = get_settings()
    with OllamaLLMProvider(settings.llm) as provider:
        yield LlmCoachService(provider=provider)


@lru_cache
def get_rag_service() -> RagService:
    settings = get_settings()
    provider = OllamaEmbeddingProvider(settings.embeddings)
    digest = provider.model_digest()
    signature = f"{settings.embeddings.model}@{digest}" if digest else None
    store = MilvusStore(
        settings.milvus,
        embedding_signature=signature,
        create_if_missing=False,
    )
    return RagService(
        embedding_provider=provider,
        store=store,
        min_score=settings.rag.min_score,
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/analyze-position", response_model=AnalyzePositionResponse)
def analyze_position_endpoint(
    request: AnalyzePositionRequest,
    lichess_client: LichessExplorerClient = Depends(get_lichess_client),
    stockfish_service: StockfishService = Depends(get_stockfish_service),
    cache_store: CacheStore = Depends(get_cache_store),
    session_store: SessionStore = Depends(get_session_store),
    opening_tree: OpeningTree | None = Depends(get_opening_tree),
    intent_router: IntentRouter | None = Depends(get_intent_router),
    rag_service: RagService | None = Depends(get_rag_service),
    coach_service: CoachService = Depends(get_coach_service),
) -> AnalyzePositionResponse:
    return analyze_position(
        request,
        lichess_client,
        stockfish_service,
        cache_store,
        session_store,
        opening_tree,
        intent_router,
        rag_service,
        coach_service,
    )


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
        raise HTTPException(status_code=404, detail="Session inconnue")
    return SessionResponse.model_validate(updated)


@router.post("/api/sessions/{session_id}/analyses", response_model=SessionResponse)
def save_analysis_endpoint(
    session_id: str,
    payload: SessionAnalysisRecord,
    session_store: SessionStore = Depends(get_session_store),
) -> SessionResponse:
    if not session_store.available():
        raise HTTPException(status_code=503, detail="MongoDB sessions unavailable")

    session = session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session inconnue")

    record = payload.model_dump()
    record["created_at"] = now_iso()
    if not session_store.save_analysis(
        session_id,
        record["position_key"],
        record["fen"],
        record["response"],
    ):
        raise HTTPException(status_code=503, detail="MongoDB sessions unavailable")

    updated = session_store.get_session(session_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Session inconnue")
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
        raise HTTPException(status_code=404, detail="Session inconnue")
    return SessionResponse.model_validate(updated)


def _pgn_after_move(session_moves: list[dict], san: str) -> str:
    sans = [str(move.get("san", "")) for move in session_moves] + [san]
    parts: list[str] = []
    for index, move_san in enumerate(sans):
        if index % 2 == 0:
            parts.append(f"{index // 2 + 1}. {move_san}")
        else:
            parts[-1] = f"{parts[-1]} {move_san}"
    return " ".join(parts)
