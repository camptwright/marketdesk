from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import require_bearer_token
from src.data.db_client import get_db
from src.data.providers.manager import ProviderManager, get_provider_manager
from src.models.orm import PriceSnapshot
from src.utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(require_bearer_token)], tags=["history"])


class HistoryRange(str, Enum):
    one_month = "1mo"
    six_months = "6mo"
    one_year = "1y"
    five_years = "5y"


_RANGE_DAYS = {
    HistoryRange.one_month: 30,
    HistoryRange.six_months: 182,
    HistoryRange.one_year: 365,
    HistoryRange.five_years: 365 * 5,
}


@router.get("/history/{symbol}")
async def get_history(
    symbol: str,
    range: HistoryRange = HistoryRange.one_month,
    db: AsyncSession = Depends(get_db),
    manager: ProviderManager = Depends(get_provider_manager),
) -> list[dict]:
    symbol = symbol.strip().upper()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=_RANGE_DAYS[range])

    earliest_result = await db.execute(
        select(func.min(PriceSnapshot.ts)).where(PriceSnapshot.symbol == symbol)
    )
    earliest = earliest_result.scalar_one_or_none()

    # "Backfilled from the provider on first request": no coverage at all,
    # or existing coverage doesn't reach as far back as this range needs.
    if earliest is None or earliest > start:
        bars = await manager.get_history(symbol, start, end)
        if bars:
            for bar in bars:
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
                await db.execute(stmt)
            await db.commit()
        elif earliest is None:
            # Nothing stored and the provider gave us nothing either -
            # genuinely no data for this symbol/range, not a crash.
            raise HTTPException(
                status_code=502, detail=f"no history available for {symbol}"
            )

    result = await db.execute(
        select(PriceSnapshot)
        .where(PriceSnapshot.symbol == symbol, PriceSnapshot.ts >= start)
        .order_by(PriceSnapshot.ts.asc())
    )
    rows = result.scalars().all()
    return [
        {
            "ts": r.ts,
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": r.volume,
        }
        for r in rows
    ]
