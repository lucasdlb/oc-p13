from fastapi import FastAPI

from backend.app.api.routes import router
from backend.app.core.logging import configure_logging
from backend.app.core.settings import get_settings
from backend.app.middleware.request_logging import RequestLoggingMiddleware


settings = get_settings()
configure_logging(settings.logging)

app = FastAPI(title="POC Agent d'ouvertures FFE")
app.add_middleware(
    RequestLoggingMiddleware,
    request_id_header=settings.logging.request_id_header,
)

app.include_router(router)
