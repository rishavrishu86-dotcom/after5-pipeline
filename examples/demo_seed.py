"""Populate the DB with realistic-looking demo data so the dashboard has content.

This is NOT real prospect data — it's plausible-shaped data for visually
checking the UI. UK only (UAE removed per current scope). Wipes existing DB.
"""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from after5 import db

random.seed(7)

UK_COS = [
    ("monzo.com", "Monzo", "fintech"),
    ("deliveroo.co.uk", "Deliveroo", "marketplace"),
    ("gymshark.com", "Gymshark", "d2c"),
    ("revolut.com", "Revolut", "fintech"),
    ("brewdog.com", "BrewDog", "d2c"),
    ("ovo.com", "Ovo Energy", "utility"),
    ("octopus.energy", "Octopus Energy", "utility"),
    ("starlingbank.com", "Starling Bank", "fintech"),
    ("trainline.com", "Trainline", "travel"),
    ("just-eat.co.uk", "Just Eat", "marketplace"),
    ("asos.com", "ASOS", "d2c"),
    ("notonthehighstreet.com", "Not On The High Street", "marketplace"),
    ("zoopla.co.uk", "Zoopla", "proptech"),
    ("checkatrade.com", "Checkatrade", "marketplace"),
    ("simplybusiness.co.uk", "Simply Business", "insurtech"),
    ("vinted.co.uk", "Vinted UK", "marketplace"),
    ("cazoo.co.uk", "Cazoo", "marketplace"),
    ("wise.com", "Wise", "fintech"),
    ("nutmeg.com", "Nutmeg", "fintech"),
    ("ocado.com", "Ocado", "marketplace"),
    ("naked-wines.com", "Naked Wines", "d2c"),
    ("graze.com", "Graze", "d2c"),
    ("hellofresh.co.uk", "HelloFresh UK", "foodtech"),
    ("treatwell.co.uk", "Treatwell", "marketplace"),
    ("rentalcars.com", "Rentalcars.com", "travel"),
    ("blackcircles.com", "Black Circles", "ecom"),
    ("smol.co.uk", "Smol", "d2c"),
    ("snag.co.uk", "Snag Tights", "d2c"),
    ("appearhere.co.uk", "Appear Here", "proptech"),
    ("propertypartner.co", "Property Partner", "proptech"),
]

FIRST_NAMES = ["Jordan", "Priya", "Tom", "Anna", "Sam", "Olivia", "Liam", "Sophie",
               "Adam", "Hannah", "Ben", "Maya", "Connor", "Ella", "Dylan",
               "Holly", "James", "Emily", "Oliver", "Charlotte"]
LAST_NAMES = ["Smith", "Patel", "Wright", "Kowalski", "Jones", "Wilson", "Taylor",
              "Edwards", "Wood", "Brown", "Khan", "Cooper", "Foster",
              "Hughes", "Mitchell", "Bennett", "Price"]
ROLES = ["Head of Growth", "VP Sales", "Marketing Director", "CMO", "Growth Lead",
         "Director of Customer Success", "Head of Digital", "Sales Director",
         "Commercial Lead", "Head of B2B", "Operations Director"]

SIGNAL_TYPES = ["ads", "hiring", "reviews", "tech"]


def _signals(scores: dict) -> str:
    evidence = {
        "tech": {"score": scores["tech"], "type": "tech",
                 "evidence": {"detected": random.choice([["Shopify"], ["WordPress","Intercom"], ["HubSpot"], []])}},
        "ads": {"score": scores["ads"], "type": "ads",
                "evidence": {"meta_active": random.randint(0, 18), "google_transparency": True}},
        "hiring": {"score": scores["hiring"], "type": "hiring",
                   "evidence": {"page": "/careers",
                                "roles": random.sample(["sdr", "bdr", "customer success", "account executive"],
                                                       k=random.randint(0, 3))}},
        "reviews": {"score": scores["reviews"], "type": "reviews",
                    "evidence": {"count": random.randint(50, 5000),
                                 "rating": round(random.uniform(2.8, 4.9), 1)}},
    }
    return json.dumps(evidence)


def _priority(total: int) -> str:
    if total >= 18: return "hot"
    if total >= 10: return "warm"
    return "cold"


