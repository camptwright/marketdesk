from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import require_bearer_token
from src.api.routers.quotes import _serialize
from src.data.db_client import get_db
from src.data.providers.manager import ProviderManager, get_provider_manager
from src.models.orm import Watchlist

router = APIRouter(dependencies=[Depends(require_bearer_token)], tags=["movers"])


@router.get("/movers")
async def movers(
    db: AsyncSession = Depends(get_db),
    manager: ProviderManager = Depends(get_provider_manager),
) -> list[dict]:
    """Watchlist, sorted by |day change %| descending - the "what moved
    today" view. Symbols with no quote available (every provider failed,
    no cache) are omitted rather than shown as a fake zero move."""
    result = await db.execute(select(Watchlist.symbol))
    symbols = [row[0] for row in result.all()]
    if not symbols:
        return []

    quotes = await manager.get_quotes(symbols)
    rows = [_serialize(q) for q in quotes.values()]
    rows.sort(key=lambda r: abs(r["change_percent"]), reverse=True)
    return rows
