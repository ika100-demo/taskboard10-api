"""FastAPI entry point for taskboard10-api."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from . import __version__
from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .tasks import router as tasks_router
from .tasks.pg_store import PostgresTaskStore
from .tracing import configure_tracing, tracing_enabled

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
if tracing_enabled():
    configure_tracing()


class HealthResponse(BaseModel):
    status: str


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    close = getattr(app.state.task_store, "close", None)
    if callable(close):
        close()


def create_app() -> FastAPI:
    """Build an app instance; reads DATABASE_URL now, does no database I/O."""
    app = FastAPI(title="taskboard10-api", version=__version__, lifespan=_lifespan)
    app.add_middleware(MetricsMiddleware)
    app.include_router(tasks_router)
    app.state.task_store = PostgresTaskStore.from_env()

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Liveness probe — returns 200 as long as the process is responding."""
        return HealthResponse(status="ok")

    @app.get("/ready", response_model=HealthResponse)
    def ready() -> HealthResponse:
        """Readiness probe — returns 200 when the service is ready to accept traffic."""
        return HealthResponse(status="ready")

    @app.get("/ping")
    def ping() -> dict[str, str]:
        """Simple ping endpoint."""
        return {"pong": "taskboard10-api"}

    @app.get("/metrics")
    def metrics() -> Response:
        """Prometheus scrape endpoint."""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
