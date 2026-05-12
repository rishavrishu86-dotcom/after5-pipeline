from __future__ import annotations
"""All login-gated page routes."""
from flask import Flask, render_template, request, redirect, url_for, flash

from pathlib import Path

from .. import db, send
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

    @app.route("/templates/<path:rel>", methods=["GET", "POST"])
    @login_required
    def template_edit(rel):
        # Defence: path must stay inside TEMPLATE_DIR (no ../ traversal).
        target = (TEMPLATE_DIR / rel).resolve()
        if not str(target).startswith(str(TEMPLATE_DIR.resolve())) or not target.is_file():
            return ("not found", 404)
        if request.method == "POST":
            body = request.form.get("body", "")
            target.write_text(body)
            flash(f"saved {rel}", "ok")
            return redirect(url_for("template_edit", rel=rel))
        return render_template(
            "template_edit.html",
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
