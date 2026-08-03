from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.auth import require_bearer_token
from src.data.providers.manager import ProviderManager, get_provider_manager

router = APIRouter(dependencies=[Depends(require_bearer_token)], tags=["quotes"])


def _serialize(quote) -> dict:
    return {
        "symbol": quote.symbol,
        "price": quote.price,
        "change": quote.change,
        "change_percent": quote.change_percent,
        "previous_close": quote.previous_close,
        "timestamp": quote.timestamp,
        "delayed": quote.delayed,
        "degraded": quote.degraded,
        "source": quote.source,
    }


@router.get("/quote/{symbol}")
async def get_quote(
    symbol: str, manager: ProviderManager = Depends(get_provider_manager)
) -> dict:
    quote = await manager.get_quote(symbol.upper())
    if quote is None:
        raise HTTPException(
            status_code=502,
            detail=f"no provider returned data for {symbol.upper()}",
        )
    return _serialize(quote)


@router.get("/quotes")
async def get_quotes(
    symbols: str = Query(..., description="Comma-separated symbols, e.g. AAPL,MSFT"),
    manager: ProviderManager = Depends(get_provider_manager),
) -> dict:
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="symbols must be a non-empty list")
    quotes = await manager.get_quotes(symbol_list)
    return {symbol: _serialize(q) for symbol, q in quotes.items()}
