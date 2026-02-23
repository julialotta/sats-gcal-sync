"""
Background scheduler — runs the sync job every N minutes.
The sync function is defined in app.py and injected here to avoid circular imports.
"""

import logging
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def start(sync_fn, interval_minutes: int = 60) -> None:
    """Start the background scheduler with the given sync function."""
    global _scheduler
    if _scheduler and _scheduler.running:
        logger.warning("Scheduler already running — skipping start")
        return

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        sync_fn,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="sats_sync",
        replace_existing=True,
        name="Sats → GCal sync",
    )
    _scheduler.start()
    logger.info("Scheduler started — sync every %d minute(s)", interval_minutes)


def stop() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
