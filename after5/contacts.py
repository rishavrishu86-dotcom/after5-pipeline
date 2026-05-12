from __future__ import annotations
"""Contact discovery — free-stack replacement for Clay / Apollo.

Per brief §7: exactly 3 decision makers per company —
  1. Founder / CEO / Owner
  2. Head of Sales / Sales Director
  3. Head of Marketing / Marketing Manager

Two paths:
  1. `import_people_csv(path)` — user-supplied CSV of named people per company.
  2. `find_for_company(domain)` — Hunter.io domain search filtered to the 3
     target roles, falling back to role-pattern emails (founder@, sales@,
     marketing@) for any missing role.

We deliberately do NOT do SMTP RCPT-TO probing: Gmail and M365 catch-all
everything then bounce later, so the result is unreliable. MX existence +
Hunter confidence are the verification signals we trust; hard bounces get
caught later by `bounces.run()`.
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

# Role bucket → keyword matchers (lowercased). First match wins.
ROLE_BUCKETS = (
    ("founder",   ("founder", "ceo", "co-founder", "owner", "managing director",
                   "md", "chief executive", "president")),
    ("sales",     ("head of sales", "vp sales", "vp of sales", "sales director",
                   "director of sales", "chief revenue", "cro", "commercial director",
                   "sales lead")),
    ("marketing", ("head of marketing", "marketing director", "vp marketing",
                   "cmo", "chief marketing", "growth lead", "head of growth",
                   "marketing manager", "marketing lead")),
)

# Generic mailbox fallback per role when no real person is found.
ROLE_FALLBACK_LOCAL = {
    "founder":   "founder",
    "sales":     "sales",
    "marketing": "marketing",
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _pattern_emails(first: str, last: str, domain: str) -> list[str]:
    f, l = _slug(first), _slug(last)
    if not f:
        return []
    ctx = {"first": f, "last": l, "f": f[:1], "l": l[:1] if l else ""}
    return [p.format(**ctx) + "@" + domain for p in PATTERNS if "{last}" not in p or l]


def _classify_role(position: str | None) -> str | None:
    """Return 'founder' / 'sales' / 'marketing' or None."""
    if not position:
        return None
    p = position.lower()
    for bucket, kws in ROLE_BUCKETS:
        if any(k in p for k in kws):
            return bucket
    return None


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


def _existing_role_buckets(company_id: int) -> set[str]:
    rows = db.fetchall(
        "SELECT role FROM contacts WHERE company_id=?", (company_id,)
    )
    return {b for r in rows for b in [_classify_role(r["role"])] if b}


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
            email = explicit
            if not email:
                cands = _pattern_emails(first, last, domain)
                if not cands:
                    continue
                email = cands[0]
            if _insert_contact(company_id, first, last, role, email, verified=0):
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
            params={"domain": domain, "api_key": config.HUNTER_API_KEY, "limit": 25},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        return r.json().get("data", {}).get("emails", []) or []
    except requests.RequestException:
        return []


def find_for_company(domain: str) -> int:
    """Find up to 3 contacts (founder + sales + marketing).

    Order of attempts per role:
      1. A Hunter result with a matching position.
      2. A generic role mailbox guess (founder@, sales@, marketing@).
    """
    company_id = _company_id(domain)
    if not company_id or not _mx_ok(domain):
        return 0

    already_have = _existing_role_buckets(company_id)
    target_roles = [b for b, _ in ROLE_BUCKETS if b not in already_have]
    if not target_roles:
        return 0

    inserted = 0
    hunter_results = _hunter_domain_search(domain)

    # First pass — claim roles from real Hunter results.
    claimed: set[str] = set()
    for entry in hunter_results:
        email = (entry.get("value") or "").lower()
        if not email:
            continue
        bucket = _classify_role(entry.get("position"))
        if bucket not in target_roles or bucket in claimed:
            continue
        first = entry.get("first_name") or ""
        last = entry.get("last_name") or ""
        role = entry.get("position") or None
        confidence = entry.get("confidence") or 0
        verified = 1 if confidence >= 70 else 0
        if _insert_contact(company_id, first, last, role, email, verified):
            inserted += 1
            claimed.add(bucket)

    # Second pass — fill any still-missing role with a generic mailbox guess.
    for bucket in target_roles:
        if bucket in claimed:
            continue
        local = ROLE_FALLBACK_LOCAL[bucket]
        email = f"{local}@{domain}"
        role_label = {"founder": "Founder / CEO",
                      "sales":   "Head of Sales",
                      "marketing": "Head of Marketing"}[bucket]
        if _insert_contact(company_id, "", "", role_label, email, verified=0):
            inserted += 1

    return inserted


def find_all(limit: int | None = None) -> dict:
    """Run role-targeted contact discovery for every qualified company
    that doesn't yet have all 3 role buckets filled."""
    rows = db.fetchall(
        """
        SELECT co.domain
        FROM companies co
        WHERE co.status = 'qualified'
        ORDER BY co.total_score DESC
        """
        + (f" LIMIT {int(limit)}" if limit else "")
    )
    stats = {"companies_checked": 0, "contacts_inserted": 0}
    for r in rows:
        stats["companies_checked"] += 1
        stats["contacts_inserted"] += find_for_company(r["domain"])
    return stats
