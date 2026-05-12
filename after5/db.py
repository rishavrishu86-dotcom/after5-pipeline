from __future__ import annotations
"""SQLite helpers — no ORM, plain stdlib."""
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "after5.db"
SCHEMA = Path(__file__).resolve().parent / "schema.sql"


def init():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.executescript(SCHEMA.read_text())
        _migrate(con)
    return DB_PATH


def _migrate(con) -> None:
    """Idempotent column-add migrations. Safe on every init() call."""
    reply_cols = {r[1] for r in con.execute("PRAGMA table_info(replies)").fetchall()}
    if "slack_pinged_at" not in reply_cols:
        con.execute("ALTER TABLE replies ADD COLUMN slack_pinged_at TIMESTAMP")
    company_cols = {r[1] for r in con.execute("PRAGMA table_info(companies)").fetchall()}
    if "campaign" not in company_cols:
        con.execute(
            "ALTER TABLE companies ADD COLUMN campaign TEXT DEFAULT 'icp_outreach'"
        )


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def fetchall(sql, params=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def fetchone(sql, params=()):
    with conn() as c:
        row = c.execute(sql, params).fetchone()
        return dict(row) if row else None


def execute(sql, params=()):
    with conn() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid
