from __future__ import annotations
"""Per-contact personalisation — picks strongest signal, asks Ollama for line."""
import json
from . import db, ai

SIGNAL_PRIORITY = ["ads", "hiring", "reviews", "tech"]


def _strongest_signal(signals_json: str | None) -> dict | None:
    if not signals_json:
        return None
    try:
        signals = json.loads(signals_json)
    except (TypeError, ValueError):
        return None
    candidates = [
        s for s in signals.values()
        if isinstance(s, dict) and s.get("score", 0) > 0
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda s: (
            s.get("score", 0),
            -SIGNAL_PRIORITY.index(s["type"]) if s.get("type") in SIGNAL_PRIORITY else -99,
        ),
        reverse=True,
    )
    return candidates[0]


def run(limit: int | None = None) -> int:
    rows = db.fetchall(
        """
        SELECT c.id AS contact_id, c.first_name, co.name, co.domain, co.country, co.signals
        FROM contacts c
        JOIN companies co ON co.id = c.company_id
        WHERE c.ai_first_line IS NULL
          AND c.unsubscribed = 0
          AND co.status = 'qualified'
        ORDER BY co.total_score DESC
        """
        + (f" LIMIT {int(limit)}" if limit else "")
    )
    written = 0
    for r in rows:
        signal = _strongest_signal(r["signals"])
        if not signal:
            continue
        try:
            line = ai.first_line(
                {"name": r["name"], "domain": r["domain"]},
                signal,
                r["country"],
            )
        except Exception:
            continue
        if not line:
            continue
        with db.conn() as c:
            c.execute(
                "UPDATE contacts SET ai_first_line=?, signal_used=?, ready_to_send=1, "
                "next_send_day=1 WHERE id=?",
                (line, signal.get("type"), r["contact_id"]),
            )
        written += 1
    return written
