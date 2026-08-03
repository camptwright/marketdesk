"""Provider abstraction tests: preference order, caching, degraded
fallback, and rate limiting. All against `FakeProvider` - no network call,
real or otherwise, per the module docstring in conftest.py.
"""

from __future__ import annotations

import time

import pytest

from config.settings import Settings
from src.data.providers.base import RateLimiter
from src.data.providers.manager import ProviderManager
from tests.conftest import FakeProvider


class TestRateLimiter:
    def test_allows_up_to_the_limit(self):
        limiter = RateLimiter(requests_per_minute=3)
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is True

    def test_blocks_past_the_limit(self):
        limiter = RateLimiter(requests_per_minute=2)
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is False

    def test_window_slides(self):
        """Calls older than 60s should stop counting against the budget -
        verified by manipulating the limiter's internal deque directly
        rather than sleeping 60s in a test."""
        limiter = RateLimiter(requests_per_minute=1)
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is False
        # Simulate the one recorded call having happened 61s ago.
        limiter._calls[0] = time.monotonic() - 61
        assert limiter.try_acquire() is True


@pytest.fixture
def settings() -> Settings:
    return Settings(quote_cache_seconds=600)


class TestProviderManagerPreferenceOrder:
    @pytest.mark.asyncio
    async def test_first_provider_wins(self, settings: Settings):
        first = FakeProvider("first")
        second = FakeProvider("second")
        first.set_quote("AAPL", price=200.0, previous_close=195.0)
        second.set_quote("AAPL", price=999.0, previous_close=999.0)

        manager = ProviderManager(settings, quote_providers=[first, second])
        quote = await manager.get_quote("AAPL")

        assert quote is not None
        assert quote.source == "first"
        assert quote.price == 200.0
        # Second provider shouldn't even be asked once the first succeeds.
        assert second.calls == []

    @pytest.mark.asyncio
    async def test_falls_through_to_second_provider_on_failure(self, settings: Settings):
        first = FakeProvider("first")
        second = FakeProvider("second")
        first.fail_symbols.add("AAPL")
        second.set_quote("AAPL", price=200.0, previous_close=195.0)

        manager = ProviderManager(settings, quote_providers=[first, second])
        quote = await manager.get_quote("AAPL")

        assert quote is not None
        assert quote.source == "second"
        assert first.calls == ["AAPL"]


class TestProviderManagerCache:
    @pytest.mark.asyncio
    async def test_second_call_within_window_hits_cache(self, settings: Settings):
        provider = FakeProvider()
        provider.set_quote("AAPL", price=200.0, previous_close=195.0)
        manager = ProviderManager(settings, quote_providers=[provider])

        first = await manager.get_quote("AAPL")
        provider.set_quote("AAPL", price=250.0, previous_close=195.0)  # provider "moves"
        second = await manager.get_quote("AAPL")

        assert first.price == second.price == 200.0
        assert provider.calls == ["AAPL"]  # only the first call actually reached the provider

    @pytest.mark.asyncio
    async def test_expired_cache_refetches(self, settings: Settings):
        settings.quote_cache_seconds = 0  # expires immediately
        provider = FakeProvider()
        provider.set_quote("AAPL", price=200.0, previous_close=195.0)
        manager = ProviderManager(settings, quote_providers=[provider])

        await manager.get_quote("AAPL")
        provider.set_quote("AAPL", price=250.0, previous_close=195.0)
        second = await manager.get_quote("AAPL")

        assert second.price == 250.0
        assert provider.calls == ["AAPL", "AAPL"]


class TestProviderManagerDegradedFallback:
    @pytest.mark.asyncio
    async def test_serves_stale_cache_labeled_degraded_when_all_providers_fail(
        self, settings: Settings
    ):
        settings.quote_cache_seconds = 0
        provider = FakeProvider()
        provider.set_quote("AAPL", price=200.0, previous_close=195.0)
        manager = ProviderManager(settings, quote_providers=[provider])

        fresh = await manager.get_quote("AAPL")
        assert fresh.degraded is False

        provider.fail_symbols.add("AAPL")  # now every provider fails
        stale = await manager.get_quote("AAPL")

        assert stale is not None
        assert stale.degraded is True
        assert stale.price == 200.0  # the last known value, not fabricated

    @pytest.mark.asyncio
    async def test_returns_none_when_no_cache_and_all_providers_fail(self, settings: Settings):
        provider = FakeProvider()
        provider.fail_symbols.add("AAPL")
        manager = ProviderManager(settings, quote_providers=[provider])

        result = await manager.get_quote("AAPL")

        assert result is None


class TestProviderManagerBatch:
    @pytest.mark.asyncio
    async def test_batch_skips_already_cached_symbols(self, settings: Settings):
        provider = FakeProvider()
        provider.set_quote("AAPL", price=200.0, previous_close=195.0)
        provider.set_quote("MSFT", price=300.0, previous_close=295.0)
        manager = ProviderManager(settings, quote_providers=[provider])

        await manager.get_quote("AAPL")  # warms the cache for AAPL only
        results = await manager.get_quotes(["AAPL", "MSFT"])

        assert set(results.keys()) == {"AAPL", "MSFT"}
        # AAPL came from cache, so the batch call should only have asked
        # for MSFT.
        assert provider.batch_calls == [["MSFT"]]
