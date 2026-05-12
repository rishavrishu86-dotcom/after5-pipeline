from __future__ import annotations
"""Active-ads signal — Meta Ad Library API (free, official).

If a company is running paid ads they're actively spending on growth, which
makes them a hotter prospect for an AI sales agent. Falls back to a Google Ads
Transparency Center HTML probe when no Meta token is set.
"""
from urllib.parse import quote_plus
from . import _http
from .. import config


def _meta_ad_count(name: str) -> int | None:
    if not config.META_AD_LIBRARY_TOKEN:
        return None
    url = (
        "https://graph.facebook.com/v18.0/ads_archive"
        f"?search_terms={quote_plus(name)}"
        "&ad_active_status=ACTIVE&ad_reached_countries=['GB','AE']"
        f"&access_token={config.META_AD_LIBRARY_TOKEN}&limit=25"
    )
    r = _http.get(url)
    if not r or r.status_code != 200:
        return None
    try:
        return len(r.json().get("data", []))
    except ValueError:
        return None


def _google_transparency_hit(domain: str) -> bool:
    r = _http.get(f"https://adstransparency.google.com/?region=anywhere&domain={domain}")
    return bool(r and r.status_code == 200 and domain.lower() in r.text.lower())


def check(domain: str, country: str) -> dict:
    name = domain.split(".")[0]
    meta = _meta_ad_count(name)
    google = _google_transparency_hit(domain)
    score = 0
    if meta:
        score += min(meta, 6)
    if google:
        score += 3
    return {
        "score": min(score, 10),
        "type": "ads",
        "evidence": {"meta_active": meta, "google_transparency": google},
    }
