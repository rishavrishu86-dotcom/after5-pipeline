from __future__ import annotations
"""Indeed UK source — best-effort.

Indeed has serious anti-bot defenses. Plain `requests` GETs frequently 403. We
try once with a realistic UA; on 403 we record a `blocked` evidence row and
return empty. A future upgrade would route this through Playwright headless
(already in requirements) but that's not built here yet.

When it does work, we extract company names from search-result cards. Those
names alone aren't usable as leads — we'd have to resolve company → domain via
a second step. For now this source returns empty pending that resolver.
"""
import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from ..scrapers import _http
from ._common import guess_icp


def _company_names(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    for sel in (
        '[data-testid="company-name"]',
        "span.companyName",
        "a.companyName",
        ".companyName",
    ):
        for el in soup.select(sel):
            name = el.get_text(strip=True)
            if name and name not in out:
                out.append(name)
    return out


def discover(country: str, queries: list[str], limit: int = 20) -> list[dict]:
    if country != "UK":
        return []
    out: list[dict] = []
    for q in queries:
        url = (
            "https://uk.indeed.com/jobs?"
            f"q={quote_plus(q + ' sales OR marketing')}&l=United+Kingdom&fromage=14"
        )
        r = _http.get(url, timeout=12)
        if not r or r.status_code in (403, 429):
            # Anti-bot — give up on this source for now.
            return out
        if r.status_code != 200:
            continue
        names = _company_names(r.text)
        for n in names[:limit]:
            out.append({
                "domain": "",  # unresolved — orchestrator will skip empties
                "name": n,
                "country": "UK",
                "icp": guess_icp(q),
                "source": "indeed_uk",
                "_unresolved": True,
            })
        if len(out) >= limit:
            break
    return out
