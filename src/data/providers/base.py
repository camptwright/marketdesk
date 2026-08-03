"""Provider abstraction: the shared contract every quote/history source
implements, plus the rate limiter every provider is wrapped in.

Design principle carried through this whole module: a provider call NEVER
raises out to its caller. Network errors, rate-limit exhaustion, and bad
responses all collapse to `None` (for a single quote) or an empty list (for
history) - "degraded data", never a 500. `ProviderManager` (manager.py) is
what decides what to do about a `None` - fall back to the next provider, or
to the cache, or finally give up and label the response.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class Quote:
    symbol: str
    price: float
    change: float
    change_percent: float
    previous_close: float
    timestamp: datetime
    # Free-tier reality: yfinance's data is Yahoo's public 15-minute-delayed
    # feed. Finnhub/Alpha Vantage's free tiers are documented as real-time
    # for US equities - `delayed` reflects each provider's own claim, not a
    # guarantee this codebase can independently verify.
    delayed: bool
    # True when this Quote is a stale cache entry served because every
    # configured provider failed on this request - "some data beats no
    # data", but callers (the API layer) must surface this, not hide it.
    degraded: bool
    source: str


@dataclass
class HistoryBar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class Provider(Protocol):
    name: str

    async def get_quote(self, symbol: str) -> Quote | None: ...

    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote]: ...

    async def get_history(
        self, symbol: str, start: datetime, end: datetime
    ) -> list[HistoryBar]: ...


class RateLimiter:
    """Fixed-window-ish limiter via a sliding deque of call timestamps -
    simple, in-memory, correct for a single-process app with no Celery
    (constraint: never exceed configurable requests-per-minute per
    provider). Not thread-safe by design; this app has one event loop.
    """

    def __init__(self, requests_per_minute: int):
        self._limit = requests_per_minute
        self._calls: deque[float] = deque()

    def try_acquire(self) -> bool:
        now = time.monotonic()
        cutoff = now - 60.0
        while self._calls and self._calls[0] < cutoff:
            self._calls.popleft()
        if len(self._calls) >= self._limit:
            return False
        self._calls.append(now)
        return True
