from __future__ import annotations
"""Campaign 2 — hiring signal source.

Per brief §3 Campaign 2: target UK businesses actively hiring for sales,
customer service, marketing, OR paid media specialists. Hiring = growth/
capacity problem they're trying to solve with headcount; we sell the
faster/cheaper alternative.

Strategy: DuckDuckGo search for "UK <role> hiring" + extract company domains.
Tags every discovered company with campaign='hiring_signal' so the pipeline
can route them through a different sequence + send-time later.
"""
from ddgs import DDGS  # type: ignore

from ._common import guess_icp, is_junk, normalise_domain

HIRING_ROLES = [
    "head of sales",
    "sales director",
    "head of marketing",
    "marketing manager",
    "customer service manager",
    "head of customer success",
    "paid media specialist",
    "performance marketing manager",
]


def _queries(roles: list[str]) -> list[str]:
    return [
        f'"{role}" hiring UK -site:linkedin.com -site:indeed.com'
        for role in roles
    ]


def discover(country: str, queries: list[str], limit: int = 20) -> list[dict]:
    if country != "UK":
        return []
    # Ignore caller queries — this source uses its own role-keyword catalogue.
    found: dict[str, dict] = {}
    with DDGS() as ddgs:
        for q in _queries(HIRING_ROLES):
            try:
                results = list(ddgs.text(q, max_results=8, region="uk-en"))
            except Exception:
                continue
            for r in results:
                url = r.get("href") or r.get("url") or ""
                title = r.get("title") or ""
                snippet = r.get("body") or ""
                d = normalise_domain(url)
                if not d or is_junk(d) or d in found:
                    continue
                icp = guess_icp(f"{title} {snippet}", fallback=None)
                found[d] = {
                    "domain": d,
                    "name": title.split(" - ")[0].split(" | ")[0].strip()[:80] or d,
                    "country": "UK",
                    "icp": icp,
                    "source": "hiring_signal",
                    "campaign": "hiring_signal",
                }
                if len(found) >= limit:
                    return list(found.values())
    return list(found.values())[:limit]
