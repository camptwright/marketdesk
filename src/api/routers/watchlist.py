from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import require_bearer_token
from src.data.db_client import get_db
from src.models.orm import Watchlist

router = APIRouter(
    prefix="/watchlist", dependencies=[Depends(require_bearer_token)], tags=["watchlist"]
)


class WatchlistRow(BaseModel):
    symbol: str
    added_at: datetime
    notes: str | None


class AddWatchlistRequest(BaseModel):
    symbol: str
    notes: str | None = None


@router.get("")
async def list_watchlist(db: AsyncSession = Depends(get_db)) -> list[WatchlistRow]:
    result = await db.execute(select(Watchlist).order_by(Watchlist.symbol))
    return [
        WatchlistRow(symbol=w.symbol, added_at=w.added_at, notes=w.notes)
        for w in result.scalars().all()
    ]


@router.post("", status_code=201)
async def add_to_watchlist(
    request: AddWatchlistRequest, db: AsyncSession = Depends(get_db)
) -> WatchlistRow:
    symbol = request.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    stmt = (
        pg_insert(Watchlist)
        .values(symbol=symbol, notes=request.notes)
        .on_conflict_do_update(
            index_elements=["symbol"], set_={"notes": request.notes}
        )
        .returning(Watchlist)
    )
    result = await db.execute(stmt)
    await db.commit()
    row = result.first()
    assert row is not None
    watchlist_row = row[0]
    return WatchlistRow(
        symbol=watchlist_row.symbol,
        added_at=watchlist_row.added_at,
        notes=watchlist_row.notes,
    )


@router.delete("/{symbol}", status_code=204)
async def remove_from_watchlist(symbol: str, db: AsyncSession = Depends(get_db)) -> None:
    result = await db.execute(
        select(Watchlist).where(Watchlist.symbol == symbol.strip().upper())
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="symbol not on watchlist")
    await db.delete(row)
    await db.commit()
