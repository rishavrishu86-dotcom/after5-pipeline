from __future__ import annotations
"""Source-discovery modules — free-stack replacement for WF1 (Rightmove/Bayut/etc).

Each module exposes:
    discover(country: str, queries: list[str], limit: int) -> list[dict]

Returned dicts have shape:
    {"domain": str, "name": str, "country": "UK"|"UAE", "icp": str|None, "source": str}
"""
from . import bayt, gulftalent, indeed_uk, web_search

ALL = {
    "web_search":  web_search,
    "indeed_uk":   indeed_uk,
    "bayt":        bayt,
    "gulftalent":  gulftalent,
}
