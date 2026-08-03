"""Alpha Vantage-backed provider. Activated only when ALPHAVANTAGE_API_KEY
is set; second in the preference order (after Finnhub) for real-time
quotes. Free tier is notoriously stingy - 5 requests/minute is the
documented ceiling, hence the conservative default in settings.py.

Implemented against Alpha Vantage's documented GLOBAL_QUOTE contract - NOT
verified against a live key, since none is configured in this deployment.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from src.data.providers.base import HistoryBar, Provider, Quote, RateLimiter
from src.utils.logging import get_logger

log = get_logger(__name__)

BASE_URL = "https://www.alphavantage.co/query"
TIMEOUT_SECONDS = 10.0


def _parse_percent(raw: str) -> float:
    return float(raw.rstrip("%"))


class AlphaVantageProvider(Provider):
    name = "alphavantage"

    def __init__(self, api_key: str, requests_per_minute: int):
        self._api_key = api_key
        self._limiter = RateLimiter(requests_per_minute)

    async def get_quote(self, symbol: str) -> Quote | None:
        if not self._limiter.try_acquire():
            log.warning("alphavantage.rate_limited", symbol=symbol)
            return None

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                res = await client.get(
                    BASE_URL,
                    params={
                        "function": "GLOBAL_QUOTE",
                        "symbol": symbol,
                        "apikey": self._api_key,
                    },
                )
                res.raise_for_status()
                data = res.json()
        except Exception as exc:
            log.warning("alphavantage.quote_failed", symbol=symbol, error=str(exc))
            return None

        # Rate-limit/invalid-key responses come back as {"Note": ...} or
        # {"Information": ...} with a 200 status, not an HTTP error - the
        # absence of "Global Quote" IS the failure signal here.
        quote_data = data.get("Global Quote")
        if not quote_data:
            log.warning("alphavantage.no_quote_data", symbol=symbol, response=data)
            return None

        try:
            price = float(quote_data["05. price"])
            prev_close = float(quote_data["08. previous close"])
            change = float(quote_data["09. change"])
            change_percent = _parse_percent(quote_data["10. change percent"])
        except (KeyError, ValueError) as exc:
            log.warning("alphavantage.parse_failed", symbol=symbol, error=str(exc))
            return None

        return Quote(
            symbol=symbol,
            price=price,
            change=change,
            change_percent=change_percent,
            previous_close=prev_close,
            timestamp=datetime.now(timezone.utc),
            delayed=False,
            degraded=False,
            source=self.name,
        )

    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        # No batch endpoint on the free tier, and a 5/min budget makes this
        # provider a poor fit for a large watchlist regardless - callers
        # (manager.py) should treat this as a slow last resort, not the
        # primary path for a full-watchlist refresh.
        results: dict[str, Quote] = {}
        for symbol in symbols:
            quote = await self.get_quote(symbol)
            if quote is not None:
                results[symbol] = quote
        return results

    async def get_history(
        self, symbol: str, start: datetime, end: datetime
    ) -> list[HistoryBar]:
        # TIME_SERIES_DAILY exists on the free tier, but yfinance is the
        # sole /history source in this app (see manager.py) - no need for a
        # second, much-more-rate-limited path to the same data shape.
        return []
