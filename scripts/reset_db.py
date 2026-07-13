"""Wipe ALL TreatyIQ data and recreate empty tables — a clean slate.

DESTRUCTIVE: drops and recreates every table (treaties, versions, data points,
documents, the semantic index / treaty_chunks, and the audit trail). Works on
both SQLite (dev) and Postgres/Supabase (prod), so it also clears the KB index.

Usage (from the repo root):
    python -m scripts.reset_db            # asks for confirmation
    python -m scripts.reset_db --yes      # no prompt (for scripts/CI)

MLflow data (mlflow.db / mlartifacts/) is separate — delete those files
manually if you also want to reset tracking.
"""
import sys

from app.config import get_settings
from app.database import Base, get_engine


def reset(confirm: bool) -> None:
    settings = get_settings()
    target = settings.database_url
    if not confirm:
        print(f"This will DELETE ALL DATA in: {target}")
        answer = input("Type 'reset' to confirm: ").strip().lower()
        if answer != "reset":
            print("Aborted.")
            return

    from app import models  # noqa: F401 — register mappings before drop/create

    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print(f"Done. All data cleared and empty tables recreated in {target}.")


if __name__ == "__main__":
    reset(confirm="--yes" in sys.argv or "-y" in sys.argv)
