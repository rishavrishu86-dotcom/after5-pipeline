from __future__ import annotations
"""WF1 — source-discovery orchestrator.

Loops through enabled `sources/*` modules, dedupes by domain (within run +
against existing companies), and inserts new rows with status='new'.
"""
from . import db, sources

DEFAULT_QUERIES = {
    "UK":  ["estate agent", "mortgage broker", "car dealership",
            "solar installer", "car finance", "recruitment agency",
            "boutique gym"],
}

DEFAULT_SOURCES = {
    # All three campaigns fire by default — each source self-tags its campaign.
    "UK":  ["web_search", "hiring_signal", "clutch_agency"],
}


def _existing_domains() -> set[str]:
    return {r["domain"] for r in db.fetchall("SELECT domain FROM companies")}


def run(country: str | None = None,
        source_names: list[str] | None = None,
        queries: list[str] | None = None,
        limit_per_source: int = 15) -> dict:
    countries = [country] if country else ["UK"]
    existing = _existing_domains()
    per_source: dict[str, int] = {}
    inserted_total = 0
    skipped_dupe = 0

    for c in countries:
        srcs = source_names or DEFAULT_SOURCES[c]
        qs = queries or DEFAULT_QUERIES[c]
        for src_name in srcs:
            mod = sources.ALL.get(src_name)
            if not mod:
                continue
            try:
                results = mod.discover(c, qs, limit=limit_per_source)
            except Exception as e:
                per_source[f"{c}/{src_name}/error"] = str(e)[:80]
                continue
            for r in results:
                d = (r.get("domain") or "").strip().lower()
                if not d or r.get("_unresolved"):
                    continue
                if d in existing:
                    skipped_dupe += 1
                    continue
                try:
                    with db.conn() as conn:
                        cur = conn.execute(
                            """
                            INSERT OR IGNORE INTO companies
                            (domain, name, country, icp, source, campaign, status)
                            VALUES (?, ?, ?, ?, ?, ?, 'new')
                            """,
                            (d, r.get("name"), r["country"], r.get("icp"),
                             r.get("source"), r.get("campaign", "icp_outreach")),
                        )
                        if cur.rowcount:
                            inserted_total += 1
                            existing.add(d)
                            per_source[f"{c}/{src_name}"] = (
                                per_source.get(f"{c}/{src_name}", 0) + 1
                            )
                except Exception:
                    continue
    return {
        "inserted": inserted_total,
        "skipped_dupe": skipped_dupe,
        "per_source": per_source,
    }
