from __future__ import annotations
"""Shared helpers for source-discovery scrapers."""
import re
from urllib.parse import urlparse

# Aggregator / social / utility domains we never want as a "lead".
JUNK_DOMAINS = {
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "youtube.com", "wikipedia.org", "amazon.com", "amazon.co.uk", "ebay.com",
    "indeed.com", "indeed.co.uk", "uk.indeed.com", "indeed.ae",
    "bayt.com", "gulftalent.com", "monster.com", "reed.co.uk",
    "totaljobs.com", "naukrigulf.com", "glassdoor.com", "glassdoor.co.uk",
    "crunchbase.com", "bloomberg.com", "reuters.com", "ft.com", "bbc.co.uk",
    "google.com", "google.co.uk", "google.ae", "duckduckgo.com", "bing.com",
    "yelp.com", "yelp.co.uk", "trustpilot.com", "trustpilot.co.uk",
    "github.com", "gitlab.com", "medium.com", "substack.com",
    "yellowpages.com", "yell.com", "companieshouse.gov.uk",
    "apple.com", "microsoft.com", "wordpress.com", "wix.com", "squarespace.com",
}


def normalise_domain(url_or_domain: str) -> str | None:
    """Take any URL/domain string, return apex-ish domain or None."""
    if not url_or_domain:
        return None
    s = url_or_domain.strip().lower()
    if "://" not in s:
        s = "http://" + s
    try:
        host = urlparse(s).hostname or ""
    except ValueError:
        return None
    if not host:
        return None
    # strip leading www. and m. subdomains
    host = re.sub(r"^(www\.|m\.|en\.)", "", host)
    # crude apex extraction — keep last two labels, plus extra label for known cctld pairs
    parts = host.split(".")
    if len(parts) < 2:
        return None
    cctld_pairs = {("co", "uk"), ("ac", "uk"), ("org", "uk"),
                   ("gov", "uk"), ("co", "ae"), ("com", "ae")}
    if len(parts) >= 3 and tuple(parts[-2:]) in cctld_pairs:
        host = ".".join(parts[-3:])
    else:
        host = ".".join(parts[-2:])
    return host


def is_junk(domain: str) -> bool:
    if not domain:
        return True
    return domain in JUNK_DOMAINS or any(
        domain.endswith("." + j) for j in JUNK_DOMAINS
    )


def guess_icp(text: str, fallback: str | None = None) -> str | None:
    """Cheap keyword sniff to pick a category."""
    if not text:
        return fallback
    t = text.lower()
    rules = [
        ("fintech",       ["fintech", "bank", "lending", "payments", "crypto"]),
        ("proptech",      ["property", "real estate", "estate agent", "letting"]),
        ("d2c",           ["ecommerce", "e-commerce", "direct to consumer", "shopify", "d2c"]),
        ("marketplace",   ["marketplace", "platform", "two-sided", "aggregator"]),
        ("saas",          ["saas", "software", "platform-as-a-service"]),
        ("healthtech",    ["health", "clinic", "telemedicine", "medtech"]),
        ("foodtech",      ["food", "restaurant", "delivery", "kitchen", "cloud kitchen"]),
        ("insurtech",     ["insurance", "insurtech", "underwriting"]),
        ("agency",        ["agency", "marketing agency", "digital agency"]),
        ("hospitality",   ["hotel", "hospitality", "resort"]),
        ("travel",        ["travel", "booking", "tourism"]),
    ]
    for label, kws in rules:
        if any(k in t for k in kws):
            return label
    return fallback
