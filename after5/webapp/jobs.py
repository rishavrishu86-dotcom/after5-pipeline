from __future__ import annotations
"""Background job runner — fire pipeline stages from the UI, poll status via HTMX.

Jobs run in daemon threads. State lives in a process-local dict; restart wipes it.
That's fine: real cron is the scheduler, this is just operator on-demand.
"""
import io
import threading
import time
import traceback
import uuid
from contextlib import redirect_stdout
from typing import Callable

from flask import Flask, abort, jsonify, render_template, request

from .. import (
    bounces, contacts, discover, enrich, loom, personalise, qualify,
    send, triage,
)

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()

JOB_FACTORIES: dict[str, Callable[..., dict | int]] = {
    "discover": lambda: discover.run(limit_per_source=15),
    "enrich": lambda: enrich.run(limit=50),
    "qualify": qualify.run,
    "find-contacts": lambda: contacts.find_all(limit=20),
    "personalise": lambda: personalise.run(limit=200),
    "send-dry": lambda: send.run(dry_run=True),
    "send-live": lambda: send.run(dry_run=False),
    "triage": triage.run,
    "bounces": bounces.run,
    "loom-check": lambda: loom.run(hours=48),
}


def _run(job_id: str, name: str) -> None:
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            result = JOB_FACTORIES[name]()
        with _LOCK:
            _JOBS[job_id].update(
                status="done",
                result=result,
                stdout=buf.getvalue(),
                finished_at=time.time(),
            )
    except Exception as e:
        tb = traceback.format_exc(limit=6)
        with _LOCK:
            _JOBS[job_id].update(
                status="error",
                error=str(e),
                traceback=tb,
                stdout=buf.getvalue(),
                finished_at=time.time(),
            )


def start(name: str) -> str:
    if name not in JOB_FACTORIES:
        raise ValueError(f"unknown job: {name}")
    job_id = uuid.uuid4().hex[:8]
    with _LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "name": name,
            "status": "running",
            "started_at": time.time(),
        }
    t = threading.Thread(target=_run, args=(job_id, name), daemon=True)
    t.start()
    return job_id


def get(job_id: str) -> dict | None:
    with _LOCK:
        return dict(_JOBS[job_id]) if job_id in _JOBS else None


def recent(n: int = 12) -> list[dict]:
    with _LOCK:
        rows = list(_JOBS.values())
    rows.sort(key=lambda r: r.get("started_at", 0), reverse=True)
    return rows[:n]


def register(app: Flask, login_required) -> None:
    @app.post("/jobs/<name>")
    @login_required
    def start_job(name):
        if name not in JOB_FACTORIES:
            abort(404)
        job_id = start(name)
        return render_template("_job_row.html", job=get(job_id))

    @app.get("/jobs/<job_id>")
    @login_required
    def poll_job(job_id):
        job = get(job_id)
        if not job:
            abort(404)
        return render_template("_job_row.html", job=job)
