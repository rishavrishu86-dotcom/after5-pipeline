from __future__ import annotations
"""GulfTalent source — best-effort.

Public job listings include the hiring company's name and (sometimes) a link
to the company's own website. Falls back to empty silently on layout changes.
"""
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from ..scrapers import _http
from ._common import guess_icp, is_junk, normalise_domain

BASE = "https://www.gulftalent.com"


def _company_profile_urls(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []
    for a in soup.select('a[href*="/employer/"]'):
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
    for a in soup.select('a[href^="http"]'):
        href = a.get("href") or ""
        text = a.get_text(strip=True).lower()
        if "gulftalent.com" in href:
            continue
        if "website" in text or text.startswith("www") or text.startswith("http"):
            return href
    return None


def discover(country: str, queries: list[str], limit: int = 20) -> list[dict]:
    if country != "UAE":
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for q in queries:
        url = f"{BASE}/jobs/search?keywords={quote_plus(q)}&country=United+Arab+Emirates"
        r = _http.get(url, timeout=15)
        if not r or r.status_code != 200:
            continue
        for profile, name in _company_profile_urls(r.text):
            site = _company_website(profile)
            d = normalise_domain(site or "")
            if not d or is_junk(d) or d in seen:
                continue
            seen.add(d)
            out.append({
                "domain": d,
                "name": name[:80],
                "country": "UAE",
                "icp": guess_icp(q),
                "source": "gulftalent",
            })
            if len(out) >= limit:
                return out
    return out
