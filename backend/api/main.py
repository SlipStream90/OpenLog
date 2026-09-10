"""FastAPI application -- the local API on http://localhost:3141.

Composition root: this is the one module that wires the database, the telemetry
engine and the routers together.

Run with:
    uv run uvicorn backend.api.main:app --port 3141
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routers import analytics, charts, export, files, search, sessions, stats, timeline
from backend.database.session import init_db
from backend.telemetry import TelemetryEngine

logger = logging.getLogger(__name__)

#: Explicit localhost origins only -- never "*". Nothing off this machine has any
#: business reading a local telemetry database (PRD section 21).
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

#: Lets the test suite build the app without spawning background watchers.
DISABLE_TELEMETRY_ENV = "AI_OBSERVATORY_DISABLE_TELEMETRY"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the telemetry engine alongside the API -- one process, no daemon.

    Every startup step is individually guarded: a telemetry failure must still
    leave the dashboard and API serving (PRD section 25). The one exception is
    `init_db`, since without a database there is nothing to serve.
    """
    init_db()

    engine: TelemetryEngine | None = None
    if os.environ.get(DISABLE_TELEMETRY_ENV, "").strip().lower() not in ("1", "true", "yes"):
        engine = TelemetryEngine()
        try:
            await engine.start()
        except Exception:
            logger.exception("Telemetry engine failed to start; API continues serving")
            engine = None
    app.state.telemetry = engine

    try:
        yield
    finally:
        if engine is not None:
            try:
                await engine.stop()
            except Exception:
                logger.exception("Telemetry engine shutdown was not clean")


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI Observatory",
        description="Local-first observability for AI coding agents.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    app.include_router(sessions.router)
    app.include_router(timeline.router)
    app.include_router(files.router)
    app.include_router(stats.router)
    app.include_router(search.router)
    app.include_router(charts.router)
    app.include_router(analytics.router)
    app.include_router(export.router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    # Bound to 127.0.0.1, not 0.0.0.0: this API must not be reachable from the
    # local network.
    uvicorn.run(app, host="127.0.0.1", port=3141)
