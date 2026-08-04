# marketdesk — status and next steps

**STATUS (2026-08-04): feature-complete and deployed.** Everything this
doc originally tracked as missing (Docker, CI, README, homelab compose
wiring, live E2E test) is done - see the bottom of this file for what
changed since the mid-build snapshot below. The section immediately
following is kept as-is for its build history and the real-vs-assumed
provider notes, which are still accurate and still worth reading before
touching the provider abstraction.

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

## Needs a decision (from you) — RESOLVED

- ~~No GitHub remote for this repo~~ → `github.com/camptwright/marketdesk`,
  pushed.
- ~~`MARKETS_API_TOKEN` needs to be generated~~ → generated, in CT110's
  `.env`, and subsequently rotated once during this session's secret-
  exposure incident (see homelab CLAUDE.md's operational lessons if a
  similar `docker compose config` dump ever happens again).

## What actually happened next (2026-08-04)

All 8 items above are done:

1. **Live E2E test executed for real** against the running container -
   every route (`/health`, auth 401s, watchlist CRUD, `/quotes` batch,
   `/movers`, positions CRUD + `/portfolio/summary`, `/history` backfill,
   deletes) confirmed working with real yfinance data.
2. `tests/` written and passing: `FakeProvider`, provider preference
   order/cache/degraded-fallback/batch behavior, portfolio math.
3. **Dockerfile finalized** as a true multi-stage build (`uv` in a
   `builder` stage, only the venv + app code in `runtime`, non-root
   throughout) - verified on CT110: builds clean, runs as uid 1001,
   scheduler starts, `/health` returns 200. `.github/workflows/build.yml`
   runs `pytest` then pushes to `ghcr.io/camptwright/marketdesk`.
4. README.md written: env var table, full API surface, scheduled jobs,
   the homelab compose block, and the one-time Postgres setup steps.
5. Compose block and `postgres-init.sql`'s `markets` user/database added
   to the homelab repo; `MARKETS_DB_PASSWORD`/`MARKETS_API_TOKEN`/
   `FINNHUB_API_KEY`/`ALPHAVANTAGE_API_KEY` added to `env.example`.
6. **Deployed for real on CT110** as the actual `marketdesk` compose
   service (not a throwaway container) - `docker compose config` parses
   clean with `core,apps` profiles, the real service is healthy, and it's
   the one Adjutant's markets agent pulled real watchlist/portfolio/quote
   data from during that repo's own end-to-end verification.
7. The homelab-dashboard "stocks" tile is built and deployed - see that
   repo's `NEXT-STEPS.md`.
8. Adjutant exists (`github.com/camptwright/adjutant`) with a markets
   sub-agent that reads this API read-only and posts briefs back to the
   dashboard - see that repo's own README/NEXT-STEPS for its shape.

One thing worth knowing for next time: the GHCR package's visibility
was never explicitly confirmed public - the CT110 deployment above was
built directly from source on the LXC (same workaround dashboard needed
originally) because `docker pull ghcr.io/camptwright/marketdesk:latest`
returned `unauthorized` and the `gh auth refresh` needed to check/fix
package visibility timed out waiting on browser confirmation in this
non-interactive session. Worth revisiting before relying on a plain
`docker compose pull && up -d marketdesk` on a future redeploy.
