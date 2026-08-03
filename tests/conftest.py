"""Shared test fixtures. `FakeProvider` implements the `Provider` protocol
without touching the network, real or otherwise - used for both the
provider-abstraction tests and (eventually) route tests that need a
`ProviderManager` without hitting yfinance/Finnhub/Alpha Vantage."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.data.providers.base import HistoryBar, Quote


class FakeProvider:
    """Configurable in every direction a real provider can fail in: return
    a quote, return None (simulating a rate limit or network error), or
    raise (simulating something a real provider's own retry loop didn't
    catch - shouldn't happen given base.py's contract, but the manager
    should never trust that blindly)."""

    def __init__(self, name: str = "fake"):
        self.name = name
        self.quotes: dict[str, Quote] = {}
        self.fail_symbols: set[str] = set()
        self.calls: list[str] = []
        self.batch_calls: list[list[str]] = []

    def set_quote(
        self,
        symbol: str,
        price: float,
        previous_close: float,
        *,
        delayed: bool = False,
    ) -> None:
        change = price - previous_close
        self.quotes[symbol] = Quote(
            symbol=symbol,
            price=price,
            change=change,
            change_percent=(change / previous_close) * 100 if previous_close else 0.0,
            previous_close=previous_close,
            timestamp=datetime.now(timezone.utc),
            delayed=delayed,
            degraded=False,
            source=self.name,
        )

    async def get_quote(self, symbol: str) -> Quote | None:
        self.calls.append(symbol)
        if symbol in self.fail_symbols:
            return None
        return self.quotes.get(symbol)

    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        self.batch_calls.append(list(symbols))
        return {
            s: self.quotes[s] for s in symbols if s in self.quotes and s not in self.fail_symbols
        }

    async def get_history(self, symbol: str, start: datetime, end: datetime) -> list[HistoryBar]:
        return []


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()
