from __future__ import annotations
"""Review-sentiment signal — Ollama-classified Trustpilot text.

Pulls the Trustpilot review page, extracts review snippets, asks Ollama to
classify each as positive/neutral/negative. Scores HIGH (8-10) when the page
shows real volume *and* a meaningful share of reviews complain about slow
response / no answer / missed calls — exactly the pain we sell against.

Falls back to score 0 silently if Ollama isn't reachable; this signal is
optional, the binary qualifier still works without it.
"""
import re

from .. import config
from . import _http

REVIEW_TEXT_RE = re.compile(
    r'"reviewBody"\s*:\s*"((?:[^"\\]|\\.)*)"', re.IGNORECASE
)

SLOW_KEYWORDS = (
    "slow", "no response", "no reply", "no answer", "never got back",
    "didn't respond", "took ages", "ignored",
)


def _trustpilot_reviews(domain: str, limit: int = 8) -> list[str]:
    r = _http.get(f"https://www.trustpilot.com/review/{domain}")
    if not r or r.status_code != 200:
        return []
    out: list[str] = []
    for m in REVIEW_TEXT_RE.finditer(r.text):
        text = m.group(1).encode().decode("unicode_escape", errors="replace")
        text = re.sub(r"\s+", " ", text).strip()
        if 30 < len(text) < 600 and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _ollama_classify(text: str) -> str:
    """Returns 'positive' / 'neutral' / 'negative'. 'neutral' on any failure."""
    try:
        from .. import ai
        labels = ["positive", "neutral", "negative"]
        return ai.classify(text[:1500], labels, context="Customer review")
    except Exception:
        return "neutral"


def check(domain: str, country: str) -> dict:
    reviews = _trustpilot_reviews(domain)
    if not reviews:
        return {"score": 0, "type": "sentiment",
                "evidence": {"reason": "no reviews scraped"}}

    pos = neu = neg = 0
    slow_complaints = 0
    if config.OLLAMA_HOST:
        for text in reviews:
            label = _ollama_classify(text)
            if label == "positive": pos += 1
            elif label == "negative": neg += 1
            else: neu += 1
            if any(k in text.lower() for k in SLOW_KEYWORDS):
                slow_complaints += 1
    else:
        # No Ollama — fall back to keyword sniff only.
        for text in reviews:
            if any(k in text.lower() for k in SLOW_KEYWORDS):
                slow_complaints += 1
                neg += 1
            else:
                neu += 1

    total = pos + neu + neg or 1
    neg_share = neg / total
    score = 0
    if slow_complaints >= 2:
        score += 6      # the perfect target — visible response-pain
    elif slow_complaints == 1:
        score += 3
    if neg_share >= 0.4:
        score += 2
    if total >= 6 and neg_share >= 0.25:
        score += 2
    return {
        "score": min(score, 10),
        "type": "sentiment",
        "evidence": {
            "reviews_scanned": total,
            "negative": neg,
            "slow_complaints": slow_complaints,
        },
    }
