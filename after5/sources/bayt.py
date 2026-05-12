from __future__ import annotations
"""Bayt UAE source — best-effort.

Bayt's job-search HTML is reasonably stable. We list jobs by query, extract
company names, and try to follow company-profile links to find any "Website"
field. Domains there are often dirty (linkedin.com etc) — we filter via
_common.is_junk.
"""
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from ..scrapers import _http
from ._common import guess_icp, is_junk, normalise_domain

BASE = "https://www.bayt.com"


def _company_links(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []
    for a in soup.select('a[href*="/en/company/"]'):
        href = a.get("href") or ""
        name = a.get_text(strip=True)
        if href and name and (href, name) not in out:
            out.append((href, name))
    return out


def _company_website(profile_url: str) -> str | None:
    r = _http.get(urljoin(BASE, profile_url), timeout=12)
    if not r or r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    # The website usually appears as <a href="http..." rel="nofollow"> in the company info block.
    for a in soup.select('a[rel="nofollow"][href^="http"]'):
        href = a.get("href")
        if href and "bayt.com" not in href:
            return href
    return None


def discover(country: str, queries: list[str], limit: int = 20) -> list[dict]:
    if country != "UAE":
        return []
    out: list[dict] = []
    seen_domains: set[str] = set()
    for q in queries:
        url = f"{BASE}/en/uae/jobs/?xc_keyword={quote_plus(q)}"
        r = _http.get(url, timeout=15)
        if not r or r.status_code != 200:
            continue
        for profile, name in _company_links(r.text):
            site = _company_website(profile)
            d = normalise_domain(site or "")
            if not d or is_junk(d) or d in seen_domains:
                continue
            seen_domains.add(d)
            out.append({
                "domain": d,
                "name": name[:80],
                "country": "UAE",
                "icp": guess_icp(q),
                "source": "bayt",
            })
            if len(out) >= limit:
                return out
    return out
