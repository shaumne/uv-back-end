"""
API key authentication middleware.

Validates the `X-API-Key` request header against the key configured in
[Settings.api_key]. Requests without a matching key receive a 403 response.

Bypass behaviour:
  - When [Settings.api_key] is empty or None, authentication is disabled
    (useful for local development without a configured key).
  - The `/health` endpoint is always exempt so load-balancer health checks
    do not require credentials.

Configuration:
  Set the API_KEY environment variable (or .env file entry) before deployment.
"""
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..core.config import settings
from ..core.logging import logger

# Paths that bypass API key validation.
_EXEMPT_PATHS: frozenset[str] = frozenset({
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
})


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces X-API-Key authentication.

    Applied to all paths except those in [_EXEMPT_PATHS].
    Disabled transparently when [Settings.api_key] is not configured.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # Skip validation when API key protection is not configured.
        configured_key = getattr(settings, "api_key", None)
        if not configured_key:
            return await call_next(request)

        # Exempt health-check and docs paths.
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        request_key = request.headers.get("X-API-Key", "")

        if request_key != configured_key:
            logger.warning(
                "Rejected request to %s — invalid or missing X-API-Key.",
                request.url.path,
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "detail": "Invalid or missing API key.",
                    "code": "FORBIDDEN",
                },
            )

        return await call_next(request)
