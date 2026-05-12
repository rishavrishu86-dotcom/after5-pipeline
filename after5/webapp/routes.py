from __future__ import annotations
"""All login-gated page routes."""
from flask import Flask, render_template, request, redirect, url_for, flash

import tempfile
from pathlib import Path

from .. import contacts as contacts_mod
from .. import db, seed, send
from . import jobs

TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


def _kpis() -> dict:
    one = lambda sql, p=(): db.fetchone(sql, p)["n"]  # noqa: E731
    return {
        "total":       one("SELECT COUNT(*) AS n FROM companies"),
        "new":         one("SELECT COUNT(*) AS n FROM companies WHERE status='new'"),
        "contacted":   one(
            "SELECT COUNT(DISTINCT contact_id) AS n FROM sends"
        ),
        "qualified":   one("SELECT COUNT(*) AS n FROM companies WHERE status='qualified'"),
        "interested":  one(
            "SELECT COUNT(*) AS n FROM replies WHERE classification='interested'"
        ),
        "needs_louis": one(
            "SELECT COUNT(*) AS n FROM replies "
            "WHERE needs_louis=1 AND louis_responded=0"
        ),
        "sent":        one("SELECT COUNT(*) AS n FROM sends"),
    }


def _recent_leads(n: int = 6) -> list[dict]:
    return db.fetchall(
        """
        SELECT co.id, co.name, co.domain, co.country, co.icp, co.source,
               co.status, co.priority, co.total_score, co.created_at,
               c.first_name, c.last_name, c.email, c.signal_used
        FROM companies co
        LEFT JOIN contacts c ON c.id = (
            SELECT id FROM contacts WHERE company_id = co.id LIMIT 1
        )
        ORDER BY co.created_at DESC
        LIMIT ?
        """,
        (n,),
    )


def _top_sources(n: int = 6) -> list[dict]:
    return db.fetchall(
        """
        SELECT COALESCE(NULLIF(icp,''), 'unknown') AS name, COUNT(*) AS count
        FROM companies
        GROUP BY name
        ORDER BY count DESC
        LIMIT ?
        """,
        (n,),
    )


def _activity(n: int = 8) -> list[dict]:
    """Unified feed: company-added + reply-received + email-sent."""
    rows = db.fetchall(
        """
        SELECT kind, label, ts FROM (
          SELECT 'company' AS kind,
                 COALESCE(name, domain) AS label,
                 created_at AS ts
            FROM companies
          UNION ALL
          SELECT 'reply', COALESCE(co.name, co.domain) || ' · ' || r.classification,
                 r.received_at
            FROM replies r
            JOIN contacts c ON c.id=r.contact_id
            JOIN companies co ON co.id=c.company_id
          UNION ALL
          SELECT 'send', COALESCE(co.name, co.domain) || ' · D' || s.sequence_day,
                 s.sent_at
            FROM sends s
            JOIN contacts c ON c.id=s.contact_id
            JOIN companies co ON co.id=c.company_id
        )
        ORDER BY ts DESC
        LIMIT ?
        """,
        (n,),
    )
    return rows


