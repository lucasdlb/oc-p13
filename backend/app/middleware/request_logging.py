from time import perf_counter
from uuid import uuid4
import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from backend.app.core.logging import request_id_var


logger = logging.getLogger("backend.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, request_id_header: str) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.request_id_header = request_id_header

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get(self.request_id_header) or uuid4().hex
        token = request_id_var.set(request_id)
        start = perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((perf_counter() - start) * 1000, 2)
            logger.exception(
                "Unhandled request error",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)
            raise

        duration_ms = round((perf_counter() - start) * 1000, 2)
        response.headers[self.request_id_header] = request_id
        logger.info(
            "HTTP request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        request_id_var.reset(token)
        return response
