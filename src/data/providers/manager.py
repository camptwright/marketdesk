"""Orchestrates the provider preference order, the 10-minute quote cache,
and graceful degradation when every configured provider fails.

Preference order for quotes: Finnhub (if FINNHUB_API_KEY set) > Alpha
Vantage (if ALPHAVANTAGE_API_KEY set) > yfinance (always available). Each
provider already treats its own failures as "return None/[]", so this
class's job is purely sequencing and caching, not error handling.

/history is served by yfinance ALONE, never the other two - see each
provider's own `get_history` docstring for why (no free-tier bulk OHLCV on
either Finnhub or Alpha Vantage worth using over what Yahoo already gives
for free).
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime
from functools import lru_cache

from config.settings import Settings, get_settings
from src.data.providers.alphavantage_provider import AlphaVantageProvider
from src.data.providers.base import HistoryBar, Provider, Quote
from src.data.providers.finnhub_provider import FinnhubProvider
from src.data.providers.yfinance_provider import YFinanceProvider
from src.utils.logging import get_logger

log = get_logger(__name__)


class ProviderManager:
    def __init__(
        self,
        settings: Settings,
        *,
        quote_providers: list[Provider] | None = None,
        history_provider: Provider | None = None,
    ):
        """`quote_providers`/`history_provider` are test seams - real usage
        (via `get_provider_manager()`) never passes them, letting this
        constructor build the real Finnhub/Alpha Vantage/yfinance stack
        from settings. Tests pass `FakeProvider` instances instead, so
        preference-order/caching/fallback logic can be verified without a
        network call, real or otherwise.
        """
        if quote_providers is not None:
            self._quote_providers = quote_providers
        else:
            self._quote_providers = []
            if settings.finnhub_api_key:
                self._quote_providers.append(
                    FinnhubProvider(
                        settings.finnhub_api_key, settings.finnhub_requests_per_minute
                    )
                )
            if settings.alphavantage_api_key:
                self._quote_providers.append(
                    AlphaVantageProvider(
                        settings.alphavantage_api_key,
                        settings.alphavantage_requests_per_minute,
                    )
                )
            self._quote_providers.append(
                YFinanceProvider(settings.yfinance_requests_per_minute)
            )

        self._history_provider = (
            history_provider if history_provider is not None else self._quote_providers[-1]
        )

        self._cache_seconds = settings.quote_cache_seconds
        self._cache: dict[str, tuple[Quote, float]] = {}

    def _cached(self, symbol: str) -> Quote | None:
        entry = self._cache.get(symbol)
        if entry is None:
            return None
        quote, cached_at = entry
        if time.time() - cached_at < self._cache_seconds:
            return quote
        return None

    def _store(self, quote: Quote) -> None:
        self._cache[quote.symbol] = (quote, time.time())

    async def get_quote(self, symbol: str) -> Quote | None:
        cached = self._cached(symbol)
        if cached is not None:
            return cached

        for provider in self._quote_providers:
            quote = await provider.get_quote(symbol)
            if quote is not None:
                self._store(quote)
                return quote

        # Every provider failed. A stale cache entry (even past its 10-
        # minute freshness window) is still more useful than nothing to a
        # dashboard - but it MUST be labeled degraded, never silently
        # served as if it were fresh.
        stale = self._cache.get(symbol)
        if stale is not None:
            log.warning("provider_manager.serving_stale", symbol=symbol)
            return replace(stale[0], degraded=True)

        log.warning("provider_manager.all_providers_failed", symbol=symbol)
        return None

    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        """Batched where possible: symbols already cached are served
        without any provider call, and only the remainder is fetched -
        via each provider's own batch method, not N sequential get_quote
        calls, so a full-watchlist refresh costs O(1) provider requests
        rather than O(watchlist size)."""
        results: dict[str, Quote] = {}
        remaining = []
        for symbol in symbols:
            cached = self._cached(symbol)
            if cached is not None:
                results[symbol] = cached
            else:
                remaining.append(symbol)

        if not remaining:
            return results

        for provider in self._quote_providers:
            if not remaining:
                break
            fetched = await provider.get_quotes(remaining)
            for symbol, quote in fetched.items():
                self._store(quote)
                results[symbol] = quote
            remaining = [s for s in remaining if s not in fetched]

        for symbol in remaining:
            stale = self._cache.get(symbol)
            if stale is not None:
                log.warning("provider_manager.serving_stale", symbol=symbol)
                results[symbol] = replace(stale[0], degraded=True)
            else:
                log.warning("provider_manager.all_providers_failed", symbol=symbol)

        return results

    async def get_history(
        self, symbol: str, start: datetime, end: datetime
    ) -> list[HistoryBar]:
        return await self._history_provider.get_history(symbol, start, end)

    async def get_current_bar(self, symbol: str) -> HistoryBar | None:
        """Real intraday OHLCV, used by the snapshot scheduler - see
        YFinanceProvider.get_current_bar's docstring for why this is
        yfinance-only rather than going through the quote preference order.

        `get_current_bar` isn't part of the `Provider` protocol (only
        yfinance has it - Finnhub/Alpha Vantage's free tiers don't give
        the OHLC-for-current-session shape it needs), so this degrades to
        `None` for any injected test double that doesn't implement it,
        the same "no data, not a crash" contract as everything else here.
        """
        method = getattr(self._history_provider, "get_current_bar", None)
        if method is None:
            return None
        return await method(symbol)


@lru_cache
def get_provider_manager() -> ProviderManager:
    return ProviderManager(get_settings())
