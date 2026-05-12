from __future__ import annotations
"""CSV import — replaces AI Ark's pre-built DB.

Expects CSV columns: domain, name, country, icp[, source]
country must be 'UK' or 'UAE'. Idempotent on domain.
"""
import csv
from pathlib import Path
from . import db


def _normalise_domain(d: str) -> str:
    d = (d or "").strip().lower()
    for prefix in ("https://", "http://", "www."):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d.split("/")[0]


MAX_ROWS = 5000  # cap to prevent runaway imports from a hostile / mis-shaped file


def import_csv(path: str | Path) -> tuple[int, int]:
    """Returns (inserted, skipped). Caps input at MAX_ROWS."""
    path = Path(path)
    inserted = skipped = 0
    with db.conn() as c, path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader):
            if i >= MAX_ROWS:
                break
            domain = _normalise_domain(row.get("domain", ""))
            country = (row.get("country") or "").strip().upper()
            if not domain or country not in ("UK", "UAE"):
                skipped += 1
                continue
            cur = c.execute(
                "INSERT OR IGNORE INTO companies (domain, name, country, icp, source) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    domain,
                    (row.get("name") or "").strip() or None,
                    country,
                    (row.get("icp") or "").strip() or None,
                    (row.get("source") or "csv").strip(),
                ),
            )
            if cur.rowcount:
                inserted += 1
            else:
                skipped += 1
    return inserted, skipped
