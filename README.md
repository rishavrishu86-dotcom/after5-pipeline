# after5 pipeline

Free-stack rebuild of After5 Digital's UK GTM automation — discover, qualify, enrich, personalise, send, triage, follow-up.

## Quick start (local)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit APP_PASSWORD + SMTP creds
python -m after5.cli init-db
python examples/demo_seed.py     # optional — fills the UI for demoing
python -m after5.webapp.app      # http://127.0.0.1:8001
```

## Pipeline (8 workflows)

| Stage | CLI | What it does |
|---|---|---|
| 1. Discover | `discover` | Find new UK companies via DuckDuckGo + (best-effort) Indeed |
| 2. Enrich | `enrich` | Score each on tech / ads / hiring / reviews signals |
| 3. Qualify | `qualify` | Bucket into hot / warm / cold; reject the rest |
| 4. Find contacts | `find-contacts` | Hunter free tier or pattern guess + MX check |
| 5. Personalise | `personalise` | Local Ollama writes a signal-aware first line |
| 6. Send | `send [--dry-run]` | Gmail SMTP, day-1/3/7 sequencer, suppression |
| 7. Triage | `triage` | IMAP read, Ollama classifier, Slack flag on interested |
| 8. Loom reminder | `loom-check` | Slack-nudge if interested replies sit >48h with no Loom |

## Stack

Python + SQLite + Flask + Gmail SMTP/IMAP + local Ollama (`llama3.1:8b`). No paid SaaS; ~£15–50/year for a sending domain.

## Deploy

`render.yaml` is included. Push to GitHub → connect repo in Render → set `APP_PASSWORD` in the dashboard.

## License

Private — not for redistribution.
