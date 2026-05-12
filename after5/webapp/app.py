from __future__ import annotations
"""Flask application factory — hardened single-tenant auth.

Run:  python -m after5.webapp.app
"""
import logging
import os
import secrets
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request,
    session, url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect, generate_csrf
from werkzeug.security import check_password_hash, generate_password_hash

from .. import config
from . import jobs, routes

SECRET_KEY_FILE = ".flask_secret"
MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB — covers a roomy CSV
log = logging.getLogger(__name__)


def _secret_key() -> str:
    """FLASK_SECRET_KEY env wins. Falls back to on-disk file (dev only).

    On Render set FLASK_SECRET_KEY as an env var so sessions survive deploys.
    """
    env = os.environ.get("FLASK_SECRET_KEY", "").strip()
    if env:
        return env
    p = Path(__file__).resolve().parent.parent.parent / SECRET_KEY_FILE
    if p.exists():
        return p.read_text().strip()
    s = secrets.token_hex(32)
    try:
        p.write_text(s)
    except OSError:
        pass  # read-only filesystem — fine, generated each boot
    return s


def _password_ok(submitted: str) -> bool:
    """Compare submitted password against APP_PASSWORD.

    Supports either a plaintext APP_PASSWORD (dev) or an APP_PASSWORD_HASH
    (production, werkzeug.generate_password_hash). Hash wins if both set.
    """
    if not submitted:
        return False
    hashed = os.environ.get("APP_PASSWORD_HASH", "").strip()
    if hashed:
        try:
            return check_password_hash(hashed, submitted)
        except Exception:
            return False
    expected = config.APP_PASSWORD or ""
    if not expected:
        return False
    return secrets.compare_digest(submitted, expected)


def _safe_next(target: str | None) -> str:
    """Return target only if it's a relative path on this app (open-redirect-proof)."""
    if not target:
        return url_for("dashboard")
    # Reject anything with a scheme or netloc.
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return url_for("dashboard")
    # Must start with '/', and not '//' (protocol-relative).
    if not target.startswith("/") or target.startswith("//"):
        return url_for("dashboard")
    return target


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def _refuse_insecure_boot() -> None:
    """Refuse to start with no password or the publicly-known default.

    Falls back to a clear error rather than silently accepting `change-me`
    or empty, which would put a public Render URL behind no real auth.
    """
    if os.environ.get("APP_PASSWORD_HASH", "").strip():
        return  # hash overrides plaintext; no plaintext check needed
    pw = (config.APP_PASSWORD or "").strip()
    if not pw or pw.lower() in ("change-me", "changeme", "password", "admin"):
        raise RuntimeError(
            "INSECURE BOOT REFUSED — APP_PASSWORD is empty or the known "
            "default. Set APP_PASSWORD to a strong value, or set "
            "APP_PASSWORD_HASH (from werkzeug.security.generate_password_hash) "
            "in your environment. See /setup in the dashboard for guidance."
        )


def create_app() -> Flask:
    _refuse_insecure_boot()
    app = Flask(__name__)
    app.secret_key = _secret_key()
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("RENDER", "") != "",
        WTF_CSRF_TIME_LIMIT=None,  # session-lifetime tokens, fine for our use
    )

    csrf = CSRFProtect(app)

    # Don't CSRF-protect HTMX job-trigger POSTs (they go through CSRFProtect
    # too — we'll exempt by sending the token via a request header instead).
    # Instead, expose the token to every template and let HTMX send it.

    @app.context_processor
    def inject_csrf():
        return {"csrf_token": generate_csrf}

    # Security headers — HSTS only on HTTPS (Render terminates TLS for us).
    # CSP is permissive enough for our HTMX + lucide CDN + inline scripts.
    Talisman(
        app,
        force_https=os.environ.get("RENDER", "") != "",
        strict_transport_security=True,
        session_cookie_secure=os.environ.get("RENDER", "") != "",
        frame_options="DENY",
        content_security_policy={
            "default-src": "'self'",
            "script-src":  ["'self'", "'unsafe-inline'", "https://unpkg.com"],
            "style-src":   ["'self'", "'unsafe-inline'"],
            "img-src":     ["'self'", "data:"],
            "connect-src": "'self'",
            "frame-ancestors": "'none'",
        },
        content_security_policy_nonce_in=[],
    )

    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per minute"],
        storage_uri="memory://",
    )

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
    @limiter.limit("5 per minute; 30 per hour", methods=["POST"])
    def login():
        if request.method == "POST":
            pw = request.form.get("password", "")
            if _password_ok(pw):
                session.clear()
                session["authed"] = True
                session.permanent = False
                next_target = _safe_next(request.args.get("next"))
                _audit("login_ok", request.remote_addr or "?")
                return redirect(next_target)
            _audit("login_fail", request.remote_addr or "?")
            flash("wrong password", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # Health endpoint — useful for uptime monitors hitting it externally
    # to keep the Render free-tier instance awake.
    @app.route("/healthz")
    def healthz():
        return jsonify({"ok": True})

    # Routes module attaches the rest, gated by login_required.
    routes.register(app, login_required)
    jobs.register(app, login_required, csrf=csrf, limiter=limiter)
    return app


def _audit(event: str, who: str, detail: str = "") -> None:
    """Best-effort audit logger. Writes to audit_log table if available,
    falls back to stderr."""
    try:
        from .. import db as _db
        with _db.conn() as c:
            c.execute(
                "INSERT INTO audit_log (event, who, detail) VALUES (?, ?, ?)",
                (event, who, detail),
            )
    except Exception as e:
        log.warning("audit (%s/%s/%s) fallback: %s", event, who, detail, e)


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8001"))
    app.run(host=host, port=port, debug=False)
