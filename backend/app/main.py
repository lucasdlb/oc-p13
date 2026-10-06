import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from backend.app.api.routes import router
from backend.app.composition import RuntimeServices, build_runtime_services
from backend.app.core.logging import configure_logging
from backend.app.core.settings import Settings, get_settings
from backend.app.middleware.request_logging import RequestLoggingMiddleware


logger = logging.getLogger(__name__)


def make_lifespan(settings: Settings):
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime: RuntimeServices = build_runtime_services(settings)
        app.state.runtime = runtime
        await runtime.warmup()
        try:
            yield
        finally:
            runtime.close()

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.logging)
    app = FastAPI(title="POC Agent d'ouvertures FFE", lifespan=make_lifespan(resolved_settings))
    app.add_middleware(
        RequestLoggingMiddleware,
        request_id_header=resolved_settings.logging.request_id_header,
    )
    app.include_router(router)
    return app


app = create_app()
