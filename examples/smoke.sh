#!/usr/bin/env bash
# End-to-end smoke test — exercises every stage that doesn't need live Gmail/Ollama.
# Sends NO real email (uses --dry-run). Hits live websites for enrichment scoring.
set -e
cd "$(dirname "$0")/.."

PY=.venv/bin/python

# Fresh DB each run so the smoke is repeatable
rm -f data/after5.db

echo "== init-db =="
$PY -m after5.cli init-db

echo
echo "== seed =="
$PY -m after5.cli seed examples/sample_companies.csv

echo
echo "== enrich (live HTTP to each domain) =="
$PY -m after5.cli enrich --limit 10

echo
echo "== qualify =="
$PY -m after5.cli qualify

echo
echo "== import-people =="
$PY -m after5.cli import-people examples/sample_people.csv

echo
echo "== fake personalise (no Ollama: stub a first line per contact) =="
.venv/bin/python - <<'PY'
from after5 import db
with db.conn() as c:
    c.execute("""
        UPDATE contacts
        SET ai_first_line = 'Noticed your recent growth in ' ||
                            (SELECT country FROM companies WHERE id=contacts.company_id) ||
                            ' and thought this might be timely.',
            signal_used = 'tech',
            ready_to_send = 1,
            next_send_day = 1
        WHERE ai_first_line IS NULL
    """)
PY
echo "stub first-lines applied"

echo
echo "== send --dry-run =="
$PY -m after5.cli send --dry-run --cap 5

echo
echo "== stats =="
$PY -m after5.cli stats
