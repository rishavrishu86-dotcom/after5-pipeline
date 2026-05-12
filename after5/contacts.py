from __future__ import annotations
"""Contact discovery — free-stack replacement for Clay / Apollo.

Two paths:
  1. `import_people_csv(path)` — user-supplied CSV of named people per company
     (columns: domain, first_name, last_name, role[, email]). For each row,
     either takes the given email or generates pattern guesses, MX-validates
     the domain, and inserts the best candidate.
  2. `find_for_company(domain)` — calls Hunter.io domain search (free tier,
     25 lookups/mo) to fetch already-known public emails for the domain.

We deliberately do NOT do SMTP RCPT-TO probing: Gmail and M365 catch-all
everything then bounce later, so the result is unreliable. MX existence +
Hunter confidence are the verification signals we trust.
"""
import csv
import re
import socket
from pathlib import Path

import dns.resolver  # type: ignore
import requests

from . import config, db

PATTERNS = [
    "{first}.{last}",
    "{first}{last}",
    "{f}{last}",
    "{first}",
    "{first}_{last}",
    "{first}-{last}",
    "{f}.{last}",
]


def _slug(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _pattern_emails(first: str, last: str, domain: str) -> list[str]:
    f, l = _slug(first), _slug(last)
    if not f:
        return []
    ctx = {"first": f, "last": l, "f": f[:1], "l": l[:1] if l else ""}
    return [p.format(**ctx) + "@" + domain for p in PATTERNS if "{last}" not in p or l]


def _mx_ok(domain: str) -> bool:
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


def _company_id(domain: str) -> int | None:
    row = db.fetchone("SELECT id FROM companies WHERE domain=?", (domain,))
    return row["id"] if row else None


def _insert_contact(company_id: int, first: str, last: str, role: str | None,
                    email: str, verified: int) -> bool:
    try:
        with db.conn() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO contacts (company_id, first_name, last_name, "
                "role, email, email_verified) VALUES (?, ?, ?, ?, ?, ?)",
                (company_id, first, last, role, email.lower(), verified),
            )
            return bool(cur.rowcount)
    except Exception:
        return False


def import_people_csv(path: str | Path) -> dict:
    """CSV columns: domain, first_name, last_name, role[, email]."""
    path = Path(path)
    stats = {"inserted": 0, "skipped_no_company": 0, "skipped_no_mx": 0, "skipped_dup": 0}
    mx_cache: dict[str, bool] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            domain = (row.get("domain") or "").strip().lower()
            first = (row.get("first_name") or "").strip()
            last = (row.get("last_name") or "").strip()
            role = (row.get("role") or "").strip() or None
            explicit = (row.get("email") or "").strip().lower()
            company_id = _company_id(domain)
            if not company_id:
                stats["skipped_no_company"] += 1
                continue
            if domain not in mx_cache:
                mx_cache[domain] = _mx_ok(domain)
            if not mx_cache[domain]:
                stats["skipped_no_mx"] += 1
                continue
            if explicit:
                if _insert_contact(company_id, first, last, role, explicit, verified=0):
                    stats["inserted"] += 1
                else:
                    stats["skipped_dup"] += 1
                continue
            candidates = _pattern_emails(first, last, domain)
            if not candidates:
                continue
            if _insert_contact(company_id, first, last, role, candidates[0], verified=0):
                stats["inserted"] += 1
            else:
                stats["skipped_dup"] += 1
    return stats


def _hunter_domain_search(domain: str) -> list[dict]:
    if not config.HUNTER_API_KEY:
        return []
    try:
        r = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": config.HUNTER_API_KEY, "limit": 10},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        return r.json().get("data", {}).get("emails", []) or []
    except requests.RequestException:
        return []


def find_for_company(domain: str) -> int:
    """Hunter lookup → contacts table. Returns count inserted."""
    company_id = _company_id(domain)
    if not company_id:
        return 0
    if not _mx_ok(domain):
        return 0
    inserted = 0
    for entry in _hunter_domain_search(domain):
        email = (entry.get("value") or "").lower()
        if not email:
            continue
        first = entry.get("first_name") or ""
        last = entry.get("last_name") or ""
        role = entry.get("position") or None
        confidence = entry.get("confidence") or 0
        verified = 1 if confidence >= 70 else 0
        if _insert_contact(company_id, first, last, role, email, verified):
            inserted += 1
    return inserted


def find_all(limit: int | None = None) -> dict:
    """Run Hunter for every qualified company that has no contacts yet."""
    rows = db.fetchall(
        """
        SELECT co.domain
        FROM companies co
        LEFT JOIN contacts c ON c.company_id = co.id
        WHERE co.status = 'qualified'
        GROUP BY co.id
        HAVING COUNT(c.id) = 0
        ORDER BY co.total_score DESC
        """
        + (f" LIMIT {int(limit)}" if limit else "")
    )
    stats = {"companies_checked": 0, "contacts_inserted": 0}
    for r in rows:
        stats["companies_checked"] += 1
        stats["contacts_inserted"] += find_for_company(r["domain"])
    return stats
