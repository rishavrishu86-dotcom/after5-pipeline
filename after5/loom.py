from __future__ import annotations
"""WF7 — Loom Reminder.

Scans replies that look like real opportunities and have been left to rot:
  • classification = 'interested'
  • >48h since received_at
  • loom_sent = 0
  • meeting_booked = 0
  • louis_responded = 0

For each, Slack-DM Louis once (idempotent via `slack_pinged_at`).

The blueprint adds "Mark Loom Sent" / "Snooze 24h" buttons in Slack; we don't
have a Slack app for interactivity, so those actions live in the webapp instead.
"""
from datetime import datetime

from . import config, db, notify


def stale_interesteds(hours: int = 48) -> list[dict]:
    return db.fetchall(
        f"""
        SELECT r.id, r.received_at, r.raw_body, r.slack_pinged_at,
               c.first_name, c.last_name, c.email,
               co.name AS company_name, co.domain, co.country, co.priority
        FROM replies r
        JOIN contacts c ON c.id = r.contact_id
        JOIN companies co ON co.id = c.company_id
        WHERE r.classification = 'interested'
          AND r.loom_sent = 0
          AND r.meeting_booked = 0
          AND r.louis_responded = 0
          AND r.slack_pinged_at IS NULL
          AND julianday('now') - julianday(r.received_at) >= ({hours} / 24.0)
        ORDER BY r.received_at ASC
        """
    )


def _mark_pinged(reply_id: int) -> None:
    with db.conn() as c:
        c.execute(
            "UPDATE replies SET slack_pinged_at=? WHERE id=?",
            (datetime.utcnow().isoformat(timespec="seconds"), reply_id),
        )


def run(hours: int = 48) -> dict:
    rows = stale_interesteds(hours=hours)
    pinged = 0
    for r in rows:
        who = f"{r['first_name'] or ''} {r['last_name'] or ''}".strip() or r["email"]
        priority = r["priority"] or "?"
        snippet = " ".join((r["raw_body"] or "").split())[:240]
        ok = notify.slack(
            f":alarm_clock: *Loom nudge* — {who} at *{r['company_name'] or r['domain']}* "
            f"({r['country']}, priority={priority}) said *interested* over {hours}h ago "
            f"and you haven't sent a Loom yet.\n"
            f"> {snippet}\n"
            f"_Reply id #{r['id']} · domain {r['domain']}_"
        )
        if ok or not config.SLACK_WEBHOOK_URL:
            # Mark pinged even when webhook is empty so we don't print the same row forever.
            _mark_pinged(r["id"])
            pinged += 1
    return {
        "stale_replies": len(rows),
        "pinged": pinged,
        "lookback_hours": hours,
    }
