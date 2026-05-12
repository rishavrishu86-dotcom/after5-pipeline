from __future__ import annotations
"""After5 pipeline — single click entry point.

Run: python -m after5.cli <command> [opts]
"""
import json
import click
from tabulate import tabulate

from . import (
    bounces, contacts, db, discover, enrich, loom, personalise,
    qualify, scheduler, send, seed, triage,
)


@click.group()
def cli():
    """After5 free-stack outbound pipeline."""


@cli.command("init-db")
def init_db():
    path = db.init()
    click.echo(f"db ready at {path}")


@cli.command("seed")
@click.argument("csv_path", type=click.Path(exists=True))
def cmd_seed(csv_path):
    inserted, skipped = seed.import_csv(csv_path)
    click.echo(f"inserted={inserted} skipped={skipped}")


@cli.command("discover")
@click.option("--country", type=click.Choice(["UK", "UAE"]), default=None,
              help="restrict to one country; default runs both")
@click.option("--source", "sources", multiple=True,
              help="source modules to use (e.g. web_search, bayt, gulftalent, indeed_uk)")
@click.option("--query", "queries", multiple=True,
              help="ICP search terms; defaults to a per-country set")
@click.option("--limit", type=int, default=15,
              help="max companies per source per query batch")
def cmd_discover(country, sources, queries, limit):
    """WF1 — find new prospects across configured sources."""
    stats = discover.run(
        country=country,
        source_names=list(sources) or None,
        queries=list(queries) or None,
        limit_per_source=limit,
    )
    click.echo(json.dumps(stats, indent=2))


@cli.command("loom-check")
@click.option("--hours", type=int, default=48,
              help="how many hours an 'interested' reply must sit before a nudge")
def cmd_loom_check(hours):
    """WF7 — Slack-nudge Louis on stale interested replies."""
    stats = loom.run(hours=hours)
    click.echo(json.dumps(stats, indent=2))


@cli.command("enrich")
@click.option("--limit", type=int, default=None, help="max companies to enrich this run")
def cmd_enrich(limit):
    n = enrich.run(limit=limit)
    click.echo(f"enriched {n} companies")


@cli.command("qualify")
def cmd_qualify():
    counts = qualify.run()
    click.echo(f"hot={counts['hot']} warm={counts['warm']} cold={counts['cold']}")


@cli.command("import-people")
@click.argument("csv_path", type=click.Path(exists=True))
def cmd_import_people(csv_path):
    """CSV: domain, first_name, last_name, role[, email]."""
    stats = contacts.import_people_csv(csv_path)
    click.echo(json.dumps(stats, indent=2))


@cli.command("find-contacts")
@click.option("--limit", type=int, default=None, help="max companies to look up via Hunter")
def cmd_find_contacts(limit):
    """Hunter domain search for qualified companies with no contacts yet."""
    stats = contacts.find_all(limit=limit)
    click.echo(json.dumps(stats, indent=2))


@cli.command("personalise")
@click.option("--limit", type=int, default=None)
def cmd_personalise(limit):
    n = personalise.run(limit=limit)
    click.echo(f"personalised {n} contacts")


@cli.command("send")
@click.option("--dry-run", is_flag=True, help="render but do not send")
@click.option("--cap", type=int, default=None, help="max sends this run")
def cmd_send(dry_run, cap):
    stats = send.run(dry_run=dry_run, cap=cap)
    click.echo(json.dumps(stats, indent=2))


@cli.command("triage")
def cmd_triage():
    stats = triage.run()
    click.echo(json.dumps(stats, indent=2))


@cli.command("bounces")
@click.option("--days", type=int, default=14, help="lookback window in days")
def cmd_bounces(days):
    """Scan IMAP for bounce notifications, suppress failed addresses."""
    stats = bounces.run(days=days)
    click.echo(json.dumps(stats, indent=2))


@cli.command("run")
def cmd_run():
    """Start the unattended daily+weekly scheduler (foreground; ctrl-c to stop)."""
    scheduler.main()


@cli.command("run-once")
@click.argument("job", type=click.Choice(["daily", "weekly"]))
def cmd_run_once(job):
    """Trigger one scheduler job immediately and exit."""
    if job == "daily":
        scheduler.daily_job()
    else:
        scheduler.weekly_job()


@cli.command("unsubscribe")
@click.argument("email")
def cmd_unsub(email):
    send.unsubscribe(email)
    click.echo(f"unsubscribed {email}")


@cli.command("stats")
def cmd_stats():
    rows = db.fetchall(
        "SELECT country, status, COUNT(*) AS n FROM companies "
        "GROUP BY country, status ORDER BY country, status"
    )
    click.echo(tabulate(rows, headers="keys"))
    pipe = db.fetchall(
        """
        SELECT priority, COUNT(DISTINCT co.id) AS companies,
               COUNT(c.id) AS contacts,
               SUM(CASE WHEN c.ready_to_send THEN 1 ELSE 0 END) AS ready_contacts,
               SUM(CASE WHEN c.email_verified THEN 1 ELSE 0 END) AS verified_contacts
        FROM companies co LEFT JOIN contacts c ON c.company_id=co.id
        WHERE co.status IN ('qualified','enriched')
        GROUP BY priority
        """
    )
    click.echo(tabulate(pipe, headers="keys"))


if __name__ == "__main__":
    cli()
