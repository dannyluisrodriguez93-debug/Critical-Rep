"""
Background scheduler — runs automatically when app.py starts.
Checks for new emails every morning at 7:30 AM and syncs notes.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_email_ingestion():
    log.info("Scheduler: running email ingestion...")
    try:
        from ingestion.email_fetcher import run_ingestion
        stats = run_ingestion(days_back=2)
        log.info("Scheduler: email ingestion done — %s", stats)
    except Exception as e:
        log.exception("Scheduler: email ingestion failed: %s", e)


def _run_notes_sync():
    log.info("Scheduler: syncing notes...")
    try:
        from integrations.apple_notes import sync_apple_notes
        from integrations.onenote import sync_onenote_notes
        apple_count = sync_apple_notes()
        one_count = sync_onenote_notes()
        log.info("Scheduler: notes sync done — Apple: %d, OneNote: %d", apple_count, one_count)
    except Exception as e:
        log.exception("Scheduler: notes sync failed: %s", e)


def _run_sf_sync():
    log.info("Scheduler: syncing Salesforce...")
    try:
        from integrations.salesforce import run_sf_sync
        result = run_sf_sync()
        log.info("Scheduler: SF sync done — %s", result)
    except Exception as e:
        log.exception("Scheduler: SF sync failed: %s", e)


def start_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone="America/New_York")

    # Email ingestion: 7:30 AM daily (reports arrive overnight)
    _scheduler.add_job(
        _run_email_ingestion,
        CronTrigger(hour=7, minute=30),
        id="email_ingestion",
        name="Daily email ingestion",
        replace_existing=True,
    )

    # Notes sync: 8:00 AM daily + every 4 hours
    _scheduler.add_job(
        _run_notes_sync,
        CronTrigger(hour="8,12,16,20", minute=0),
        id="notes_sync",
        name="Notes sync",
        replace_existing=True,
    )

    # Salesforce sync: 8:15 AM daily
    _scheduler.add_job(
        _run_sf_sync,
        CronTrigger(hour=8, minute=15),
        id="sf_sync",
        name="Salesforce sync",
        replace_existing=True,
    )

    _scheduler.start()
    log.info("Scheduler started — email ingestion at 7:30 AM ET daily")


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Scheduler stopped")


def trigger_now(job_id: str) -> bool:
    """Manually trigger a job by id. Returns True if triggered."""
    global _scheduler
    if not _scheduler:
        return False
    try:
        _scheduler.get_job(job_id).trigger
        _scheduler.get_job(job_id).modify(next_run_time=__import__("datetime").datetime.now())
        return True
    except Exception:
        return False
