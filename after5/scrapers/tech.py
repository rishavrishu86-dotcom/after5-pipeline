from __future__ import annotations
"""Tech-stack fingerprint — headers + JS tag heuristics.

Scores companies whose stack suggests they could plausibly install an AI sales
agent themselves: WordPress / Shopify / HubSpot / Webflow get a low-friction
score; bespoke or no detectable stack scores neutral.
"""
from . import _http

TAGS = {
    "WordPress": ["wp-content", "wp-includes"],
    "Shopify": ["cdn.shopify.com", "shopify.theme"],
    "Webflow": ["webflow.com", "webflow.css"],
    "HubSpot": ["hs-scripts.com", "hubspot.com/_hcms"],
    "Wix": ["static.wixstatic.com"],
    "Squarespace": ["squarespace.com"],
    "Intercom": ["widget.intercom.io"],
    "Drift": ["js.driftt.com"],
    "GA4": ["googletagmanager.com/gtag/js"],
}

FRIENDLY = {"WordPress", "Shopify", "Webflow", "HubSpot", "Wix", "Squarespace"}


def check(domain: str, country: str) -> dict:
    r = _http.get(f"https://{domain}")
    if not r or r.status_code >= 500:
        return {"score": 0, "type": "tech", "evidence": {"reachable": False}}
    html = r.text.lower()
    server = r.headers.get("server", "")
    detected = [tag for tag, needles in TAGS.items() if any(n in html for n in needles)]
    has_chat = any(t in detected for t in ("Intercom", "Drift"))
    friendly = any(t in FRIENDLY for t in detected)
    score = 0
    if friendly:
        score += 4
    if has_chat:
        score += 3  # already pays for chat → warm to AI agent
    if "GA4" in detected:
        score += 1  # measures things → cares about funnel
    return {
        "score": min(score, 10),
        "type": "tech",
        "evidence": {"detected": detected, "server": server},
    }