def register(app: Flask, login_required) -> None:
    @app.route("/")
    @login_required
    def dashboard():
        camp_rows = db.fetchall(
            """
            SELECT campaign,
                   COUNT(*) AS count,
                   SUM(CASE WHEN status='qualified' THEN 1 ELSE 0 END) AS qualified
            FROM companies
            WHERE campaign IS NOT NULL
            GROUP BY campaign
            """
        )
        camp_meta = {
            "icp_outreach":       {"label": "Campaign 1 — ICP",          "icon": "violet", "lucide": "target"},
            "hiring_signal":      {"label": "Campaign 2 — Hiring",       "icon": "amber",  "lucide": "briefcase"},
            "agency_partnership": {"label": "Campaign 3 — Agency",       "icon": "green",  "lucide": "handshake"},
        }
        campaigns = []
        for r in camp_rows:
            meta = camp_meta.get(r["campaign"], {"label": r["campaign"], "icon": "blue", "lucide": "circle"})
            campaigns.append({**meta, "count": r["count"], "qualified": r["qualified"] or 0})
        return render_template(
            "dashboard.html",
            kpis=_kpis(),
            campaigns=campaigns,
            recent_leads=_recent_leads(),
            top_sources=_top_sources(),
            activity=_activity(),
            recent_jobs=jobs.recent(),
            job_names=list(jobs.JOB_FACTORIES.keys()),
        )

    @app.route("/companies")
    @login_required
    def companies():
        q = (request.args.get("q") or "").strip()
        country = request.args.get("country") or ""
        status = request.args.get("status") or ""
        priority = request.args.get("priority") or ""
        campaign = request.args.get("campaign") or ""
        where = ["1=1"]
        params: list = []
        if q:
            where.append("(domain LIKE ? OR name LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        if country in ("UK", "UAE"):
            where.append("country=?")
            params.append(country)
        if status:
            where.append("status=?")
            params.append(status)
        if priority:
            where.append("priority=?")
            params.append(priority)
        if campaign:
            where.append("campaign=?")
            params.append(campaign)
        rows = db.fetchall(
            f"SELECT * FROM companies WHERE {' AND '.join(where)} "
            "ORDER BY total_score DESC, id DESC LIMIT 300",
            tuple(params),
        )
        return render_template(
            "companies.html",
            rows=rows, q=q, country=country, status=status,
            priority=priority, campaign=campaign,
        )

    @app.route("/companies/<int:cid>")
    @login_required
    def company_detail(cid):
        company = db.fetchone("SELECT * FROM companies WHERE id=?", (cid,))
        if not company:
            return ("not found", 404)
        contacts_ = db.fetchall(
            "SELECT * FROM contacts WHERE company_id=? ORDER BY id", (cid,)
        )
        sends_ = db.fetchall(
            """
            SELECT s.*, c.email FROM sends s
            JOIN contacts c ON c.id = s.contact_id
            WHERE c.company_id = ? ORDER BY s.sent_at DESC
            """,
            (cid,),
        )
        touches_ = db.fetchall(
            """
            SELECT t.*, c.first_name, c.last_name, c.email
            FROM touches t JOIN contacts c ON c.id = t.contact_id
            WHERE c.company_id = ?
            ORDER BY t.day ASC, t.created_at DESC
            """,
            (cid,),
        )
        return render_template(
            "company_detail.html",
            company=company, contacts=contacts_, sends=sends_, touches=touches_,
        )

    @app.route("/setup")
    @login_required
    def setup_status():
        """Operator cockpit — shows which env vars are set and what's missing.

        This is the page you stare at when going from demo → production.
        """
        from .. import config as cfg
        import os
        def chk(value, *, recommended: bool = False, secret: bool = True) -> dict:
            ok = bool(value and str(value).strip())
            display = "" if not ok else ("●●●●●" if secret else str(value))
            return {"ok": ok, "recommended": recommended, "display": display}

        groups = [
            {
                "label": "Auth (must-have)",
                "rows": [
                    {"key": "APP_PASSWORD",       "purpose": "Dashboard login password (or use hash below)",   **chk(cfg.APP_PASSWORD)},
                    {"key": "APP_PASSWORD_HASH",  "purpose": "werkzeug hash — preferred over plaintext",       **chk(os.environ.get("APP_PASSWORD_HASH"), recommended=True)},
                    {"key": "FLASK_SECRET_KEY",   "purpose": "Session signing key (Render auto-generates)",    **chk(os.environ.get("FLASK_SECRET_KEY"))},
                    {"key": "CRON_TOKEN",         "purpose": "Shared secret for /cron/<job> webhook",          **chk(cfg.CRON_TOKEN, recommended=True)},
                ],
            },
            {
                "label": "Sending (must-have for real email)",
                "rows": [
                    {"key": "SMTP_USER",     "purpose": "Sending Gmail address",                  **chk(cfg.SMTP_USER, secret=False)},
                    {"key": "SMTP_PASS",     "purpose": "Gmail App Password (16-char)",           **chk(cfg.SMTP_PASS)},
                    {"key": "SENDER_NAME",   "purpose": "Display name in From: header",           **chk(cfg.SENDER_NAME, secret=False)},
                    {"key": "REPLY_TO",      "purpose": "Reply-to email address",                 **chk(cfg.REPLY_TO,   secret=False)},
                ],
            },
            {
                "label": "AI personalisation (recommended)",
                "rows": [
                    {"key": "GROQ_API_KEY",  "purpose": "Cloud LLM (free tier, Llama 3.1 70B)",   **chk(cfg.GROQ_API_KEY, recommended=True)},
                    {"key": "OLLAMA_HOST",   "purpose": "Local Ollama URL (dev only)",            **chk(cfg.OLLAMA_HOST, secret=False)},
                ],
            },
            {
                "label": "Optional integrations",
                "rows": [
                    {"key": "SLACK_WEBHOOK_URL", "purpose": "Needs-Louis pings",                  **chk(cfg.SLACK_WEBHOOK_URL)},
                    {"key": "HUNTER_API_KEY",    "purpose": "Real contact enrichment (25/mo)",   **chk(cfg.HUNTER_API_KEY, recommended=True)},
                    {"key": "META_AD_LIBRARY_TOKEN", "purpose": "Better ads signal",              **chk(cfg.META_AD_LIBRARY_TOKEN)},
                ],
            },
            {
                "label": "Mode",
                "rows": [
                    {"key": "DEMO_SEED", "purpose": "Reset to demo data on cold start (set to 0 in production)",
                     "ok": os.environ.get("DEMO_SEED", "").lower() in ("0", "false", "no"),
                     "recommended": True, "display": os.environ.get("DEMO_SEED", "(unset)")},
                ],
            },
        ]

        # External cron URLs the operator needs to paste into cron-job.org.
        host = request.host_url.rstrip("/")
        token_set = bool(cfg.CRON_TOKEN)
        cron_jobs = [
            {"name": "pipeline-intake",  "when": "Weekly, Monday 06:00 UK"},
            {"name": "triage",           "when": "Daily 09:00 UK"},
            {"name": "bounces",          "when": "Daily 09:00 UK"},
            {"name": "send-live",        "when": "Daily 09:00 UK"},
            {"name": "loom-check",       "when": "Every 6 hours"},
        ]
        return render_template(
            "setup.html",
            groups=groups, cron_jobs=cron_jobs,
            host=host, token_set=token_set,
        )

    @app.route("/setup/dns")
    @login_required
    def setup_dns():
        """Generate SPF / DKIM / DMARC DNS records for any sending domain.

        Real DKIM needs a signed selector from Google Workspace's Admin
        Console. We surface the *template* + the exact Workspace steps.
        """
        domain = (request.args.get("domain") or "").strip().lower()
        records = []
        if domain:
            records = [
                {
                    "type": "TXT", "host": "@",
                    "value": "v=spf1 include:_spf.google.com ~all",
                    "note": "Authorises Gmail to send for this domain. Required.",
                },
                {
                    "type": "TXT", "host": "google._domainkey",
                    "value": "(generated in Google Workspace Admin → Apps → Gmail → Authenticate email — paste the value Google gives you)",
                    "note": "Without this real DKIM signature, ~50% of mail goes to spam.",
                },
                {
                    "type": "TXT", "host": "_dmarc",
                    "value": f"v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain}; pct=10; aspf=s; adkim=s",
                    "note": "Start permissive (p=quarantine, pct=10) — graduate to p=reject once you see no false positives.",
                },
                {
                    "type": "TXT", "host": "@",
                    "value": f"google-site-verification=(paste from Google Workspace setup)",
                    "note": "Only if you're setting up Workspace on this domain.",
                },
                {
                    "type": "MX", "host": "@",
                    "value": "1 ASPMX.L.GOOGLE.COM",
                    "note": "Plus the 4 secondary Google MX records — see Workspace setup wizard.",
                },
            ]
        return render_template("setup_dns.html", domain=domain, records=records)

    @app.route("/upload", methods=["GET", "POST"])
    @login_required
    def upload_csv():
        """AI-Ark-style intake: drop a curated CSV, get rows into the DB.

        Companies CSV columns: domain, name, country, icp[, source]
        People    CSV columns: domain, first_name, last_name, role[, email]
        """
        result = None
        if request.method == "POST":
            kind = request.form.get("kind", "companies")
            upfile = request.files.get("file")
            if not upfile or not upfile.filename:
                flash("No file selected", "error")
                return redirect(url_for("upload_csv"))
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".csv", delete=False
            ) as tmp:
                upfile.save(tmp)
                tmp_path = tmp.name
            try:
                if kind == "people":
                    stats = contacts_mod.import_people_csv(tmp_path)
                else:
                    inserted, skipped = seed.import_csv(tmp_path)
                    stats = {"inserted": inserted, "skipped": skipped}
                result = {"kind": kind, "filename": upfile.filename, "stats": stats}
                flash(f"Imported {stats.get('inserted', 0)} rows from {upfile.filename}", "ok")
            except Exception as e:
                flash(f"Import failed: {e}", "error")
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        return render_template("upload.html", result=result)

    @app.route("/automation")
    @login_required
    def automation():
        # Honest disclosure: on Render web tier, the APScheduler daemon
        # isn't running — only the web server is. We expose this so the
        # user knows manual triggers are the actual driver here.
        scheduler_running = False
        job_specs = [
            {"name": "discover",      "icon": "violet", "lucide": "radar",
             "desc": "WF1 — find new UK prospects via DuckDuckGo + hiring-signal + agency sources."},
            {"name": "enrich",        "icon": "cyan",   "lucide": "search-check",
             "desc": "WF2 — score new companies on 6 signals (tech, SEO, reviews, ads, hiring, sentiment)."},
            {"name": "qualify",       "icon": "blue",   "lucide": "filter",
             "desc": "Bucket enriched companies into hot/warm/cold using 3/6 binary threshold."},
            {"name": "find-contacts", "icon": "purple", "lucide": "user-search",
             "desc": "WF3 — find 3 decision makers per qualified company (founder + sales + marketing)."},
            {"name": "personalise",   "icon": "amber",  "lucide": "sparkles",
             "desc": "WF4 — Ollama writes a signal-aware first line per contact."},
            {"name": "send-dry",      "icon": "green",  "lucide": "eye",
             "desc": "WF5 — render every ready email, print to log, do NOT actually send."},
            {"name": "send-live",     "icon": "rose",   "lucide": "send",
             "desc": "WF5 — actually send today's batch over Gmail SMTP. Needs SMTP creds."},
            {"name": "triage",        "icon": "orange", "lucide": "mail-search",
             "desc": "WF6 — read replies via IMAP, classify with Ollama, flag needs_louis."},
            {"name": "bounces",       "icon": "rose",   "lucide": "mail-x",
             "desc": "Scan MAILER-DAEMON replies, parse DSN, suppress hard bounces (5.x.x)."},
            {"name": "loom-check",    "icon": "amber",  "lucide": "alarm-clock",
             "desc": "WF7 — Slack-nudge on interested replies >48h with no Loom sent."},
        ]
        return render_template(
            "automation.html",
            scheduler_running=scheduler_running,
            job_specs=job_specs,
            recent_jobs=jobs.recent(20),
        )

    @app.post("/contacts/<int:cid>/touches")
    @login_required
    def add_touch(cid):
        kind = request.form.get("kind", "other")
        day_raw = request.form.get("day", "")
        notes = request.form.get("notes", "").strip()
        status_ = request.form.get("status", "logged")
        try:
            day = int(day_raw) if day_raw else None
        except ValueError:
            day = None
        valid_kinds = {"linkedin_invite", "linkedin_voice", "cold_call", "loom", "other"}
        if kind not in valid_kinds:
            kind = "other"
        with db.conn() as c:
            row = c.execute(
                "SELECT company_id FROM contacts WHERE id=?", (cid,)
            ).fetchone()
            if not row:
                return ("not found", 404)
            c.execute(
                "INSERT INTO touches (contact_id, kind, day, status, notes) "
                "VALUES (?, ?, ?, ?, ?)",
                (cid, kind, day, status_, notes or None),
            )
            company_id = row["company_id"]
        flash(f"logged {kind}", "ok")
        return redirect(request.referrer or url_for("company_detail", cid=company_id))

    @app.route("/contacts")
    @login_required
    def contacts_page():
        f = request.args.get("filter") or "all"
        clauses = {
            "all": "1=1",
            "ready": "c.ready_to_send=1 AND c.unsubscribed=0",
            "verified": "c.email_verified=1",
            "unsub": "c.unsubscribed=1",
            "sent": "c.last_sent_at IS NOT NULL",
        }
        where = clauses.get(f, "1=1")
        rows = db.fetchall(
            f"""
            SELECT c.*, co.name AS company_name, co.country, co.priority, co.total_score
            FROM contacts c JOIN companies co ON co.id=c.company_id
            WHERE {where}
            ORDER BY co.total_score DESC, c.id DESC LIMIT 300
            """
        )
        return render_template("contacts.html", rows=rows, filter=f)

    @app.route("/replies")
    @login_required
    def replies():
        only = request.args.get("only") or "all"
        where = "1=1"
        if only == "needs_louis":
            where = "r.needs_louis=1 AND r.louis_responded=0"
        elif only == "interested":
            where = "r.classification='interested'"
        rows = db.fetchall(
            f"""
            SELECT r.*, c.email, c.first_name, c.last_name,
                   co.name AS company_name, co.country, co.priority
            FROM replies r
            JOIN contacts c ON c.id=r.contact_id
            JOIN companies co ON co.id=c.company_id
            WHERE {where}
            ORDER BY r.received_at DESC LIMIT 200
            """
        )
        return render_template("replies.html", rows=rows, only=only)

    @app.post("/replies/<int:rid>/responded")
    @login_required
    def mark_responded(rid):
        with db.conn() as c:
            c.execute("UPDATE replies SET louis_responded=1 WHERE id=?", (rid,))
        return redirect(request.referrer or url_for("replies"))

    @app.post("/replies/<int:rid>/loom-sent")
    @login_required
    def mark_loom_sent(rid):
        with db.conn() as c:
            c.execute("UPDATE replies SET loom_sent=1 WHERE id=?", (rid,))
        flash("Loom marked sent", "ok")
        return redirect(request.referrer or url_for("replies"))

    @app.post("/replies/<int:rid>/snooze")
    @login_required
    def snooze_reply(rid):
        with db.conn() as c:
            c.execute(
                "UPDATE replies SET slack_pinged_at = "
                "datetime('now', '+1 day') WHERE id=?",
                (rid,),
            )
        flash("Snoozed for 24h", "ok")
        return redirect(request.referrer or url_for("replies"))

    @app.route("/preview")
    @login_required
    def preview_emails():
        day_filter = request.args.get("day", "")
        params: list = []
        clause = "c.ready_to_send=1 AND c.unsubscribed=0 AND c.email IS NOT NULL"
        if day_filter in ("1", "4", "12", "30", "60", "90"):
            clause += " AND c.next_send_day=?"
            params.append(int(day_filter))
        rows = db.fetchall(
            f"""
            SELECT c.id, c.first_name, c.last_name, c.email, c.role, c.signal_used,
                   c.ai_first_line, c.next_send_day,
                   co.name AS company_name, co.domain, co.country, co.priority, co.icp
            FROM contacts c JOIN companies co ON co.id=c.company_id
            WHERE {clause} AND co.status='qualified'
            ORDER BY co.total_score DESC, c.id DESC LIMIT 50
            """,
            tuple(params),
        )
        previews = []
        for r in rows:
            try:
                subject, body = send.render_for_contact(r)
            except Exception as e:
                subject, body = f"[render error: {e}]", ""
            previews.append({**r, "subject": subject, "body": body})
        return render_template("preview.html", rows=previews, day_filter=day_filter)

    @app.route("/sent")
    @login_required
    def sent_emails():
        rows = db.fetchall(
            """
            SELECT s.id, s.sent_at, s.sequence_day, s.subject, s.body, s.message_id,
                   c.first_name, c.last_name, c.email,
                   co.name AS company_name, co.domain, co.country
            FROM sends s
            JOIN contacts c ON c.id=s.contact_id
            JOIN companies co ON co.id=c.company_id
            ORDER BY s.sent_at DESC LIMIT 200
            """
        )
        return render_template("sent.html", rows=rows)

    @app.route("/templates")
    @login_required
    def template_list():
        items = []
        if TEMPLATE_DIR.exists():
            for p in sorted(TEMPLATE_DIR.rglob("*.j2")):
                rel = p.relative_to(TEMPLATE_DIR)
                items.append({
                    "path": str(rel),
                    "size": p.stat().st_size,
                    "country": rel.parts[0].upper() if rel.parts else "",
                    "name": rel.name,
                })
        return render_template("templates.html", items=items)

    @app.route("/templates/<path:rel>", methods=["GET"])
    @login_required
    def template_view(rel):
        """Read-only template viewer.

        The in-app editor was removed: writing arbitrary text to .j2 files
        which are then rendered server-side is a Jinja SSTI primitive. Edit
        templates via git instead — Render auto-redeploys on push.
        """
        target = (TEMPLATE_DIR / rel).resolve()
        if not str(target).startswith(str(TEMPLATE_DIR.resolve())) or not target.is_file():
            return ("not found", 404)
        return render_template(
            "template_view.html",
            rel=rel, body=target.read_text(),
        )

    @app.post("/contacts/<int:cid>/unsubscribe")
    @login_required
    def unsub_contact(cid):
        row = db.fetchone("SELECT email FROM contacts WHERE id=?", (cid,))
        if row and row["email"]:
            send.unsubscribe(row["email"])
            flash(f"unsubscribed {row['email']}", "ok")
        return redirect(request.referrer or url_for("contacts_page"))
