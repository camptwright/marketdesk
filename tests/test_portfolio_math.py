"""Portfolio math tests - formalizes the hand-verification done while
building this module (see NEXT-STEPS.md) into real assertions."""

from __future__ import annotations

import pytest

from src.utils.portfolio_math import PositionQuote, compute_portfolio_summary


def test_single_position_up_on_the_day_and_overall():
    pq = PositionQuote(
        symbol="AAPL", shares=10, cost_basis=150.0, current_price=200.0, previous_close=195.0
    )
    summary = compute_portfolio_summary([pq])
    p = summary.positions[0]

    assert p.market_value == pytest.approx(2000.0)
    assert p.day_change_dollar == pytest.approx(50.0)  # (200-195)*10
    assert p.day_change_percent == pytest.approx(2.564102564, rel=1e-6)
    assert p.unrealized_pl_dollar == pytest.approx(500.0)  # (200-150)*10
    assert p.unrealized_pl_percent == pytest.approx(33.33333333, rel=1e-6)


def test_multi_position_totals_and_allocation():
    positions = [
        PositionQuote("AAPL", shares=10, cost_basis=150.0, current_price=200.0, previous_close=195.0),
        PositionQuote("MSFT", shares=5, cost_basis=300.0, current_price=290.0, previous_close=295.0),
    ]
    summary = compute_portfolio_summary(positions)

    assert summary.total_market_value == pytest.approx(3450.0)  # 2000 + 1450
    assert summary.total_day_change_dollar == pytest.approx(25.0)  # 50 + (-25)
    assert summary.total_unrealized_pl_dollar == pytest.approx(450.0)  # 500 + (-50)
    assert summary.allocation_by_symbol["AAPL"] == pytest.approx(57.971014, rel=1e-5)
    assert summary.allocation_by_symbol["MSFT"] == pytest.approx(42.028985, rel=1e-5)
    assert sum(summary.allocation_by_symbol.values()) == pytest.approx(100.0)


def test_position_down_on_the_day_and_at_a_loss():
    pq = PositionQuote(
        symbol="TSLA", shares=2, cost_basis=300.0, current_price=250.0, previous_close=260.0
    )
    summary = compute_portfolio_summary([pq])
    p = summary.positions[0]

    assert p.day_change_dollar == pytest.approx(-20.0)  # (250-260)*2
    assert p.day_change_percent < 0
    assert p.unrealized_pl_dollar == pytest.approx(-100.0)  # (250-300)*2
    assert p.unrealized_pl_percent < 0


def test_empty_portfolio_does_not_divide_by_zero():
    summary = compute_portfolio_summary([])

    assert summary.total_market_value == 0.0
    assert summary.total_day_change_percent == 0.0
    assert summary.total_unrealized_pl_percent == 0.0
    assert summary.positions == []
    assert summary.allocation_by_symbol == {}


def test_multiple_positions_in_the_same_symbol_combine_in_allocation():
    positions = [
        PositionQuote("AAPL", shares=5, cost_basis=140.0, current_price=200.0, previous_close=195.0),
        PositionQuote("AAPL", shares=5, cost_basis=160.0, current_price=200.0, previous_close=195.0),
        PositionQuote("MSFT", shares=10, cost_basis=300.0, current_price=300.0, previous_close=300.0),
    ]
    summary = compute_portfolio_summary(positions)

    # Two separate lots of the same symbol still contribute separate
    # PositionMetrics entries (one per lot, e.g. for a positions table)...
    assert len([p for p in summary.positions if p.symbol == "AAPL"]) == 2
    # ...but combine into ONE allocation entry per symbol.
    assert summary.allocation_by_symbol["AAPL"] == pytest.approx(2000 / 5000 * 100)
    assert summary.allocation_by_symbol["MSFT"] == pytest.approx(3000 / 5000 * 100)
