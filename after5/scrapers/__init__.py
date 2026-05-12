from __future__ import annotations
"""Per-signal enrichers — the free-stack replacement for Apify.

Six signals per the brief (§5): tech, seo, reviews, ads, hiring, sentiment.

Each module exposes `check(domain: str, country: str) -> dict` with shape:
    {"score": int 0..10, "type": str, "evidence": Any}
"""
from . import ads, hiring, reviews, sentiment, seo, tech

ALL = {
    "tech":      tech,
    "seo":       seo,
    "reviews":   reviews,
    "ads":       ads,
    "hiring":    hiring,
    "sentiment": sentiment,
}
