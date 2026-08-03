"""Job bodies. Every job opens its own DB session via `get_session()` and
disposes of it when done - APScheduler's `AsyncIOScheduler` runs these as
coroutines on the same event loop as the API (no forking, no Celery), so
there's no constraint-#1-style fork-safety concern; this is just normal
"don't hold a session open longer than one unit of work" hygiene.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from config.settings import get_settings
from src.data.db_client import get_session
from src.data.providers.manager import get_provider_manager
from src.models.orm import Position, PriceSnapshot, Watchlist
from src.utils.logging import get_logger

log = get_logger(__name__)


async def _tracked_symbols() -> list[str]:
    """Watchlist symbols plus OPEN positions - a closed position's price
    history is already fixed at close time and doesn't need continued
    snapshotting."""
    async with get_session() as db:
        watchlist_result = await db.execute(select(Watchlist.symbol))
        position_result = await db.execute(
            select(Position.symbol).where(Position.closed_at.is_(None))
        )
        symbols = {row[0] for row in watchlist_result.all()} | {
            row[0] for row in position_result.all()
        }
    return sorted(symbols)


async def snapshot_all() -> int:
    """Runs every 30 min during market hours plus once at EOD (see
    scheduler/app.py for the exact cron triggers). Fetches a real
    intraday OHLCV bar per tracked symbol and stores it - ON CONFLICT DO
    NOTHING because re-running within the same instant (manual trigger
    racing the schedule, a retry, etc.) should never crash on the (symbol,
    ts) primary key.
    """
    symbols = await _tracked_symbols()
    if not symbols:
        log.info("snapshot_all.no_symbols")
        return 0

    manager = get_provider_manager()
    stored = 0
    async with get_session() as db:
        for symbol in symbols:
            bar = await manager.get_current_bar(symbol)
            if bar is None:
                log.warning("snapshot_all.no_bar", symbol=symbol)
                continue
            stmt = (
                pg_insert(PriceSnapshot)
                .values(
                    symbol=symbol,
                    ts=bar.ts,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                )
                .on_conflict_do_nothing(constraint="price_snapshots_pkey")
            )
            result = await db.execute(stmt)
            stored += result.rowcount or 0
        await db.commit()

    log.info("snapshot_all.complete", symbols=len(symbols), stored=stored)
    return stored


async def prune_old_snapshots() -> int:
    """Runs daily. Keeps `price_snapshots` from growing without bound on a
    resource-constrained host - 2 years of 30-min bars across a watchlist
    is already a meaningful amount of data; there's no product need to
    keep it forever."""
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.snapshot_retention_days)

    async with get_session() as db:
        result = await db.execute(delete(PriceSnapshot).where(PriceSnapshot.ts < cutoff))
        await db.commit()

    deleted = result.rowcount or 0
    log.info("prune_old_snapshots.complete", deleted=deleted, cutoff=cutoff.isoformat())
    return deleted
