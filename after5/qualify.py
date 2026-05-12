from __future__ import annotations
"""Qualify enriched companies per brief §5 — 0-6 binary signals, pass at 3/6.

Each of the 6 signals contributes:
  - binary: 1 if the rich score >= SIGNAL_PASS_THRESHOLD, else 0
  - rich total: sum of all rich scores (0-60) for fine-grained ordering

Priority per brief:
  5-6/6 binary → "hot"   (dial first, personalise heavily)
  3-4/6 binary → "warm"
  <3/6 binary  → "cold"  → status='rejected'
"""
from . import db

SIGNALS = ("tech_score", "seo_score", "reviews_score",
           "ads_score", "hiring_score", "sentiment_score")
SIGNAL_PASS_THRESHOLD = 3   # each rich score must be at least this to "count"
MIN_BINARY_TO_QUALIFY = 3   # 3/6 signals to enter the sequence


def _binary_total(row: dict) -> int:
    return sum(1 for s in SIGNALS if (row.get(s) or 0) >= SIGNAL_PASS_THRESHOLD)


def _rich_total(row: dict) -> int:
    return sum(row.get(s) or 0 for s in SIGNALS)


def _priority(binary: int) -> str:
    if binary >= 5: return "hot"
    if binary >= 3: return "warm"
    return "cold"


def run() -> dict:
    rows = db.fetchall(
        "SELECT id, " + ", ".join(SIGNALS) + " FROM companies WHERE status='enriched'"
    )
    counts = {"hot": 0, "warm": 0, "cold": 0}
    with db.conn() as c:
        for r in rows:
            binary = _binary_total(r)
            total = _rich_total(r)
            prio = _priority(binary)
            counts[prio] += 1
            new_status = "qualified" if binary >= MIN_BINARY_TO_QUALIFY else "rejected"
            c.execute(
                "UPDATE companies SET total_score=?, priority=?, status=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (total, prio, new_status, r["id"]),
            )
    return counts
