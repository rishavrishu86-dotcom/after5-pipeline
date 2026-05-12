from __future__ import annotations
"""Qualify enriched companies — sum sub-scores and bucket by priority."""
from . import db

HOT = 18
WARM = 10


def _priority(total: int) -> str:
    if total >= HOT:
        return "hot"
    if total >= WARM:
        return "warm"
    return "cold"


def run() -> dict:
    rows = db.fetchall(
        "SELECT id, tech_score, ads_score, hiring_score, reviews_score, sentiment_score "
        "FROM companies WHERE status='enriched'"
    )
    counts = {"hot": 0, "warm": 0, "cold": 0}
    with db.conn() as c:
        for r in rows:
            total = (
                r["tech_score"] + r["ads_score"] + r["hiring_score"]
                + r["reviews_score"] + r["sentiment_score"]
            )
            prio = _priority(total)
            counts[prio] += 1
            new_status = "qualified" if prio in ("hot", "warm") else "rejected"
            c.execute(
                "UPDATE companies SET total_score=?, priority=?, status=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (total, prio, new_status, r["id"]),
            )
    return counts
