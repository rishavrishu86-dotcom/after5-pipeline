from __future__ import annotations
"""Enrichment orchestrator — runs every scraper for every new company."""
import json
from . import db, scrapers

SCORE_COLUMNS = {
    "tech":      "tech_score",
    "seo":       "seo_score",
    "reviews":   "reviews_score",
    "ads":       "ads_score",
    "hiring":    "hiring_score",
    "sentiment": "sentiment_score",
}


def enrich_company(company: dict) -> dict:
    results = {}
    for name, mod in scrapers.ALL.items():
        try:
            results[name] = mod.check(company["domain"], company["country"])
        except Exception as e:
            results[name] = {"score": 0, "type": name, "evidence": {"error": str(e)}}
    return results


def run(limit: int | None = None) -> int:
    rows = db.fetchall(
        "SELECT id, domain, country FROM companies WHERE status='new' ORDER BY id"
        + (f" LIMIT {int(limit)}" if limit else "")
    )
    for row in rows:
        results = enrich_company(row)
        sets = ["status='enriched'", "signals=?", "updated_at=CURRENT_TIMESTAMP"]
        params: list = [json.dumps(results)]
        for name, col in SCORE_COLUMNS.items():
            sets.append(f"{col}=?")
            params.append(results.get(name, {}).get("score", 0))
        params.append(row["id"])
        with db.conn() as c:
            c.execute(f"UPDATE companies SET {', '.join(sets)} WHERE id=?", params)
    return len(rows)
