"""FastAPI app entrypoint. Dockerfile's CMD points uvicorn at
`src.api.main:app`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routers import health, history, movers, portfolio, positions, quotes, watchlist
from src.data.db_client import dispose_engine
from src.scheduler.app import shutdown_scheduler, start_scheduler
from src.utils.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    start_scheduler()
    yield
    shutdown_scheduler()
    await dispose_engine()


app = FastAPI(title="marketdesk", lifespan=lifespan)

app.include_router(health.router)
app.include_router(quotes.router)
app.include_router(watchlist.router)
app.include_router(positions.router)
app.include_router(portfolio.router)
app.include_router(movers.router)
app.include_router(history.router)
