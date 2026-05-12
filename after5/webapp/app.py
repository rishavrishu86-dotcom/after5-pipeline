from __future__ import annotations
"""Flask application factory — single APP_PASSWORD session login.

Run:  python -m after5.webapp.app
"""
import secrets
from functools import wraps

from flask import (
    Flask, redirect, render_template, request, session, url_for, flash, abort,
)

from .. import config
from . import jobs, routes

SECRET_KEY_FILE = ".flask_secret"


def _secret_key() -> str:
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent.parent / SECRET_KEY_FILE
    if p.exists():
        return p.read_text().strip()
    s = secrets.token_hex(32)
    p.write_text(s)
    return s


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = _secret_key()

    @app.context_processor
    def inject_layout_globals():
        """Sidebar needs these on every authenticated page."""
        from .. import db as _db
        try:
            needs_louis = _db.fetchone(
                "SELECT COUNT(*) AS n FROM replies "
                "WHERE needs_louis=1 AND louis_responded=0"
            )["n"]
        except Exception:
            needs_louis = 0
        return {
            "smtp_user": config.SMTP_USER,
            "needs_louis_badge": needs_louis or None,
            "country_hint": "UK",
        }

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            pw = request.form.get("password", "")
            if pw and pw == config.APP_PASSWORD:
                session["authed"] = True
                return redirect(request.args.get("next") or url_for("dashboard"))
            flash("wrong password", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # Routes module attaches the rest, gated by login_required.
    routes.register(app, login_required)
    jobs.register(app, login_required)
    return app


app = create_app()


if __name__ == "__main__":
    import logging
    import os
    logging.basicConfig(level=logging.INFO)
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8001"))
    app.run(host=host, port=port, debug=False)
