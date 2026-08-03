"""Pure portfolio math - no I/O, no DB, no HTTP. Kept separate from the API
layer specifically so it's directly unit-testable (see tests/
test_portfolio_math.py) without mocking a database or a provider.

Design decision worth documenting: `Position.cost_basis` is the PER-SHARE
average cost (what a user would naturally type when opening a position -
"I bought at $150"), not the total dollar amount paid. Unrealized P/L is
therefore `shares * (current_price - cost_basis)`, not
`market_value - cost_basis`. This is stated here once, not re-derived at
every call site.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PositionQuote:
    """The minimal shape position math needs - decoupled from both the
    ORM's `Position` and the provider's `Quote` so this module has zero
    import-time dependency on either."""

    symbol: str
    shares: float
    cost_basis: float  # per-share
    current_price: float
    previous_close: float


@dataclass
class PositionMetrics:
    symbol: str
    shares: float
    cost_basis: float
    current_price: float
    market_value: float
    day_change_dollar: float
    day_change_percent: float
    unrealized_pl_dollar: float
    unrealized_pl_percent: float


@dataclass
class PortfolioSummary:
    total_market_value: float
    total_day_change_dollar: float
    total_day_change_percent: float
    total_unrealized_pl_dollar: float
    total_unrealized_pl_percent: float
    positions: list[PositionMetrics]
    # symbol -> percent of total_market_value. Positions in the same symbol
    # are combined into one allocation entry.
    allocation_by_symbol: dict[str, float]


def compute_position_metrics(pq: PositionQuote) -> PositionMetrics:
    market_value = pq.shares * pq.current_price
    previous_value = pq.shares * pq.previous_close
    day_change_dollar = market_value - previous_value
    day_change_percent = (
        (day_change_dollar / previous_value) * 100 if previous_value else 0.0
    )

    cost_total = pq.shares * pq.cost_basis
    unrealized_pl_dollar = market_value - cost_total
    unrealized_pl_percent = (
        ((pq.current_price - pq.cost_basis) / pq.cost_basis) * 100
        if pq.cost_basis
        else 0.0
    )

    return PositionMetrics(
        symbol=pq.symbol,
        shares=pq.shares,
        cost_basis=pq.cost_basis,
        current_price=pq.current_price,
        market_value=market_value,
        day_change_dollar=day_change_dollar,
        day_change_percent=day_change_percent,
        unrealized_pl_dollar=unrealized_pl_dollar,
        unrealized_pl_percent=unrealized_pl_percent,
    )


def compute_portfolio_summary(position_quotes: list[PositionQuote]) -> PortfolioSummary:
    positions = [compute_position_metrics(pq) for pq in position_quotes]

    total_market_value = sum(p.market_value for p in positions)
    total_day_change_dollar = sum(p.day_change_dollar for p in positions)
    total_previous_value = total_market_value - total_day_change_dollar
    total_day_change_percent = (
        (total_day_change_dollar / total_previous_value) * 100
        if total_previous_value
        else 0.0
    )
    total_cost = sum(p.shares * p.cost_basis for p in positions)
    total_unrealized_pl_dollar = sum(p.unrealized_pl_dollar for p in positions)
    total_unrealized_pl_percent = (
        (total_unrealized_pl_dollar / total_cost) * 100 if total_cost else 0.0
    )

    allocation: dict[str, float] = {}
    for p in positions:
        allocation[p.symbol] = allocation.get(p.symbol, 0.0) + p.market_value
    if total_market_value:
        allocation = {
            symbol: (value / total_market_value) * 100
            for symbol, value in allocation.items()
        }
    else:
        allocation = dict.fromkeys(allocation, 0.0)

    return PortfolioSummary(
        total_market_value=total_market_value,
        total_day_change_dollar=total_day_change_dollar,
        total_day_change_percent=total_day_change_percent,
        total_unrealized_pl_dollar=total_unrealized_pl_dollar,
        total_unrealized_pl_percent=total_unrealized_pl_percent,
        positions=positions,
        allocation_by_symbol=allocation,
    )
