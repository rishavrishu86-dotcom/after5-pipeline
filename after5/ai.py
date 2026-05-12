from __future__ import annotations
"""LLM wrapper — Groq first (cloud, free tier), Ollama fallback (local).

Why two paths:
- Local Ollama is great for development but isn't reachable from the
  deployed Render instance.
- Groq's free tier serves Llama 3.1 70B at ~30 req/min with an OpenAI-
  compatible API — usable in production for free.

If neither is available, callers get a graceful no-op rather than a crash.
"""
import json
import logging
import requests

from . import config

log = logging.getLogger(__name__)


def _generate_groq(prompt: str, system: str | None, temperature: float) -> str | None:
    if not config.GROQ_API_KEY:
        return None
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {config.GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.GROQ_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 300,
            },
            timeout=20,
        )
        if r.status_code != 200:
            log.warning("Groq returned %s: %s", r.status_code, r.text[:200])
            return None
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning("Groq call failed: %s", e)
        return None


def _generate_ollama(prompt: str, system: str | None, temperature: float) -> str | None:
    try:
        import ollama  # type: ignore
        client = ollama.Client(host=config.OLLAMA_HOST)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat(
            model=config.OLLAMA_MODEL,
            messages=messages,
            options={"temperature": temperature},
        )
        return resp["message"]["content"].strip()
    except Exception as e:
        log.warning("Ollama call failed: %s", e)
        return None


def generate(prompt: str, system: str | None = None,
             temperature: float = 0.4) -> str:
    """Try Groq → Ollama → empty string (so callers can no-op gracefully)."""
    out = _generate_groq(prompt, system, temperature)
    if out is not None:
        return out
    out = _generate_ollama(prompt, system, temperature)
    if out is not None:
        return out
    return ""


def classify(text: str, labels: list[str], context: str = "") -> str:
    """Pick exactly one label from `labels`. Falls back to labels[-1] on failure."""
    system = (
        "You are a strict classifier. Read the text and return exactly one of the "
        "allowed labels — nothing else, no punctuation, no explanation."
    )
    prompt = (
        f"Allowed labels: {', '.join(labels)}\n"
        f"{('Context: ' + context + chr(10)) if context else ''}"
        f"Text:\n{text}\n\nLabel:"
    )
    raw = generate(prompt, system=system, temperature=0.0).strip().lower()
    if not raw:
        return labels[-1]
    for label in labels:
        if label.lower() in raw:
            return label
    return labels[-1]


def first_line(company: dict, signal: dict, country: str) -> str:
    """Write a single-sentence cold-email opening line that name-drops a real signal."""
    system = (
        "You write cold-email opening lines for a B2B AI agency. "
        "One sentence, under 25 words, specific to the company, no flattery, "
        "no exclamation marks, no em-dashes. Reference the signal naturally."
    )
    prompt = (
        f"Company: {company.get('name') or company.get('domain')}\n"
        f"Country: {country}\n"
        f"Signal type: {signal.get('type')}\n"
        f"Signal evidence: {json.dumps(signal.get('evidence'))[:400]}\n\n"
        "Write the opening line:"
    )
    out = generate(prompt, system=system, temperature=0.6)
    if not out:
        return ""
    return out.splitlines()[0].strip().strip('"')
