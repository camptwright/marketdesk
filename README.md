# marketdesk

Self-hosted stock watchlist and portfolio tracker. A single FastAPI
container with an in-process APScheduler (no Celery, no Redis) that other
homelab services — the [homelab-dashboard](https://github.com/camptwright/homelab-dashboard)
"stocks" tile, [Adjutant](https://github.com/camptwright/adjutant)'s markets
sub-agent — consume over a small bearer-authed HTTP API.

Quotes and history come from [yfinance](https://github.com/ranaroussi/yfinance)
by default (no API key, ~15-minute-delayed data, always labeled `delayed:
true`). Finnhub and Alpha Vantage can be layered in front of it via API keys;
when configured, the preference order for real-time quotes is **Finnhub >
Alpha Vantage > yfinance**. `/history` is always served by yfinance alone —
neither other provider's free tier handles bulk OHLCV well enough to be
worth the complexity.

## Data providers

| Provider | Enabled by | Used for | Free-tier rate limit assumed |
|---|---|---|---|
| yfinance | always (no key) | quotes (fallback), all `/history` | 30 req/min |
| Finnhub | `FINNHUB_API_KEY` set | quotes (1st choice) | 50 req/min |
| Alpha Vantage | `ALPHAVANTAGE_API_KEY` set | quotes (2nd choice) | 5 req/min |

Quotes are cached for `QUOTE_CACHE_SECONDS` (default 600 = 10 minutes). If
every configured provider fails on a symbol but a stale cache entry exists,
that stale quote is still served — labeled `degraded: true` — rather than
returning nothing. If there's no cache either, the symbol is simply omitted
(never a fabricated value).

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://markets:changeme@postgres:5432/markets` | asyncpg driver for the app; Alembic swaps it for `psycopg` automatically ([config/settings.py](config/settings.py)) |
| `API_BEARER_TOKEN` | *(empty)* | Required. Every route except `/health` fails closed with 503 if this is unset — never silently open |
| `FINNHUB_API_KEY` | *(empty)* | Optional. Enables Finnhub as the 1st-choice quote provider |
| `ALPHAVANTAGE_API_KEY` | *(empty)* | Optional. Enables Alpha Vantage as the 2nd-choice quote provider |
| `QUOTE_CACHE_SECONDS` | `600` | Quote cache TTL |
| `FINNHUB_REQUESTS_PER_MINUTE` | `50` | |
| `ALPHAVANTAGE_REQUESTS_PER_MINUTE` | `5` | |
| `YFINANCE_REQUESTS_PER_MINUTE` | `30` | |
| `MARKET_TIMEZONE` | `America/Chicago` | Drives both the scheduler's cron triggers and market-hours labeling |
| `SNAPSHOT_RETENTION_DAYS` | `730` | 2 years; older `price_snapshots` rows are pruned nightly |
| `LOG_LEVEL` | `INFO` | |
| `ENVIRONMENT` | `production` | |

## API

All routes require `Authorization: Bearer <API_BEARER_TOKEN>` except `/health`.

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | No auth. `{"status": "ok", "postgres": bool}` |
| GET | `/quote/{symbol}` | Single quote |
| GET | `/quotes?symbols=AAPL,MSFT` | Batched quotes |
| GET | `/watchlist` | |
| POST | `/watchlist` | Upsert-on-conflict by symbol |
| DELETE | `/watchlist/{symbol}` | |
| GET | `/positions` | |
| POST | `/positions` | |
| PATCH | `/positions/{id}` | Partial update |
| DELETE | `/positions/{id}` | |
| GET | `/portfolio/summary` | Market value, day change, unrealized P/L, allocation, best/worst position |
| GET | `/movers` | Watchlist sorted by absolute day change |
| GET | `/history/{symbol}?range=1mo` | Backfills `price_snapshots` from the provider on first request for a symbol/range not already cached |

## Scheduled jobs

All times `America/Chicago`, in-process `AsyncIOScheduler` (started/stopped
in the FastAPI lifespan — no separate worker process):

- Market-open snapshot — 8:30 Mon–Fri
- Intraday snapshots — every 30 min, 9:00–14:30 Mon–Fri
- End-of-day snapshot — 15:15 Mon–Fri
- Retention prune — nightly, deletes `price_snapshots` rows older than `SNAPSHOT_RETENTION_DAYS`

## Running in homelab

marketdesk joins the shared Postgres instance on CT 110 as its own
database/user, per this repo's [CLAUDE.md](../homelab/CLAUDE.md) rule that
every service gets a dedicated database and user — never the superuser.

### One-time: Postgres role + database

Add to `postgres-init.sql` (fresh installs only — the live instance already
has this applied by hand, see homelab's CLAUDE.md note on
`postgres-init.sql` only running against an empty volume):

```sql
CREATE USER markets WITH PASSWORD 'changeme';
CREATE DATABASE markets OWNER markets;
```

Then rotate the real password (matching SETUP.md step A5's pattern):

```bash
source .env   # MUST run this first - see CLAUDE.md's A5 rotation warning
docker compose exec postgres psql -U postgres -c \
  "ALTER USER markets WITH PASSWORD '$MARKETS_DB_PASSWORD';"
```

### Compose block

```yaml
  marketdesk:
    <<: *small
    profiles: [apps]
    image: ghcr.io/camptwright/marketdesk:latest
    environment:
      DATABASE_URL: postgresql+asyncpg://markets:${MARKETS_DB_PASSWORD}@postgres:5432/markets
      API_BEARER_TOKEN: ${MARKETS_API_TOKEN}
      FINNHUB_API_KEY: ${FINNHUB_API_KEY}
      ALPHAVANTAGE_API_KEY: ${ALPHAVANTAGE_API_KEY}
      TZ: America/Chicago
    depends_on: {postgres: {condition: service_healthy}}
    mem_limit: 384m
```

Add `MARKETS_DB_PASSWORD`, `MARKETS_API_TOKEN` (`openssl rand -hex 32`), and
optionally `FINNHUB_API_KEY`/`ALPHAVANTAGE_API_KEY` to `.env` and
`.env.example`.

### Migrations

```bash
docker run --rm --network homelab_homelab \
  -e DATABASE_URL="postgresql+asyncpg://markets:$MARKETS_DB_PASSWORD@postgres:5432/markets" \
  ghcr.io/camptwright/marketdesk:latest alembic upgrade head
```

## Development

```bash
uv venv && uv pip install -e ".[dev]"
pytest
```

Tests run entirely against `FakeProvider` (`tests/conftest.py`) — no network
call, real or otherwise, and no Postgres required for the provider/portfolio
math suites.
