from __future__ import annotations
"""IMAP reply triage — classify with Ollama, flag interesting ones for Louis."""
import email as email_lib
import imaplib
from email.utils import getaddresses

from . import ai, config, db, notify

LABELS = ["interested", "not_interested", "ooo", "unsubscribe", "other"]


def _plain_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                except (LookupError, AttributeError):
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(
            msg.get_content_charset() or "utf-8", errors="replace"
        )
    except (LookupError, AttributeError):
        return msg.get_payload() or ""


def _known_contact(addr: str) -> dict | None:
    return db.fetchone(
        """
        SELECT c.id, c.email, c.first_name, c.last_name,
               co.name AS company_name, co.domain, co.country, co.priority
        FROM contacts c JOIN companies co ON co.id = c.company_id
        WHERE c.email = ?
        """,
        (addr.lower(),),
    )


def run(folder: str = "INBOX", batch: int = 50) -> dict:
    if not config.SMTP_USER or not config.SMTP_PASS:
        return {"error": "smtp creds not configured"}
    stats = {"scanned": 0, "matched": 0, "classified": {l: 0 for l in LABELS}}
    M = imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT)
    try:
        M.login(config.SMTP_USER, config.SMTP_PASS)
        M.select(folder)
        typ, data = M.search(None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            return stats
        ids = data[0].split()[:batch]
        for mid in ids:
            stats["scanned"] += 1
            typ, msg_data = M.fetch(mid, "(RFC822)")
            if typ != "OK":
                continue
            msg = email_lib.message_from_bytes(msg_data[0][1])
            from_addrs = [a.lower() for _, a in getaddresses([msg.get("From", "")]) if a]
            contact = None
            for addr in from_addrs:
                contact = _known_contact(addr)
                if contact:
                    break
            if not contact:
                continue
            stats["matched"] += 1
            body = _plain_body(msg)
            label = ai.classify(body[:3000], LABELS, context="Cold-email reply")
            stats["classified"][label] += 1
            needs_louis = 1 if label == "interested" else 0
            with db.conn() as c:
                c.execute(
                    "INSERT INTO replies (contact_id, raw_body, classification, "
                    "sentiment, needs_louis) VALUES (?, ?, ?, ?, ?)",
                    (contact["id"], body[:5000], label, label, needs_louis),
                )
                if label == "unsubscribe":
                    c.execute("UPDATE contacts SET unsubscribed=1 WHERE id=?", (contact["id"],))
                    c.execute(
                        "INSERT OR IGNORE INTO suppression (email, domain, reason) "
                        "VALUES (?, ?, 'unsub')",
                        (contact["email"], contact["email"].split("@")[-1]),
                    )
                if label in ("interested", "not_interested", "unsubscribe"):
                    c.execute(
                        "UPDATE contacts SET ready_to_send=0 WHERE id=?",
                        (contact["id"],),
                    )
            if needs_louis:
                snippet = " ".join(body.split())[:240]
                who = (
                    f"{contact['first_name'] or ''} {contact['last_name'] or ''}".strip()
                    or contact["email"]
                )
                notify.slack(
                    f":mailbox_with_mail: *Interested reply* — {who} "
                    f"({contact['company_name'] or contact['domain']}, "
                    f"{contact['country']}, priority={contact['priority'] or '?'})\n"
                    f"> {snippet}"
                )
    finally:
        try:
            M.close()
        except imaplib.IMAP4.error:
            pass
        M.logout()
    return stats
