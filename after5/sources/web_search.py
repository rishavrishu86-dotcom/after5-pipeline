from __future__ import annotations
"""DuckDuckGo source — most reliable free option.

Issues seed queries like `"UAE proptech" hiring`, distils results to company
domains, filters out junk (LinkedIn/Indeed/news/etc) via _common.is_junk.
"""
from ddgs import DDGS  # type: ignore

from ._common import guess_icp, is_junk, normalise_domain


def _query_for(country: str, q: str) -> list[str]:
    """Build a couple of search variants per ICP query."""
    if country == "UK":
        return [
            f'"UK" "{q}" hiring -site:linkedin.com',
            f'"{q}" company site:.co.uk',
        ]
    return [
        f'"UAE" "{q}" hiring -site:linkedin.com',
        f'"Dubai" "{q}" company',
        f'"{q}" company site:.ae',
    ]


def discover(country: str, queries: list[str], limit: int = 20) -> list[dict]:
    if country not in ("UK", "UAE"):
        return []
    found: dict[str, dict] = {}
    with DDGS() as ddgs:
        for icp_term in queries:
            for search in _query_for(country, icp_term):
                try:
                    results = list(ddgs.text(search, max_results=10, region="uk-en" if country == "UK" else "xa-en"))
                except Exception:
                    continue
                for r in results:
                    url = r.get("href") or r.get("url") or ""
                    title = r.get("title") or ""
                    snippet = r.get("body") or ""
                    d = normalise_domain(url)
                    if not d or is_junk(d) or d in found:
                        continue
                    icp = guess_icp(f"{title} {snippet} {icp_term}", fallback=icp_term)
                    found[d] = {
                        "domain": d,
                        "name": title.split(" - ")[0].split(" | ")[0].strip()[:80] or d,
                        "country": country,
                        "icp": icp,
                        "source": "web_search",
                    }
                    if len(found) >= limit:
                        return list(found.values())
    return list(found.values())[:limit]
