"""Run demo_seed only if the DB has no companies yet.

Used by Render's startCommand so the deployed instance always has something
to show on first boot — but won't wipe data on every restart.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from after5 import db


def main() -> None:
    import os
    db.init()
    if os.environ.get("DEMO_SEED", "").lower() not in ("1", "true", "yes"):
        print("DEMO_SEED env not set — skipping demo seed (production mode).")
        return
    count = db.fetchone("SELECT COUNT(*) AS n FROM companies")["n"]
    if count > 0:
        print(f"DB has {count} companies — skipping demo seed.")
        return
    print("Empty DB + DEMO_SEED=1 — seeding demo data...")
    from examples.demo_seed import main as seed_main
    seed_main()


if __name__ == "__main__":
    main()
