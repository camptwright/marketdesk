"""In-process scheduler - no Celery, per the "resource-constrained single
container" constraint. `AsyncIOScheduler` runs jobs as coroutines on the
same event loop FastAPI is already using; `start()`/`shutdown()` are called
from the API's lifespan hooks in `src/api/main.py`.

Cron triggers are evaluated in America/Chicago - this only matters for
*when* a job fires (a Chicago 8:30am trigger is the same wall-clock moment
regardless of the host's own system timezone, since APScheduler converts
using the tzdata for the trigger's zone, not the container's `TZ` env var).
The container's `TZ` env var (also set to America/Chicago in the homelab
compose block) keeps log timestamps and this module's own reasoning
consistent, but is not what makes the schedule correct - the explicit
`timezone=` on each trigger is.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import get_settings
from src.scheduler.jobs import prune_old_snapshots, snapshot_all
from src.utils.logging import get_logger

log = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    tz = get_settings().market_timezone
    scheduler = AsyncIOScheduler(timezone=tz)

    # Market hours are 8:30-15:00 America/Chicago (9:30-16:00 ET). A single
    # cron expression can't say "every 30 min, but starting at :30 past the
    # first hour" - two triggers on the same job cover it exactly:
    # 8:30 once, then :00/:30 for 9 through 14 (i.e. up to and including
    # 14:30, the last snapshot before the 15:15 EOD one below).
    scheduler.add_job(
        snapshot_all,
        trigger=CronTrigger(day_of_week="mon-fri", hour="8", minute="30", timezone=tz),
        id="snapshot_market_open",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        snapshot_all,
        trigger=CronTrigger(day_of_week="mon-fri", hour="9-14", minute="0,30", timezone=tz),
        id="snapshot_intraday",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        snapshot_all,
        trigger=CronTrigger(day_of_week="mon-fri", hour="15", minute="15", timezone=tz),
        id="snapshot_eod",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        prune_old_snapshots,
        trigger=CronTrigger(hour="2", minute="0", timezone=tz),
        id="prune_old_snapshots",
        misfire_grace_time=3600,
    )

    scheduler.start()
    _scheduler = scheduler
    log.info("scheduler.started", timezone=tz, jobs=[j.id for j in scheduler.get_jobs()])
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("scheduler.stopped")
