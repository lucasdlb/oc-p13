import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.api.routes import router
from backend.app.core.logging import configure_logging
from backend.app.core.settings import LLMSettings, get_settings
from backend.app.middleware.request_logging import RequestLoggingMiddleware
from backend.app.services.coach import LlmCoachService
from backend.app.services.embeddings import OllamaEmbeddingProvider
from backend.app.services.lichess import LichessExplorerClient
from backend.app.services.llm import OpenAICompatLLMProvider, OllamaLLMProvider
from backend.app.services.milvus import MilvusStore
from backend.app.services.mongo import get_mongo
from backend.app.services.rag import RagService


logger = logging.getLogger(__name__)
settings = get_settings()
configure_logging(settings.logging)


def _build_rag_service() -> RagService:
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


def _build_llm_provider(llm_settings: LLMSettings) -> OllamaLLMProvider | OpenAICompatLLMProvider:
    if llm_settings.provider != "ollama":
        return OpenAICompatLLMProvider(llm_settings)
    return OllamaLLMProvider(llm_settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.lichess_client = LichessExplorerClient(settings.lichess)
    # Coach calls are latency-sensitive: give them a tighter timeout than other
    # LLM uses so a slow/local model cannot hold the whole response back.
    coach_llm_settings = settings.llm.model_copy(
        update={"timeout_seconds": settings.llm.coach_timeout_seconds}
    )
    app.state.llm_provider = _build_llm_provider(coach_llm_settings)
    if isinstance(app.state.llm_provider, OllamaLLMProvider):
        try:
            await asyncio.to_thread(app.state.llm_provider.warmup)
            logger.info("Ollama LLM model warmed up", extra={"model": coach_llm_settings.model})
        except Exception as exc:  # noqa: BLE001 - preserve the existing runtime fallback
            logger.warning(
                "Ollama LLM warmup failed; the first request will retry model loading",
                extra={"model": coach_llm_settings.model, "error": str(exc)},
            )
    app.state.coach_service = LlmCoachService(provider=app.state.llm_provider)
    app.state.rag_service = _build_rag_service()
    try:
        yield
    finally:
        app.state.lichess_client.close()
        app.state.llm_provider.close()
        app.state.rag_service._embedding_provider.close()
        # Only close a connection that was actually created: calling get_mongo()
        # unconditionally would attempt a new connection at shutdown.
        if get_mongo.cache_info().currsize:
            get_mongo().close()


app = FastAPI(title="POC Agent d'ouvertures FFE", lifespan=lifespan)
app.add_middleware(
    RequestLoggingMiddleware,
    request_id_header=settings.logging.request_id_header,
)

app.include_router(router)
