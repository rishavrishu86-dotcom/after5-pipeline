from __future__ import annotations
"""Bounce scanner — finds MAILER-DAEMON / DSN replies, suppresses bad addresses.

Honest truth-source for email validity. We:
  1. Search Gmail IMAP for messages from mailer-daemon / postmaster in the last N days.
  2. Extract the failed recipient from RFC 3464 message/delivery-status parts
     (Final-Recipient / Original-Recipient headers).
  3. Fall back to regex over the bounce body, intersecting with known contacts.
  4. Insert into `suppression` (UNIQUE on email → idempotent) and clear
     `ready_to_send` on the matching contact rows.

We do NOT distinguish hard vs soft bounces yet — any bounce suppresses. Soft-
bounce recovery can be layered on later by parsing the DSN `Status:` SMTP code
(2.x.x = OK, 4.x.x = transient, 5.x.x = permanent).
"""
import email as email_lib
import imaplib
import re
from datetime import datetime, timedelta
from email.utils import getaddresses

from . import config, db

BOUNCE_SENDERS = ("mailer-daemon", "postmaster")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
FINAL_RCPT_RE = re.compile(
    r"^(?:final|original)-recipient\s*:\s*[^;]*;\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
STATUS_RE = re.compile(
    r"^status\s*:\s*([245])\.\d+\.\d+", re.IGNORECASE | re.MULTILINE
)


def _is_bounce_sender(addr: str) -> bool:
    return any(s in (addr or "").lower() for s in BOUNCE_SENDERS)


def _extract_recipients(msg) -> tuple[set[str], str]:
    """Walk a multipart bounce. Returns (recipients, severity).

    severity is 'hard' (5.x.x), 'soft' (4.x.x), or 'unknown' (no Status:).
    Hard = permanent failure → suppress. Soft = transient → log only.
    """
    found: set[str] = set()
    severity = "unknown"
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "message/delivery-status":
                try:
                    raw = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                except (AttributeError, LookupError):
                    raw = ""
                for m in FINAL_RCPT_RE.finditer(raw):
                    addr = m.group(1).strip().strip("<>").lower()
                    if "@" in addr:
                        found.add(addr)
                status_match = STATUS_RE.search(raw)
                if status_match:
                    first_digit = status_match.group(1)
                    severity = {"5": "hard", "4": "soft", "2": "ok"}.get(
                        first_digit, severity
                    )
    return found, severity


def _body_fallback(msg) -> str:
    parts: list[str] = []
    if msg.is_multipart():
        for p in msg.walk():
            if p.get_content_type() in ("text/plain", "message/rfc822"):
                try:
                    parts.append(
                        p.get_payload(decode=True).decode(
                            p.get_content_charset() or "utf-8", errors="replace"
                        )
                    )
                except (AttributeError, LookupError):
                    continue
    else:
        try:
            parts.append(
                msg.get_payload(decode=True).decode(
                    msg.get_content_charset() or "utf-8", errors="replace"
                )
            )
        except (AttributeError, LookupError):
            pass
    return "\n".join(parts)


def _candidates_from_body(body: str) -> set[str]:
    return {m.group(0).lower() for m in EMAIL_RE.finditer(body)}


def _known_emails(candidates: set[str]) -> list[dict]:
    if not candidates:
        return []
    placeholders = ",".join("?" * len(candidates))
    return db.fetchall(
        f"SELECT id, email FROM contacts WHERE email IN ({placeholders})",
        tuple(candidates),
    )


def _suppress(email_addr: str, reason: str) -> None:
    domain = email_addr.split("@")[-1]
    with db.conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO suppression (email, domain, reason) VALUES (?, ?, ?)",
            (email_addr, domain, reason),
        )
        c.execute("UPDATE contacts SET ready_to_send=0 WHERE email=?", (email_addr,))


def run(folder: str = "INBOX", days: int = 14, batch: int = 200) -> dict:
    if not config.SMTP_USER or not config.SMTP_PASS:
        return {"error": "smtp creds not configured"}
    stats = {"scanned": 0, "bounces": 0, "hard": 0, "soft": 0, "suppressed": 0}
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%d-%b-%Y")
    M = imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT)
    try:
        M.login(config.SMTP_USER, config.SMTP_PASS)
        M.select(folder)
        criteria = f'(SINCE "{since}" OR FROM "mailer-daemon" FROM "postmaster")'
        typ, data = M.search(None, criteria)
        if typ != "OK" or not data or not data[0]:
            return stats
        ids = data[0].split()[-batch:]
        for mid in ids:
            stats["scanned"] += 1
            typ, msg_data = M.fetch(mid, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email_lib.message_from_bytes(msg_data[0][1])
            from_addrs = [a for _, a in getaddresses([msg.get("From", "")]) if a]
            if not any(_is_bounce_sender(a) for a in from_addrs):
                continue
            stats["bounces"] += 1
            recipients, severity = _extract_recipients(msg)
            if not recipients:
                body = _body_fallback(msg)
                known = _known_emails(_candidates_from_body(body))
                recipients = {row["email"] for row in known if row.get("email")}
            if severity == "soft":
                stats["soft"] += 1
                continue  # transient — don't suppress
            stats["hard"] += 1
            reason = "hard-bounce" if severity == "hard" else "bounce-unknown"
            for r in recipients:
                _suppress(r, reason=reason)
                stats["suppressed"] += 1
    finally:
        try:
            M.close()
        except imaplib.IMAP4.error:
            pass
        M.logout()
    return stats
