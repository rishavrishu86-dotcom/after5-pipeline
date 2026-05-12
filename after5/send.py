from __future__ import annotations
"""Gmail SMTP sender — sequencer, suppression check, MX probe, dry-run.

Replaces SmartLead + listclean.xyz. Daily cap from config.DAILY_SEND_CAP.
"""
import smtplib
import socket
import ssl
import uuid
from email.message import EmailMessage
from pathlib import Path

import dns.resolver  # type: ignore  # only used if dnspython installed; falls back to MX-less probe
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config, db

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "templates"


def _env_for(country: str) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_ROOT / country.lower())),
        autoescape=select_autoescape(["html"]),
    )


def _render(country: str, day: int, ctx: dict) -> tuple[str, str]:
    env = _env_for(country)
    subject = env.get_template(f"day{day}_subject.j2").render(**ctx).strip()
    body = env.get_template(f"day{day}_body.j2").render(**ctx).strip()
    return subject, body


def render_for_contact(contact: dict, day: int | None = None) -> tuple[str, str]:
    """Render the subject + body that WOULD be sent to a contact right now.

    `contact` must include keys used by the templates:
      first_name, company_name (or domain), country, ai_first_line, signal_used.
    `day` defaults to the contact's next_send_day, or 1 if unset.
    """
    day = day or contact.get("next_send_day") or 1
    ctx = {
        "first_name":    contact.get("first_name") or "there",
        "company_name":  contact.get("company_name") or contact.get("domain") or "your team",
        "domain":        contact.get("domain") or "",
        "icp":           contact.get("icp") or "",
        "ai_first_line": contact.get("ai_first_line") or "",
        "signal_used":   contact.get("signal_used") or "",
        "role":          contact.get("role") or "",
        "unsubscribe":   f"mailto:{config.REPLY_TO}?subject=unsubscribe",
    }
    return _render(contact.get("country", "UK"), day, ctx)


def _suppressed(email: str, domain: str) -> bool:
    row = db.fetchone(
        "SELECT 1 FROM suppression WHERE email=? OR domain=?",
        (email, domain),
    )
    return bool(row)


def _mx_ok(domain: str) -> bool:
    """Quick MX existence check. Returns True if MX or A record resolves."""
    try:
        dns.resolver.resolve(domain, "MX", lifetime=5)
        return True
    except Exception:
        pass
    try:
        socket.gethostbyname(domain)
        return True
    except OSError:
        return False


def _due_contacts(limit: int) -> list[dict]:
    return db.fetchall(
        """
        SELECT c.*, co.country, co.name AS company_name, co.domain, co.icp
        FROM contacts c
        JOIN companies co ON co.id = c.company_id
        WHERE co.status = 'qualified'
          AND c.ready_to_send = 1
          AND c.unsubscribed = 0
          AND c.email IS NOT NULL
          AND c.next_send_day IS NOT NULL
          AND (
            c.last_sent_at IS NULL
            OR julianday('now') - julianday(c.last_sent_at) >= (c.next_send_day - COALESCE(c.current_sequence_day, 0))
          )
        ORDER BY co.total_score DESC
        LIMIT ?
        """,
        (limit,),
    )


def _send_one(server: smtplib.SMTP, contact: dict, subject: str, body: str) -> str:
    msg = EmailMessage()
    msg["From"] = f"{config.SENDER_NAME} <{config.SMTP_USER}>"
    msg["To"] = contact["email"]
    msg["Reply-To"] = config.REPLY_TO
    msg["Subject"] = subject
    message_id = f"<{uuid.uuid4()}@{config.SMTP_USER.split('@')[-1]}>"
    msg["Message-ID"] = message_id
    msg["List-Unsubscribe"] = f"<mailto:{config.REPLY_TO}?subject=unsubscribe>"
    msg.set_content(body)
    server.send_message(msg)
    return message_id


def run(dry_run: bool = False, cap: int | None = None) -> dict:
    cap = cap or config.DAILY_SEND_CAP
    due = _due_contacts(cap)
    stats = {"sent": 0, "skipped": 0, "suppressed": 0, "bad_mx": 0}
    if not due:
        return stats

    server = None
    if not dry_run:
        ctx = ssl.create_default_context()
        server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20)
        server.starttls(context=ctx)
        server.login(config.SMTP_USER, config.SMTP_PASS)

    try:
        for contact in due:
            email = contact["email"]
            domain = email.split("@")[-1]
            if _suppressed(email, domain):
                stats["suppressed"] += 1
                continue
            if not _mx_ok(domain):
                stats["bad_mx"] += 1
                with db.conn() as c:
                    c.execute(
                        "INSERT OR IGNORE INTO suppression (email, domain, reason) "
                        "VALUES (?, ?, 'no-mx')",
                        (email, domain),
                    )
                continue
            day = contact["next_send_day"] or 1
            ctx = {
                "first_name": contact.get("first_name") or "there",
                "company_name": contact["company_name"] or contact["domain"],
                "ai_first_line": contact["ai_first_line"] or "",
                "signal_used": contact["signal_used"] or "",
                "unsubscribe": f"mailto:{config.REPLY_TO}?subject=unsubscribe",
            }
            subject, body = _render(contact["country"], day, ctx)
            if dry_run:
                print(f"--- DRY {email} day{day} ---\nSubj: {subject}\n{body}\n")
                stats["sent"] += 1
                continue

            try:
                message_id = _send_one(server, contact, subject, body)
            except smtplib.SMTPException:
                stats["skipped"] += 1
                continue

            with db.conn() as c:
                c.execute(
                    "INSERT INTO sends (contact_id, sequence_day, subject, body, message_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (contact["id"], day, subject, body, message_id),
                )
                next_day = _next_sequence_day(day)
                c.execute(
                    "UPDATE contacts SET current_sequence_day=?, next_send_day=?, "
                    "last_sent_at=CURRENT_TIMESTAMP, ready_to_send=? WHERE id=?",
                    (day, next_day, 1 if next_day else 0, contact["id"]),
                )
            stats["sent"] += 1
    finally:
        if server:
            try:
                server.quit()
            except smtplib.SMTPException:
                pass
    return stats


def _next_sequence_day(current: int) -> int | None:
    seq = config.SEQUENCE_DAYS
    for d in seq:
        if d > current:
            return d
    return None


def unsubscribe(email: str) -> None:
    domain = email.split("@")[-1]
    with db.conn() as c:
        c.execute("UPDATE contacts SET unsubscribed=1 WHERE email=?", (email,))
        c.execute(
            "INSERT OR IGNORE INTO suppression (email, domain, reason) VALUES (?, ?, 'unsub')",
            (email, domain),
        )
