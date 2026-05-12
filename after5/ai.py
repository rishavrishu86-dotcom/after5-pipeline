from __future__ import annotations
"""Ollama wrapper — single call site for all local LLM work."""
import json
import ollama
from . import config

_client = ollama.Client(host=config.OLLAMA_HOST)


def generate(prompt: str, system: str | None = None, temperature: float = 0.4) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = _client.chat(
        model=config.OLLAMA_MODEL,
        messages=messages,
        options={"temperature": temperature},
    )
    return resp["message"]["content"].strip()


def classify(text: str, labels: list[str], context: str = "") -> str:
    """Pick exactly one label from `labels`. Falls back to labels[-1] on parse failure."""
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
    for label in labels:
        if label.lower() in raw:
            return label
    return labels[-1]


def first_line(company: dict, signal: dict, country: str) -> str:
    """Write a single-sentence cold-email opener that name-drops a real signal."""
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
    return generate(prompt, system=system, temperature=0.6).splitlines()[0].strip().strip('"')
