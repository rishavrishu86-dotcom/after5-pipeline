from __future__ import annotations
"""Campaign 3 — agency partnership source.

Per brief §3 Campaign 3: UK marketing agency owners. Phone-first. 15% recurring
commission for referrals. The pitch lands twice — as a partnership AND as a
sale (many agency owners realise they need the product themselves).

Clutch.co has aggressive bot protection (Cloudflare) so a direct scrape is
fragile. We use DuckDuckGo as the lookup layer with `site:clutch.co/uk` plus
fallback agency-finding queries. Tags discovered companies with
campaign='agency_partnership'.
"""
from ddgs import DDGS  # type: ignore

from ._common import is_junk, normalise_domain

AGENCY_QUERIES = [
    "UK marketing agency",
    "UK digital agency",
    "UK growth agency",
    "UK performance marketing agency",
    "site:clutch.co/uk/agencies/digital",
    "site:clutch.co/uk/agencies/seo",
]


def discover(country: str, queries: list[str], limit: int = 20) -> list[dict]:
    if country != "UK":
        return []
    found: dict[str, dict] = {}
    with DDGS() as ddgs:
        for q in AGENCY_QUERIES:
            try:
                results = list(ddgs.text(q, max_results=8, region="uk-en"))
            except Exception:
                continue
            for r in results:
                url = r.get("href") or r.get("url") or ""
                title = r.get("title") or ""
                d = normalise_domain(url)
                if not d or is_junk(d) or d in found:
                    continue
                # Skip Clutch's own pages — we want the agency's own domain.
                if "clutch.co" in d:
                    continue
                found[d] = {
                    "domain": d,
                    "name": title.split(" - ")[0].split(" | ")[0].strip()[:80] or d,
                    "country": "UK",
                    "icp": "marketing_agency",
                    "source": "clutch_agency",
                    "campaign": "agency_partnership",
                }
                if len(found) >= limit:
                    return list(found.values())
    return list(found.values())[:limit]
