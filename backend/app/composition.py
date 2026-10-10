"""Runtime composition for the FastAPI application.

This module is the composition root: adapters are constructed here, while
services and orchestration modules receive already-built dependencies.
"""

from dataclasses import dataclass
import asyncio
import logging

from functools import lru_cache

from backend.app.core.settings import LLMSettings, Settings, get_settings
from backend.app.services.coach import CoachService, LlmCoachService
from backend.app.services.embeddings import OllamaEmbeddingProvider
from backend.app.services.lichess import LichessExplorerClient
from backend.app.services.youtube import YouTubeClient
from backend.app.services.llm import OpenAICompatLLMProvider, OllamaLLMProvider
from backend.app.services.milvus import MilvusStore
from backend.app.services.mongo import MongoConnection
from backend.app.services.rag import RagService
from backend.app.services.cache_store import CacheStore
from backend.app.services.run_store import RunStore
from backend.app.services.session_store import SessionStore
from backend.app.services.stockfish import StockfishService
from backend.app.services.intent_router import IntentRouter, JevIntentClassifier
from backend.app.services.opening_tree import DEFAULT_OUTPUT_DIR, OpeningTree, OpeningTreeError


logger = logging.getLogger("backend.composition")


@dataclass
class RuntimeServices:
    """Long-lived adapters and application services for one FastAPI process."""

    lichess_client: LichessExplorerClient
    llm_provider: OllamaLLMProvider | OpenAICompatLLMProvider
    coach_service: CoachService
    rag_service: RagService
    mongo: MongoConnection
    cache_store: CacheStore
    session_store: SessionStore
    run_store: RunStore
    stockfish_service: StockfishService
    opening_tree: OpeningTree | None
    intent_router: IntentRouter
    langgraph_enabled: bool
    youtube_client: YouTubeClient | None = None

    def close(self) -> None:
        """Release network clients owned by the runtime services."""
        resources = (
            ("lichess", self.lichess_client),
            ("llm", self.llm_provider),
            ("rag", self.rag_service),
            ("intent_router", self.intent_router),
            ("mongo", self.mongo),
        )
        if self.youtube_client is not None:
            resources = (*resources, ("youtube", self.youtube_client))
        for name, resource in resources:
            try:
                resource.close()
            except Exception as exc:  # noqa: BLE001 - close every resource
                logger.warning("%s shutdown failed", name, extra={"error": str(exc)})

    async def warmup(self) -> None:
        """Warm independent providers concurrently without blocking the event loop."""
        results = await asyncio.gather(
            asyncio.to_thread(self.llm_provider.warmup),
            asyncio.to_thread(self.rag_service.warmup),
            return_exceptions=True,
        )
        for name, result in zip(("llm", "embeddings"), results):
            if isinstance(result, Exception):
                logger.warning(
                    "%s warmup failed; will retry on first use",
                    name,
                    extra={"error": str(result)},
                )


def build_llm_provider(llm_settings: LLMSettings) -> OllamaLLMProvider | OpenAICompatLLMProvider:
    """Build the adapter for the selected provider."""
    if llm_settings.provider != "ollama":
        return OpenAICompatLLMProvider(llm_settings)
    return OllamaLLMProvider(llm_settings)


def build_opening_tree() -> OpeningTree | None:
    try:
        return OpeningTree.from_snapshot_dir(DEFAULT_OUTPUT_DIR)
    except OpeningTreeError as exc:
        logger.warning("OpeningTree unavailable for RAG retrieval: %s", exc)
        return None


def build_intent_router(settings: Settings) -> IntentRouter:
    primary = JevIntentClassifier(settings=settings.typesafe) if settings.typesafe.enabled else None
    return IntentRouter(primary=primary, medium_confidence=settings.typesafe.medium_confidence)


@lru_cache
def default_stockfish_service() -> StockfishService:
    return StockfishService(get_settings().stockfish)


@lru_cache
def default_youtube_client() -> YouTubeClient:
    return YouTubeClient(get_settings().youtube)


@lru_cache
def default_opening_tree() -> OpeningTree | None:
    return build_opening_tree()


@lru_cache
def default_intent_router() -> IntentRouter:
    return build_intent_router(get_settings())


@lru_cache
def default_langgraph_enabled() -> bool:
    return get_settings().orchestration.langgraph_enabled


def build_rag_service(settings: Settings) -> RagService:
    """Build the embedding adapter and its Milvus-backed retrieval service."""
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


def build_runtime_services(settings: Settings) -> RuntimeServices:
    """Construct all process-scoped services from validated settings."""
    coach_llm_settings = settings.llm.model_copy(
        update={"timeout_seconds": settings.llm.coach_timeout_seconds}
    )
    llm_provider = build_llm_provider(coach_llm_settings)
    mongo = MongoConnection(settings.mongodb)
    database = mongo.database()
    return RuntimeServices(
        lichess_client=LichessExplorerClient(settings.lichess),
        youtube_client=YouTubeClient(settings.youtube),
        llm_provider=llm_provider,
        coach_service=LlmCoachService(provider=llm_provider),
        rag_service=build_rag_service(settings),
        mongo=mongo,
        cache_store=CacheStore(database=database, settings=settings.mongodb),
        session_store=SessionStore(database=database),
        run_store=RunStore(database=database),
        stockfish_service=StockfishService(settings.stockfish),
        opening_tree=build_opening_tree(),
        intent_router=build_intent_router(settings),
        langgraph_enabled=settings.orchestration.langgraph_enabled,
    )
