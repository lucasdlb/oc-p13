from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.api.routes import router
from backend.app.core.logging import configure_logging
from backend.app.core.settings import get_settings
from backend.app.middleware.request_logging import RequestLoggingMiddleware
from backend.app.services.mongo import get_mongo


settings = get_settings()
configure_logging(settings.logging)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
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
