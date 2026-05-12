from __future__ import annotations
"""Hiring signal — careers page probe + role keywords.

A company hiring SDRs, BDRs, or customer-success people is feeling the pain
that an AI sales agent solves. We probe common careers paths and look for
relevant role titles.
"""
from . import _http

PATHS = ["/careers", "/jobs", "/work-with-us", "/join-us", "/about/careers"]
ROLE_KEYWORDS = [
    "sdr", "bdr", "sales development", "business development",
    "customer success", "account executive", "outbound", "inside sales",
]


def check(domain: str, country: str) -> dict:
    found_page = None
    hits: list[str] = []
    for path in PATHS:
        r = _http.get(f"https://{domain}{path}")
        if r and r.status_code == 200 and len(r.text) > 500:
            found_page = path
            body = r.text.lower()
            hits = [k for k in ROLE_KEYWORDS if k in body]
            break
    score = 0
    if found_page:
        score += 2
    score += min(len(hits) * 2, 8)
    return {
        "score": min(score, 10),
        "type": "hiring",
        "evidence": {"page": found_page, "roles": hits},
    }
