"""Finnhub-backed provider. Activated only when FINNHUB_API_KEY is set;
first in the preference order for real-time quotes since Finnhub's free
tier is documented as real-time for US equities (unlike yfinance's 15-
minute-delayed feed).

Implemented against Finnhub's documented REST contract - NOT verified
against a live key, since none is configured in this deployment. If the
real response shape differs, this is the one file that needs to change.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from src.data.providers.base import HistoryBar, Provider, Quote, RateLimiter
from src.utils.logging import get_logger

log = get_logger(__name__)

BASE_URL = "https://finnhub.io/api/v1"
TIMEOUT_SECONDS = 10.0


class FinnhubProvider(Provider):
    name = "finnhub"

    def __init__(self, api_key: str, requests_per_minute: int):
        self._api_key = api_key
        self._limiter = RateLimiter(requests_per_minute)

    async def get_quote(self, symbol: str) -> Quote | None:
        if not self._limiter.try_acquire():
            log.warning("finnhub.rate_limited", symbol=symbol)
            return None

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                res = await client.get(
                    f"{BASE_URL}/quote",
                    params={"symbol": symbol, "token": self._api_key},
                )
                res.raise_for_status()
                data = res.json()
        except Exception as exc:
            log.warning("finnhub.quote_failed", symbol=symbol, error=str(exc))
            return None

        current = data.get("c")
        prev_close = data.get("pc")
        # Finnhub returns all-zero fields for an unknown/unsupported symbol
        # rather than an HTTP error - that's "no data", not a real quote.
        if not current or not prev_close:
            return None

        change = data.get("d")
        change_percent = data.get("dp")
        if change is None:
            change = current - prev_close
        if change_percent is None:
            change_percent = (change / prev_close) * 100 if prev_close else 0.0

        return Quote(
            symbol=symbol,
            price=current,
            change=change,
            change_percent=change_percent,
            previous_close=prev_close,
            timestamp=datetime.now(timezone.utc),
            delayed=False,
            degraded=False,
            source=self.name,
        )

    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        # Finnhub's free tier has no batch quote endpoint - fetch one at a
        # time, each still governed by the same rate limiter so a large
        # watchlist can't blow through the per-minute budget.
        results: dict[str, Quote] = {}
        for symbol in symbols:
            quote = await self.get_quote(symbol)
            if quote is not None:
                results[symbol] = quote
        return results

    async def get_history(
        self, symbol: str, start: datetime, end: datetime
    ) -> list[HistoryBar]:
        # Finnhub's free tier does not include historical candles for US
        # equities - by design, this provider only ever serves quotes.
        # yfinance is the sole /history source (see manager.py).
        return []
