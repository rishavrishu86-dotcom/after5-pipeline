from __future__ import annotations
"""Env-backed config — loaded once at import time."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _get(key, default=""):
    return os.environ.get(key, default)


SMTP_HOST = _get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(_get("SMTP_PORT", "587"))
SMTP_USER = _get("SMTP_USER")
SMTP_PASS = _get("SMTP_PASS")
SENDER_NAME = _get("SENDER_NAME", "Louis from After5")
REPLY_TO = _get("REPLY_TO", SMTP_USER)

OLLAMA_HOST = _get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = _get("OLLAMA_MODEL", "llama3.1:8b")

# Optional Groq fallback for AI personalisation / triage. Free tier gives
# Llama-3.1-70B at ~30 req/min — materially better than local llama3.1:8b.
# When set, ai.py prefers Groq; otherwise it tries local Ollama.
GROQ_API_KEY = _get("GROQ_API_KEY")
GROQ_MODEL = _get("GROQ_MODEL", "llama-3.1-70b-versatile")

# Shared secret for external cron triggers (e.g. cron-job.org → /cron/<job>).
# Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
CRON_TOKEN = _get("CRON_TOKEN")

SLACK_WEBHOOK_URL = _get("SLACK_WEBHOOK_URL")
META_AD_LIBRARY_TOKEN = _get("META_AD_LIBRARY_TOKEN")
HUNTER_API_KEY = _get("HUNTER_API_KEY")

IMAP_HOST = _get("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(_get("IMAP_PORT", "993"))

APP_PASSWORD = _get("APP_PASSWORD", "change-me")

DAILY_SEND_CAP = int(_get("DAILY_SEND_CAP", "80"))
# Brief §4: main sequence + long-tail nurture
SEQUENCE_DAYS = [1, 4, 12, 30, 60, 90]
