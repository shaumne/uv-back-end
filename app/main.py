"""
FastAPI application factory.

Registers:
- CORS middleware (origins controlled via [Settings.allowed_origins])
- API key authentication middleware ([ApiKeyMiddleware])
- Slowapi rate limiting (10/min on /analyze, 60/min on /detect)
- /api/v1 router with the /analyze and /detect endpoints
- Global exception handlers for unhandled errors
"""
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .api.v1.endpoints.analyze import router as analyze_router
from .api.v1.endpoints.detect import router as detect_router
from .core.config import settings
from .core.rate_limiter import limiter
from .core.logging import configure_logging, logger
from .middleware.auth import ApiKeyMiddleware

def create_app() -> FastAPI:
    configure_logging(debug=settings.debug)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
    )

    # ── Rate limiter ──────────────────────────────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["POST", "GET"],
        allow_headers=["*"],
    )

    # ── API key authentication ────────────────────────────────────────────────
    # No-op when settings.api_key is empty (local development).
    app.add_middleware(ApiKeyMiddleware)

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(analyze_router, prefix="/api/v1")
    app.include_router(detect_router, prefix="/api/v1")

    # ── Global exception handler ──────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled exception at %s", request.url)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "An unexpected server error occurred.",
                "code": "INTERNAL_ERROR",
            },
        )

    @app.get("/health", tags=["Monitoring"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "version": settings.app_version}

    return app


app = create_app()
