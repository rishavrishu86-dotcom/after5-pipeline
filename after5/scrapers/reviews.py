from __future__ import annotations
"""Reviews / sentiment signal — Trustpilot via JSON-LD.

A company with many reviews has volume to handle; mixed sentiment suggests
support strain (AI agent triages tier-1). Trustpilot now ships rating data in
a JSON-LD <script type="application/ld+json"> block, so we parse that rather
than regex-scraping the rendered HTML.
"""
import json
import re
from . import _http

JSONLD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _extract_rating(html: str) -> tuple[int, float]:
    """Returns (review_count, rating_value). 0, 0.0 on failure."""
    for m in JSONLD_RE.finditer(html):
        blob = m.group(1).strip()
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        # Trustpilot sometimes wraps the relevant object in a graph array.
        candidates = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and isinstance(data.get("@graph"), list):
            candidates = data["@graph"]
        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            agg = obj.get("aggregateRating") or obj.get("AggregateRating")
            if isinstance(agg, dict):
                try:
                    count = int(agg.get("reviewCount") or agg.get("ratingCount") or 0)
                    rating = float(agg.get("ratingValue") or 0)
                    return count, rating
                except (TypeError, ValueError):
                    continue
    return 0, 0.0


def check(domain: str, country: str) -> dict:
    r = _http.get(f"https://www.trustpilot.com/review/{domain}")
    if not r or r.status_code != 200:
        return {"score": 0, "type": "reviews", "evidence": {"found": False}}
    count, rating = _extract_rating(r.text)
    score = 0
    if count >= 50:
        score += 3
    if count >= 500:
        score += 2
    if 0 < rating < 4.0:
        score += 4  # support strain
    elif rating >= 4.5 and count >= 100:
        score += 2  # mature, can afford automation
    return {
        "score": min(score, 10),
        "type": "reviews",
        "evidence": {"count": count, "rating": rating},
    }
