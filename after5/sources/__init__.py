from __future__ import annotations
"""Source-discovery modules — free-stack replacement for WF1 (Rightmove/Bayut/etc).

Each module exposes:
    discover(country: str, queries: list[str], limit: int) -> list[dict]

Returned dicts have shape:
    {"domain": str, "name": str, "country": "UK"|"UAE",
     "icp": str|None, "source": str, "campaign": str|None}
"""
from . import bayt, clutch_agency, gulftalent, hiring_signal, indeed_uk, web_search

ALL = {
    # Campaign 1 — ICP outreach
    "web_search":      web_search,
    "indeed_uk":       indeed_uk,
    "bayt":            bayt,
    "gulftalent":      gulftalent,
    # Campaign 2 — hiring signal
    "hiring_signal":   hiring_signal,
    # Campaign 3 — agency partnership
    "clutch_agency":   clutch_agency,
}
