"""
Background scheduler — runs automatically when app.py starts.
Checks for new emails every morning at 7:30 AM and syncs notes / Drive files.
All syncs no-op gracefully if the relevant integration is not connected.
"""

import logging
import platform

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_IS_MAC = platform.system() == "Darwin"


def _run_email_ingestion():
    log.info("Scheduler: running email ingestion...")
    try:
        from ingestion.email_fetcher import run_ingestion
        stats = run_ingestion(days_back=2)
        log.info("Scheduler: email ingestion done — %s", stats)
    except Exception as e:
        log.exception("Scheduler: email ingestion failed: %s", e)


def _run_notes_sync():
    if not _IS_MAC:
        return
    log.info("Scheduler: syncing Apple Notes...")
    try:
        from integrations.apple_notes import sync_apple_notes
        count = sync_apple_notes()
        log.info("Scheduler: notes sync done — Apple: %d", count)
    except Exception as e:
        log.exception("Scheduler: notes sync failed: %s", e)


def _run_imessage_sync():
    if not _IS_MAC:
        return
    log.info("Scheduler: syncing iMessage...")
    try:
        from integrations.imessage import sync_imessage
        result = sync_imessage(days_back=3)
        log.info("Scheduler: iMessage sync done — %s", result)
    except Exception as e:
        log.exception("Scheduler: iMessage sync failed: %s", e)


def _run_drive_sync():
    log.info("Scheduler: syncing Google Drive files...")
    try:
        from integrations.google_drive import sync_google_drive_files
        result = sync_google_drive_files()
        log.info("Scheduler: Drive sync done — %s", result)
    except Exception as e:
        log.exception("Scheduler: Drive sync failed: %s", e)


def _run_sheets_sync():
    log.info("Scheduler: syncing Google Sheets...")
    try:
        from integrations.google_sheets import sync_google_sheets
        result = sync_google_sheets()
        log.info("Scheduler: Sheets sync done — %s", result)
    except Exception as e:
        log.exception("Scheduler: Sheets sync failed: %s", e)


def _run_contacts_sync():
    log.info("Scheduler: syncing Google Contacts...")
    try:
        from integrations.google_contacts import sync_google_contacts
        result = sync_google_contacts()
        log.info("Scheduler: Contacts sync done — %s", result)
    except Exception as e:
        log.exception("Scheduler: Contacts sync failed: %s", e)


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

    # Email ingestion: 7:30 AM daily
    _scheduler.add_job(
        _run_email_ingestion,
        CronTrigger(hour=7, minute=30),
        id="email_ingestion",
        name="Daily email ingestion",
        replace_existing=True,
    )

    # Apple Notes sync: 4x daily (Mac only — no-ops silently otherwise)
    _scheduler.add_job(
        _run_notes_sync,
        CronTrigger(hour="8,12,16,20", minute=0),
        id="notes_sync",
        name="Apple Notes sync",
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

    # iMessage sync: every 2 hours (Mac only — no-ops silently otherwise)
    _scheduler.add_job(
        _run_imessage_sync,
        CronTrigger(hour="8,10,12,14,16,18,20", minute=30),
        id="imessage_sync",
        name="iMessage sync",
        replace_existing=True,
    )

    # Google Drive file sync: once daily at 8:45 AM
    _scheduler.add_job(
        _run_drive_sync,
        CronTrigger(hour=8, minute=45),
        id="drive_sync",
        name="Google Drive sync",
        replace_existing=True,
    )

    # Google Sheets sync: once daily at 9:00 AM
    _scheduler.add_job(
        _run_sheets_sync,
        CronTrigger(hour=9, minute=0),
        id="sheets_sync",
        name="Google Sheets sync",
        replace_existing=True,
    )

    # Google Contacts sync: once daily at 9:15 AM
    _scheduler.add_job(
        _run_contacts_sync,
        CronTrigger(hour=9, minute=15),
        id="contacts_sync",
        name="Google Contacts sync",
        replace_existing=True,
    )

    _scheduler.start()
    log.info(
        "Scheduler started — email 7:30 AM, notes 4x/day, iMsg 7x/day, "
        "Drive 8:45 AM, Sheets 9:00 AM, Contacts 9:15 AM ET"
        + (" (Mac features active)" if _IS_MAC else " (non-Mac: iMsg/Notes disabled)")
    )


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
        _scheduler.get_job(job_id).modify(
            next_run_time=__import__("datetime").datetime.now()
        )
        return True
    except Exception:
        return False
