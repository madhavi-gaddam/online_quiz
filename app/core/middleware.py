import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        started_at = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            process_time_ms = (time.perf_counter() - started_at) * 1000
            logger.exception(
                "Unhandled request exception method=%s path=%s process_time_ms=%.2f",
                request.method,
                request.url.path,
                process_time_ms,
            )
            raise

        process_time_ms = (time.perf_counter() - started_at) * 1000
        logger.info(
            "Request completed method=%s path=%s status_code=%s process_time_ms=%.2f",
            request.method,
            request.url.path,
            response.status_code,
            process_time_ms,
        )
        return response
