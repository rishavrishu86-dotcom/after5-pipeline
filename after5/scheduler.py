from __future__ import annotations
"""Unattended runner — daily morning + weekly Monday jobs.

Daily 09:00 Europe/London:
    bounces (suppress hard fails) → triage (classify replies) → send (next batch)

Weekly Monday 06:00 Europe/London:
    enrich (new companies)  → qualify (bucket) →
    find-contacts (Hunter)  → personalise (AI first lines)

Errors are caught per-step and pinged to Slack so one stage can't take down
the rest of the loop.
"""
import logging
import os
import traceback
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler

from . import (
    bounces, contacts, discover, enrich, loom, notify, personalise,
    qualify, send, triage,
)

log = logging.getLogger("after5.scheduler")
TZ = os.environ.get("SCHEDULER_TZ", "Europe/London")


def _step(name: str, fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
        log.info("%s ok: %s", name, result)
        return result
    except Exception as e:
        tb = traceback.format_exc(limit=4)
        log.exception("%s failed", name)
        notify.slack(f":rotating_light: `{name}` failed: {e}\n```{tb}```")
        return None


def daily_job() -> None:
    log.info("daily_job start %s", datetime.now().isoformat(timespec="seconds"))
    _step("bounces", bounces.run, days=3)
    _step("triage", triage.run)
    sent = _step("send", send.run, dry_run=False)
    if isinstance(sent, dict) and sent.get("sent"):
        notify.slack(
            f":outbox_tray: Daily send: {sent['sent']} emails out "
            f"(suppressed={sent.get('suppressed',0)}, bad_mx={sent.get('bad_mx',0)})"
        )


def weekly_job() -> None:
    log.info("weekly_job start %s", datetime.now().isoformat(timespec="seconds"))
    discovered = _step("discover", discover.run, limit_per_source=20)
    _step("enrich", enrich.run, limit=100)
    counts = _step("qualify", qualify.run)
    _step("find-contacts", contacts.find_all, limit=20)
    personalised = _step("personalise", personalise.run, limit=200)
    notify.slack(
        f":bar_chart: Weekly refresh — discovered: {(discovered or {}).get('inserted', 0)} new; "
        f"qualified: {counts or {}}; personalised {personalised or 0} new contacts."
    )


def loom_job() -> None:
    log.info("loom_job start %s", datetime.now().isoformat(timespec="seconds"))
    _step("loom-check", loom.run, hours=48)


def build_scheduler() -> BlockingScheduler:
    sched = BlockingScheduler(timezone=TZ)
    sched.add_job(daily_job, "cron", hour=9, minute=0, id="daily")
    sched.add_job(weekly_job, "cron", day_of_week="mon", hour=6, minute=0, id="weekly")
    sched.add_job(loom_job, "interval", hours=6, id="loom")
    return sched


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    sched = build_scheduler()
    log.info("scheduler started, tz=%s — daily 09:00, weekly Mon 06:00, loom every 6h", TZ)
    notify.slack(f":gear: after5 scheduler started ({TZ}).")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler stopped")
        notify.slack(":octagonal_sign: after5 scheduler stopped.")
