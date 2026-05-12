from __future__ import annotations
"""SEO footprint signal — DuckDuckGo site: indexed-page probe.

Strong SEO footprint = the company invests in inbound. A `site:` search on
DuckDuckGo returns roughly how many of their own pages rank for general queries.
We translate result count into a 0-10 score — more indexed pages = higher
score, capped.
"""
try:
    from ddgs import DDGS  # type: ignore
    _HAS_DDGS = True
except ImportError:
    _HAS_DDGS = False


def check(domain: str, country: str) -> dict:
    if not _HAS_DDGS or not domain:
        return {"score": 0, "type": "seo", "evidence": {"reason": "ddgs unavailable"}}
    indexed = 0
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(f"site:{domain}", max_results=20))
            indexed = sum(1 for r in results if domain in (r.get("href") or ""))
    except Exception as e:
        return {"score": 0, "type": "seo", "evidence": {"error": str(e)[:80]}}
    # 0 → 0, 1-3 → 3, 4-9 → 5, 10-15 → 7, 16+ → 9
    if indexed >= 16: score = 9
    elif indexed >= 10: score = 7
    elif indexed >= 4: score = 5
    elif indexed >= 1: score = 3
    else: score = 0
    return {
        "score": score,
        "type": "seo",
        "evidence": {"indexed_pages_sampled": indexed},
    }
