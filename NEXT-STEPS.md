# marketdesk — status and next steps

Written mid-build (2026-08-03) because a session usage limit was imminent.
This is the authoritative "what's real vs not yet" doc until the pieces
below are filled in — trust this over assumptions from the original request.

## What's actually done and verified

- **Repo scaffolded, git-initialized, committed locally.** No GitHub
  remote yet — needs a decision (see "Needs a decision" below).
- **Settings** (`config/settings.py`): all env vars from the spec, plus
  `sync_database_url` for Alembic.
- **ORM models** (`src/models/orm.py`): `watchlist`, `positions`,
  `price_snapshots`, exactly as specified. **Caught and fixed a real bug**
  before it ever hit Postgres: `server_default="gen_random_uuid()"` as a
  bare Python string renders as a *literal string default*, not a function
  call — inspected the compiled DDL directly, saw the quoted garbage, fixed
  it with `func.gen_random_uuid()`/`func.now()`.
- **Alembic migration 0001**: written by hand to match the ORM exactly,
  then **applied against a real Postgres** — created the actual `markets`
  user/database live on CT 110's shared Postgres instance (not a fresh
  install; ran the one-time `CREATE USER`/`CREATE DATABASE`/`ALTER USER`
  sequence by hand over SSH), built a Docker image, ran `alembic upgrade
  head` against it, and confirmed via `\dt` that all 3 tables + a correct
  `gen_random_uuid()` default exist for real. **`postgres-init.sql` has NOT
  been updated yet** — a fresh install would need the markets role/db added
  there by hand, matching how `wellthread`'s roles were added (see
  homelab's CLAUDE.md, "`postgres-init.sql` only runs on an EMPTY volume").
