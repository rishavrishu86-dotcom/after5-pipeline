"""Per-signal enrichers — the free-stack replacement for Apify.

Each module exposes `check(domain: str, country: str) -> dict` with shape:
    {"score": int 0..10, "type": str, "evidence": Any}
"""
from . import tech, ads, hiring, reviews

ALL = {
    "tech": tech,
    "ads": ads,
    "hiring": hiring,
    "reviews": reviews,
}