def main():
    Path("data").mkdir(exist_ok=True)
    db_path = Path("data/after5.db")
    if db_path.exists():
        db_path.unlink()
    db.init()

    now = datetime.utcnow()
    with db.conn() as c:
        for domain, name, icp in UK_COS:
            # status mix: ~10% new, ~15% enriched, ~55% qualified, ~20% rejected
            roll = random.random()
            if roll < 0.10:
                status, scores = "new", {"tech": 0, "ads": 0, "hiring": 0, "reviews": 0}
            elif roll < 0.25:
                status = "enriched"
                scores = {k: random.randint(0, 5) for k in SIGNAL_TYPES}
            elif roll < 0.80:
                status = "qualified"
                scores = {
                    "tech": random.randint(2, 8),
                    "ads": random.randint(3, 9),
                    "hiring": random.randint(2, 8),
                    "reviews": random.randint(2, 7),
                }
            else:
                status = "rejected"
                scores = {k: random.randint(0, 3) for k in SIGNAL_TYPES}
            total = sum(scores.values())
            prio = _priority(total) if status in ("qualified", "rejected") else None
            c.execute(
                """
                INSERT INTO companies (domain, name, country, icp, source, status,
                    tech_score, ads_score, hiring_score, reviews_score,
                    total_score, priority, signals,
                    created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    domain, name, "UK", icp, "demo", status,
                    scores["tech"], scores["ads"], scores["hiring"], scores["reviews"],
                    total, prio, _signals(scores) if status != "new" else None,
                    (now - timedelta(days=random.randint(2, 30))).isoformat(),
                    (now - timedelta(hours=random.randint(1, 72))).isoformat(),
                ),
            )

        contact_ids: list[int] = []
        for cid, domain in c.execute(
            "SELECT id, domain FROM companies WHERE status='qualified'"
        ).fetchall():
            for _ in range(random.randint(1, 3)):
                f, l = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
                role = random.choice(ROLES)
                email = f"{f.lower()}.{l.lower()}@{domain}"
                state = random.random()
                if state < 0.50:
                    ready, unsub, verified, last_sent, current_day, next_day = 1, 0, random.choice([0,1]), None, 0, 1
                elif state < 0.80:
                    last_sent = (now - timedelta(days=random.randint(0, 4))).isoformat()
                    current_day = random.choice([1, 3])
                    next_day = 3 if current_day == 1 else 7
                    ready, unsub, verified = 1, 0, random.choice([0,1])
                elif state < 0.90:
                    ready, unsub, verified = 0, 1, 0
                    last_sent = (now - timedelta(days=random.randint(1, 10))).isoformat()
                    current_day, next_day = 1, None
                else:
                    ready, unsub, verified, last_sent, current_day, next_day = 0, 0, 0, None, 0, None
                signal_type = random.choice(SIGNAL_TYPES)
                first_line = random.choice([
                    f"Saw you're hiring SDRs at {domain} — usually a sign the team's stretched.",
                    f"Noticed {domain} is running ads across Meta and Google — clearly investing in growth.",
                    f"Spotted your Trustpilot reviews trending up — you're handling real volume.",
                    f"Your stack ({signal_type}) suggests an AI agent could plug in fast.",
                ])
                cur = c.execute(
                    """
                    INSERT INTO contacts (company_id, first_name, last_name, email,
                        email_verified, role, ai_first_line, signal_used,
                        ready_to_send, unsubscribed, current_sequence_day,
                        last_sent_at, next_send_day, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (cid, f, l, email, verified, role, first_line, signal_type,
                     ready, unsub, current_day, last_sent, next_day,
                     (now - timedelta(days=random.randint(1, 20))).isoformat()),
                )
                contact_ids.append(cur.lastrowid)

        for cid, day in c.execute(
            "SELECT id, current_sequence_day FROM contacts WHERE last_sent_at IS NOT NULL"
        ).fetchall():
            for d in [1, 3, 7]:
                if d > (day or 0):
                    break
                c.execute(
                    """
                    INSERT INTO sends (contact_id, sequence_day, subject, body, sent_at, message_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (cid, d,
                     f"Quick idea for your team — day {d}",
                     "Hi there,\n\n[rendered template body]\n\nLouis",
                     (now - timedelta(days=random.randint(0, 6),
                                      hours=random.randint(0, 23))).isoformat(),
                     f"<demo-{cid}-{d}@after5.demo>"),
                )

        random.shuffle(contact_ids)
        sample_replies = [
            ("interested", "Hi Louis, yes this is interesting — can you send a Loom?", 1),
            ("interested", "We're actually evaluating exactly this. Got 20 min next week?", 1),
            ("not_interested", "Thanks but we're sorted for now.", 0),
            ("not_interested", "Please remove from your list.", 0),
            ("ooo", "I'm out of office until Monday, will revert then.", 0),
            ("unsubscribe", "Unsubscribe.", 0),
            ("other", "Who is this addressed to?", 0),
            ("interested", "Sounds promising — what's the pricing model?", 1),
        ]
        for cid, (cls, body, needs_louis) in zip(contact_ids, sample_replies):
            responded = 1 if (needs_louis and random.random() < 0.4) else 0
            c.execute(
                """
                INSERT INTO replies (contact_id, raw_body, classification, sentiment,
                    needs_louis, louis_responded, received_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (cid, body, cls, cls, needs_louis, responded,
                 (now - timedelta(days=random.randint(0, 4),
                                  hours=random.randint(0, 23))).isoformat()),
            )

        c.execute(
            "INSERT OR IGNORE INTO suppression (email, domain, reason) "
            "VALUES (?, ?, 'hard-bounce')",
            ("nonexistent@deliveroo.co.uk", "deliveroo.co.uk")
        )

    counts = {
        "companies": db.fetchone("SELECT COUNT(*) AS n FROM companies")["n"],
        "qualified": db.fetchone("SELECT COUNT(*) AS n FROM companies WHERE status='qualified'")["n"],
        "contacts":  db.fetchone("SELECT COUNT(*) AS n FROM contacts")["n"],
        "ready":     db.fetchone("SELECT COUNT(*) AS n FROM contacts WHERE ready_to_send=1 AND unsubscribed=0")["n"],
        "sends":     db.fetchone("SELECT COUNT(*) AS n FROM sends")["n"],
        "replies":   db.fetchone("SELECT COUNT(*) AS n FROM replies")["n"],
        "needs_louis": db.fetchone("SELECT COUNT(*) AS n FROM replies WHERE needs_louis=1 AND louis_responded=0")["n"],
    }
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
