from __future__ import annotations
"""Slack incoming-webhook wrapper. Stdout fallback when no webhook is set."""
import json
import requests

from . import config


def slack(text: str, blocks: list | None = None) -> bool:
    """Post to SLACK_WEBHOOK_URL. Returns True on 200, False otherwise.
    Falls back to printing when no webhook is configured — keeps dev runs quiet."""
    if not config.SLACK_WEBHOOK_URL:
        print(f"[slack] {text}")
        return False
    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        r = requests.post(
            config.SLACK_WEBHOOK_URL,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        return r.status_code == 200
    except requests.RequestException:
        return False
