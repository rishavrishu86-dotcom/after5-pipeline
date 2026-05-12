# after5 pipeline

Free-stack rebuild of After5 Digital's UK GTM automation — discover, enrich, qualify, find-contacts, personalise, send, triage, Loom-reminder.

> **Status: Phase 0 prototype.** The architecture matches the brief, the demo dashboard works end-to-end on mock data, and core security has been hardened. Several pieces still need production work before pointing it at real prospects — see [Production readiness](#production-readiness) below.

## What's in vs not

| Brief section | Status |
|---|---|
| §2 — 7 real UK ICPs (real estate, mortgage, car dealer, solar, car finance, recruitment, gyms) | ✅ |
| §3 — 3 campaigns (ICP outreach / hiring signal / agency partnership) | ✅ campaign column + 3 sources |
| §4 — 14-day sequence (Day 1, 4, 12 + Day 30/60/90 nurture) | ✅ for email · LinkedIn + cold call are **manual log only** |
| §5 — 6-signal qualifier (tech / SEO / reviews / ads / hiring / sentiment) at 3/6 binary threshold | ✅ |
| §6 — Unique AI-generated opening line per contact | ✅ via Groq (cloud) or local Ollama |
| §7 — 3 contacts per company (Founder + Head of Sales + Head of Marketing) | ✅ Hunter first, role-pattern fallback |
| §7 — 18,000 emails/month via 15 domains × 3 inboxes | ⚠️ **single inbox today** (`DAILY_SEND_CAP=80`); scale needs multiple Gmail/Workspace accounts |

## Quick start (local)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set APP_PASSWORD + SMTP creds
python -m after5.cli init-db
DEMO_SEED=1 python examples/demo_seed.py     # optional — UI demo data
python -m after5.webapp.app                  # http://127.0.0.1:8001
```

For real AI personalisation you'll need either:
- **Local**: `ollama serve` + `ollama pull llama3.1:8b` — set `OLLAMA_HOST`
- **Cloud** (recommended for production): set `GROQ_API_KEY` from console.groq.com (free tier, Llama 3.1 70B at ~30 req/min)

## Pipeline (10 stages)

| Stage | CLI | What it does |
|---|---|---|
| Discover | `discover` | Find new UK companies via DuckDuckGo + hiring-signal + Clutch sources |
| Enrich | `enrich` | Score each on 6 signals via live HTTP |
| Qualify | `qualify` | Binary 0-6, bucket hot/warm/cold (≥3 to enter sequence) |
| Find contacts | `find-contacts` | Hunter free tier or role-pattern email guess + MX check |
| Personalise | `personalise` | Groq/Ollama writes a signal-aware first line |
| Send | `send [--dry-run]` | Gmail SMTP, day 1/4/12/30/60/90 sequencer, suppression |
| Triage | `triage` | IMAP read, LLM classifier, Slack flag on interested |
| Bounces | `bounces` | Parse DSN; suppress hard fails (5.x.x), retry soft (4.x.x) |
| Loom reminder | `loom-check` | Slack-nudge if interested replies sit >48h with no Loom |
| Pipeline intake | `discover → enrich → qualify` chained | Dashboard's primary green button |

## Stack

Python 3.11 + Flask + SQLite + Gmail SMTP/IMAP + Groq (free tier) / local Ollama. No paid SaaS required to run; ~£12–50/year for a sending domain.

## Security

This is a single-tenant operator dashboard. As of the latest commit:

- ✅ CSRF protection on all POST endpoints (flask-wtf)
- ✅ Rate-limited login (5/min, 30/hour per IP)
- ✅ Password support via `APP_PASSWORD_HASH` (werkzeug hash, preferred) or `APP_PASSWORD` (plaintext, dev)
- ✅ HSTS / CSP / X-Frame-Options via flask-talisman
- ✅ SSRF guard — scrapers block private, loopback, link-local, and metadata IPs
- ✅ CSV upload capped at 2 MB / 5000 rows
- ✅ Open-redirect guard on `/login?next=`
- ✅ HttpOnly + SameSite=Lax + Secure (on Render) session cookies
- ✅ `FLASK_SECRET_KEY` from env (Render generates one automatically)
- ✅ Audit log (`audit_log` table) for every job trigger
- ✅ In-app template editor **removed** (was a Jinja SSTI primitive). Edit templates in git and push.
- ✅ Unsubscribe DELETES personal data (UK GDPR Art 17) and keeps a hashed suppression row

Still on the to-do list:
- ⚠️ Per-IP brute-force lockout (currently rate-limit only)
- ⚠️ 2FA on the admin login
- ⚠️ Separate IMAP credential (today shares with SMTP)

## Deploy

`render.yaml` is included. Push to GitHub → Render reads the blueprint → set these env vars in the Render dashboard:

| Env var | Required? | Notes |
|---|---|---|
| `APP_PASSWORD` | yes (or `APP_PASSWORD_HASH`) | Login password |
| `APP_PASSWORD_HASH` | optional | `werkzeug.security.generate_password_hash(...)` — preferred over plaintext |
| `FLASK_SECRET_KEY` | auto | Render generates a stable secret |
| `SMTP_USER` / `SMTP_PASS` | for sending | Gmail App Password, **never** main account password |
| `SENDER_NAME` / `REPLY_TO` | for sending | Identity in `From:` |
| `SLACK_WEBHOOK_URL` | optional | Free, for needs-Louis pings |
| `HUNTER_API_KEY` | optional | Free tier 25 lookups/mo |
| `GROQ_API_KEY` | optional | Free tier, enables AI personalisation in cloud |
| `DEMO_SEED` | `1` for demo, `0` for prod | Default `1` in render.yaml — flip to `0` once you're sending real |

## Production readiness — what's still missing

1. **Ollama isn't on Render** → set `GROQ_API_KEY` for cloud AI, or run Ollama locally and tunnel.
2. **SQLite on Render free tier is ephemeral** → DB resets on every deploy. For real use: upgrade Render plan ($7/mo) OR migrate to Neon/Supabase Postgres (free).
3. **One Gmail inbox = ~80 emails/day safely** → to hit the brief's 18k/mo you need 15 domains × 3 inboxes.
4. **No domain warmup logic** → bulk-sending from a fresh domain = blacklisted week one. Warm 5 → 50 → 200/day over 2-4 weeks manually.
5. **No SPF/DKIM/DMARC** in the repo → set on your sending domain at the registrar.
6. **LinkedIn / cold calls / Loom are manual** → tracked in the `touches` table, not automated.
7. **No documented Legitimate Interest Assessment** for UK GDPR cold email — Louis's responsibility before sending.

## License

Private use only. Not for redistribution.