- **Provider abstraction** (`src/data/providers/`): `base.py` (Quote/
  HistoryBar/RateLimiter), `yfinance_provider.py`, `finnhub_provider.py`,
  `alphavantage_provider.py`, `manager.py` (preference order finnhub >
  alphavantage > yfinance for quotes, yfinance-only for `/history` and the
  scheduler's intraday OHLCV bars). **Verified against real live yfinance
  data** — real AAPL/MSFT/GOOGL quotes, confirmed the 10-minute cache
  actually short-circuits a second call, batch quotes, 7 real days of
  history bars. Finnhub/Alpha Vantage are implemented against their
  *documented* API contracts but **NOT verified live** — no API key is
  configured anywhere, so if their real response shapes differ even
  slightly, `finnhub_provider.py`/`alphavantage_provider.py` are the only
  files that need to change (this is called out in each file's docstring).
- **Scheduler** (`src/scheduler/`): `jobs.py` (snapshot_all, prune_old_
  snapshots) and `app.py` (4 cron jobs: 8:30 open, 9:00-14:30 every 30 min,
  15:15 EOD, 2am pruning — all `America/Chicago`). **Verified**: started a
  real `AsyncIOScheduler` and printed all 4 jobs' actual next-fire
  timestamps, confirmed they land exactly where expected.
- **Portfolio math** (`src/utils/portfolio_math.py`): pure functions, zero
  I/O, deliberately separated so it's directly unit-testable. **Design
  decision documented in its own docstring**: `cost_basis` is interpreted
  as *per-share* average cost, not total — the spec didn't say which, and
  this is the more natural reading given a user types "I bought at $150".
  **Verified by hand** with two synthetic positions against hand-computed
  expected totals (market value, day change $/%, unrealized P/L, allocation)
  — all matched exactly.
- **FastAPI routes** (`src/api/`): `auth.py` (constant-time bearer compare,
  fails closed with a 503 if `API_BEARER_TOKEN` is unset rather than
  silently allowing everything through), `main.py` (lifespan starts/stops
  the scheduler + disposes the DB engine), and all 7 routers (health,
  quotes, watchlist, positions, portfolio, movers, history). **Only
  import-checked so far (11 routes registered, no import errors) — NOT
  live-tested against a running server + real DB CRUD flow.** This is the
  single most important thing to verify next, before trusting any of it.

## What's NOT done at all

1. **No automated tests exist yet** (`tests/` only has `__init__.py`).
   Needed: a `FakeProvider` implementing the `Provider` protocol for
   provider-abstraction tests (never hit the network in CI); portfolio
   math tests (the hand-verification above should become real
   `pytest` assertions); rate-limit/cache behavior tests (verify
   `RateLimiter.try_acquire()` actually blocks past its budget, verify
   `ProviderManager` serves from cache within the 10-minute window and
   correctly falls back to a stale-but-labeled-degraded quote when every
   provider fails).
2. **Dockerfile is a draft** — builds and was used to test the migration,
   but hasn't been used to actually *run* the API yet. No `.github/
   workflows/build.yml` exists at all.
3. **No README.md.** Needs: every env var (including the ones added mid-
   build that weren't in the original list — none currently, but double-
   check against `config/settings.py` before writing it), the homelab
   compose block (given verbatim in the original request), and the
   homelab-side one-time setup commands (`postgres-init.sql` addition +
   the live `CREATE USER`/`CREATE DATABASE`/`ALTER USER` sequence — the
   live version of these commands was already run by hand this session;
   the README needs to document the *repeatable* version for a fresh
   install, and note that it's already been done once on CT 110).
4. **homelab's `docker-compose.yml` does not have the marketdesk service
   block yet.** The exact block is in the original request verbatim — add
   it under `profiles: [apps]`, matching the pattern of every other app
   service. `MARKETS_DB_PASSWORD` already exists in CT 110's live `.env`
   (generated during the manual DB setup this session); `MARKETS_API_TOKEN`
   does NOT exist yet and needs to be generated and added.
5. **No live end-to-end test of the running API** — build the real image
   (not the migration-only draft), `docker compose up`, and actually curl
   `/health`, POST to `/watchlist`, POST a `/positions` entry, GET
   `/portfolio/summary`, GET `/quote/{symbol}` against a real symbol, GET
   `/history/{symbol}` and confirm the backfill-on-first-request behavior
   actually writes rows to `price_snapshots`. This is the biggest
   real-vs-assumed-correct gap right now — everything above was verified in
   isolation (pure functions, provider calls in a bare Python script), not
   through the actual HTTP layer with bearer auth in front of it.

## Needs a decision (from you)

- **No GitHub remote for this repo.** Same situation fantasy-edge was in —
  I don't have `gh` authenticated and don't know the intended repo name.
  Tell me the URL (or confirm `camptwright/marketdesk`) and I'll add it and
  push, same as I did for fantasy-edge → `fantasy-probabilities`.
- **`MARKETS_API_TOKEN`** needs to be generated (e.g. `openssl rand -hex
  32`) and added to CT 110's `.env` — I can do this, just flagging it
  hasn't happened yet.

## What I'll do next (in order), once resumed

1. Build the real runtime image (not just the migration draft) and run the
   API for real against the live `markets` Postgres — curl every route.
2. Write `tests/` (fake provider, portfolio math, rate-limit/cache) and
   actually run `pytest`, not just write it.
3. Finish the Dockerfile (it already has a `base` stage that works; just
   needs to be confirmed as the final multi-stage non-root shape) + write
   `.github/workflows/build.yml` (push `ghcr.io/camptwright/marketdesk:
   latest` and `:sha-<sha>`, `permissions: packages: write`).
4. Write README.md with the env var table, the compose block, and the
   `postgres-init.sql` / one-time live-command instructions.
5. Add the marketdesk service block to `homelab/docker-compose.yml`
   and the `markets` role/db to `homelab/postgres-init.sql`.
6. Deploy for real on CT 110, verify `docker compose ps` shows it healthy,
   curl it through to confirm the deployed instance actually works (not
   just a throwaway test container).
7. Then move to the homelab-dashboard "stocks" tile (`/stocks` page) — not
   started at all yet, see homelab-dashboard's own `NEXT-STEPS.md`.
8. Then the Adjutant scaffold + markets sub-agent — also not started;
   Adjutant does not exist as a codebase anywhere yet (confirmed absent
   both locally and on GitHub under every plausible name), so this
   requires building a minimal orchestrator/agent framework from scratch,
   not just adding to an existing one. This is a large, separate
   undertaking — see the main conversation for the full original spec
   (SYSTEM.md conventions, tool tiers, schedule migrations, etc.) since
   none of that exists in this repo.
