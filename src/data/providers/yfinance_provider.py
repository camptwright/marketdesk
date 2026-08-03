"""yfinance-backed provider: the always-available default. Free and
unofficial - it scrapes Yahoo's public endpoints, so it has no documented
SLA and no official support. Every call is wrapped with retries and
collapses to `None`/`[]` on failure rather than raising, per base.py's
contract.

yfinance's own API is synchronous (no native async), so every call here
runs via `asyncio.to_thread` to avoid blocking the event loop - this is a
single-process app with no worker pool to hide a blocking call behind.

Field names verified against a real call (2026-08-03): `Ticker.fast_info`
gives `lastPrice`/`previousClose`/`dayHigh`/`dayLow`/`open`/`lastVolume`;
`yf.download(tickers, group_by="ticker")` returns a MultiIndex DataFrame
keyed `(ticker, field)` with `Open`/`High`/`Low`/`Close`/`Volume`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import yfinance as yf

from src.data.providers.base import HistoryBar, Provider, Quote, RateLimiter
from src.utils.logging import get_logger

log = get_logger(__name__)

MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.5


class YFinanceProvider(Provider):
    name = "yfinance"

    def __init__(self, requests_per_minute: int):
        self._limiter = RateLimiter(requests_per_minute)

    def _fetch_quote_sync(self, symbol: str) -> Quote | None:
        info = yf.Ticker(symbol).fast_info
        price = info.get("lastPrice")
        prev_close = info.get("previousClose")
        if price is None or prev_close is None or prev_close == 0:
            return None
        change = price - prev_close
        return Quote(
            symbol=symbol,
            price=price,
            change=change,
            change_percent=(change / prev_close) * 100,
            previous_close=prev_close,
            timestamp=datetime.now(timezone.utc),
            delayed=True,
            degraded=False,
            source=self.name,
        )

    async def get_quote(self, symbol: str) -> Quote | None:
        if not self._limiter.try_acquire():
            log.warning("yfinance.rate_limited", symbol=symbol)
            return None

        for attempt in range(MAX_RETRIES):
            try:
                return await asyncio.to_thread(self._fetch_quote_sync, symbol)
            except Exception as exc:
                if attempt == MAX_RETRIES - 1:
                    log.warning(
                        "yfinance.quote_failed", symbol=symbol, error=str(exc)
                    )
                    return None
                await asyncio.sleep(BASE_BACKOFF_SECONDS * (2**attempt))
        return None

    def _fetch_quotes_sync(self, symbols: list[str]) -> dict[str, Quote]:
        """One batched call for N symbols rather than N individual ones -
        `Tickers` shares an HTTP session across symbols internally."""
        tickers = yf.Tickers(" ".join(symbols))
        results: dict[str, Quote] = {}
        now = datetime.now(timezone.utc)
        for symbol in symbols:
            try:
                info = tickers.tickers[symbol].fast_info
                price = info.get("lastPrice")
                prev_close = info.get("previousClose")
                if price is None or prev_close is None or prev_close == 0:
                    continue
                change = price - prev_close
                results[symbol] = Quote(
                    symbol=symbol,
                    price=price,
                    change=change,
                    change_percent=(change / prev_close) * 100,
                    previous_close=prev_close,
                    timestamp=now,
                    delayed=True,
                    degraded=False,
                    source=self.name,
                )
            except Exception as exc:
                log.warning("yfinance.batch_quote_failed", symbol=symbol, error=str(exc))
                continue
        return results

    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        if not symbols:
            return {}
        if not self._limiter.try_acquire():
            log.warning("yfinance.rate_limited", symbols=symbols)
            return {}

        for attempt in range(MAX_RETRIES):
            try:
                return await asyncio.to_thread(self._fetch_quotes_sync, symbols)
            except Exception as exc:
                if attempt == MAX_RETRIES - 1:
                    log.warning("yfinance.quotes_failed", error=str(exc))
                    return {}
                await asyncio.sleep(BASE_BACKOFF_SECONDS * (2**attempt))
        return {}

    def _fetch_history_sync(
        self, symbol: str, start: datetime, end: datetime
    ) -> list[HistoryBar]:
        df = yf.Ticker(symbol).history(start=start, end=end, interval="1d", auto_adjust=False)
        bars: list[HistoryBar] = []
        for idx, row in df.iterrows():
            ts = idx.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            bars.append(
                HistoryBar(
                    ts=ts,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                )
            )
        return bars

    async def get_history(
        self, symbol: str, start: datetime, end: datetime
    ) -> list[HistoryBar]:
        if not self._limiter.try_acquire():
            log.warning("yfinance.rate_limited", symbol=symbol, endpoint="history")
            return []

        for attempt in range(MAX_RETRIES):
            try:
                return await asyncio.to_thread(self._fetch_history_sync, symbol, start, end)
            except Exception as exc:
                if attempt == MAX_RETRIES - 1:
                    log.warning("yfinance.history_failed", symbol=symbol, error=str(exc))
                    return []
                await asyncio.sleep(BASE_BACKOFF_SECONDS * (2**attempt))
        return []

    def _fetch_current_bar_sync(self, symbol: str) -> HistoryBar | None:
        """A real intraday OHLCV bar for "right now", used by the snapshot
        scheduler - NOT the same as `get_quote`'s Quote, which is the
        lightweight cross-provider shape the API layer compares against
        Finnhub/Alpha Vantage. `fast_info` genuinely has open/high/low/
        volume for the current session (verified against a real call,
        2026-08-03), which is what a price_snapshots row actually needs.
        """
        info = yf.Ticker(symbol).fast_info
        price = info.get("lastPrice")
        if price is None:
            return None
        return HistoryBar(
            ts=datetime.now(timezone.utc),
            open=info.get("open", price),
            high=info.get("dayHigh", price),
            low=info.get("dayLow", price),
            close=price,
            volume=int(info.get("lastVolume", 0) or 0),
        )

    async def get_current_bar(self, symbol: str) -> HistoryBar | None:
        if not self._limiter.try_acquire():
            log.warning("yfinance.rate_limited", symbol=symbol, endpoint="current_bar")
            return None

        for attempt in range(MAX_RETRIES):
            try:
                return await asyncio.to_thread(self._fetch_current_bar_sync, symbol)
            except Exception as exc:
                if attempt == MAX_RETRIES - 1:
                    log.warning("yfinance.current_bar_failed", symbol=symbol, error=str(exc))
                    return None
                await asyncio.sleep(BASE_BACKOFF_SECONDS * (2**attempt))
        return []
