from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import require_bearer_token
from src.data.db_client import get_db
from src.data.providers.manager import ProviderManager, get_provider_manager
from src.models.orm import Position
from src.utils.portfolio_math import PositionQuote, compute_portfolio_summary

router = APIRouter(
    prefix="/portfolio", dependencies=[Depends(require_bearer_token)], tags=["portfolio"]
)


@router.get("/summary")
async def portfolio_summary(
    db: AsyncSession = Depends(get_db),
    manager: ProviderManager = Depends(get_provider_manager),
) -> dict:
    result = await db.execute(select(Position).where(Position.closed_at.is_(None)))
    positions = result.scalars().all()

    if not positions:
        return {
            "total_market_value": 0.0,
            "total_day_change_dollar": 0.0,
            "total_day_change_percent": 0.0,
            "total_unrealized_pl_dollar": 0.0,
            "total_unrealized_pl_percent": 0.0,
            "positions": [],
            "allocation_by_symbol": {},
            "best_position_today": None,
            "worst_position_today": None,
            "degraded": False,
        }

    symbols = sorted({p.symbol for p in positions})
    quotes = await manager.get_quotes(symbols)

    position_quotes: list[PositionQuote] = []
    position_ids: list[str] = []
    any_degraded = False
    for position in positions:
        quote = quotes.get(position.symbol)
        if quote is None:
            # A symbol with no quote at all (every provider failed, no
            # cache either) is excluded from the math rather than treated
            # as a $0 position, which would corrupt market value and P/L.
            continue
        any_degraded = any_degraded or quote.degraded
        position_quotes.append(
            PositionQuote(
                symbol=position.symbol,
                shares=float(position.shares),
                cost_basis=float(position.cost_basis),
                current_price=quote.price,
                previous_close=quote.previous_close,
            )
        )
        position_ids.append(str(position.id))

    summary = compute_portfolio_summary(position_quotes)

    positions_payload = [
        {
            "id": pid,
            "symbol": p.symbol,
            "shares": p.shares,
            "cost_basis": p.cost_basis,
            "current_price": p.current_price,
            "market_value": p.market_value,
            "day_change_dollar": p.day_change_dollar,
            "day_change_percent": p.day_change_percent,
            "unrealized_pl_dollar": p.unrealized_pl_dollar,
            "unrealized_pl_percent": p.unrealized_pl_percent,
        }
        for pid, p in zip(position_ids, summary.positions, strict=True)
    ]

    best = max(positions_payload, key=lambda p: p["day_change_percent"], default=None)
    worst = min(positions_payload, key=lambda p: p["day_change_percent"], default=None)

    return {
        "total_market_value": summary.total_market_value,
        "total_day_change_dollar": summary.total_day_change_dollar,
        "total_day_change_percent": summary.total_day_change_percent,
        "total_unrealized_pl_dollar": summary.total_unrealized_pl_dollar,
        "total_unrealized_pl_percent": summary.total_unrealized_pl_percent,
        "positions": positions_payload,
        "allocation_by_symbol": summary.allocation_by_symbol,
        "best_position_today": best,
        "worst_position_today": worst,
        "degraded": any_degraded,
    }
