# marketdesk Agent Instructions

## What this repo is

A self-hosted stock watchlist and portfolio tracker: a single FastAPI
container with an in-process APScheduler (no Celery, no Redis) that other
homelab services (the homelab-dashboard "stocks" tile, Adjutant's markets
sub-agent) consume over a small bearer-authed HTTP API. Quotes fall back
across three providers; `/history` is yfinance-only. Real money P/L is
computed and served, so numeric correctness in the math layer matters as
much as anything else in this repo.

## Hard rules for agents

1. **`cost_basis` is PER-SHARE, not total.** `src/utils/portfolio_math.py`
   depends on this everywhere: `unrealized_pl_dollar = shares *
   (current_price - cost_basis)`, never `market_value - cost_basis`
   directly. See the `portfolio-math-invariants` skill before touching this
   file, its callers, or the `Position` ORM model.

2. **Provider calls must never raise.** Every `Provider` in
   `src/data/providers/` collapses network errors, rate-limit exhaustion,
   and bad responses to `None`/`[]`. `ProviderManager` in `manager.py`
   handles fallback (Finnhub > Alpha Vantage > yfinance) and stale-cache
   serving (labeled `degraded: true`) — it is not a place to let exceptions
   propagate. See the `provider-fallback-contract` skill.

3. **`/history` is served by yfinance alone.** Do not route it through the
   Finnhub/Alpha Vantage preference order — neither free tier handles bulk
   OHLCV well enough; this is a deliberate simplification, not an oversight.

4. **Every division needs an explicit zero-denominator guard**, falling
   back to `0.0` (never `None` or a skipped field) — callers may not
   handle a missing key, and a crash on a $0 previous-close is worse than
   a $0.0 percentage.

5. **Auth fails closed.** `require_bearer_token` in `src/api/auth.py`
   returns 503 if `API_BEARER_TOKEN` is unset, not "auth disabled." Do not
   change this to permit unauthenticated access on misconfiguration.

6. **Positions are closed, never deleted, on normal workflow.** `DELETE
   /positions/{id}` is for mistakes; closing a position is a PATCH setting
   `closed_at`. Portfolio math and future P/L reporting depend on closed
   positions surviving in the table.

7. **marketdesk gets its own Postgres database/user (`markets`), never the
   superuser** — per homelab's `CLAUDE.md` rule referenced in this repo's
   README.

## Agents must not

- Subtract `cost_basis` from a market-value-scale number without first
  multiplying by `shares` — this silently flips the unit and reports wrong
  P/L, not a crash.
- Compute portfolio-level percent totals as a naive average of each
  position's own percentage; they must be value-weighted ratios of already-
  summed dollar totals (see `compute_portfolio_summary`).
- Treat a quote-less symbol (all providers failed, no cache) as a $0
  position — it must be excluded from the math, not zero-filled, or it
  corrupts `market_value` and the P/L-percent denominator.
- Let a provider adapter raise out to its caller instead of returning
  `None`/`[]`.

## Automatic review

The `financial-calc-reviewer` agent runs on every change to:
- `src/utils/portfolio_math.py`
- `src/api/routers/portfolio.py`
- `src/api/routers/positions.py`
- the `Position` model in `src/models/orm.py`

Do not consider such a change done without that review.
