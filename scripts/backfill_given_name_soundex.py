"""Backfill soundex + metaphone for gedcom_given_names_v2.

Requires jellyfish >= 1.0.0 and DATABASE_URL in the environment (or .env file).

Usage:
    python scripts/backfill_given_name_soundex.py [--dry-run] [--batch-size N]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

import jellyfish
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

BATCH_SIZE_DEFAULT = 500


def compute_soundex(name: str) -> str | None:
    try:
        return jellyfish.soundex(name) or None
    except Exception:
        return None


def compute_metaphone(name: str) -> str | None:
    try:
        return jellyfish.metaphone(name) or None
    except Exception:
        return None


def backfill(dry_run: bool, batch_size: int) -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        log.error("DATABASE_URL is not set")
        sys.exit(1)

    conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM gedcom_given_names_v2 WHERE soundex IS NULL"
            )
            total = cur.fetchone()["n"]
        log.info("Rows to backfill: %d", total)
        if total == 0:
            log.info("Nothing to do.")
            return

        updated = 0
        offset = 0
        while True:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, given_name
                    FROM gedcom_given_names_v2
                    WHERE soundex IS NULL
                    ORDER BY id
                    LIMIT %s OFFSET %s
                    """,
                    (batch_size, offset),
                )
                rows = cur.fetchall()
            if not rows:
                break

            updates = [
                (compute_soundex(r["given_name"]), compute_metaphone(r["given_name"]), r["id"])
                for r in rows
            ]

            if not dry_run:
                with conn.cursor() as cur:
                    psycopg2.extras.execute_batch(
                        cur,
                        "UPDATE gedcom_given_names_v2 SET soundex = %s, metaphone = %s WHERE id = %s",
                        updates,
                        page_size=batch_size,
                    )
                conn.commit()

            updated += len(rows)
            log.info(
                "%s %d / %d rows",
                "[dry-run]" if dry_run else "Updated",
                updated,
                total,
            )
            offset += batch_size

        log.info("Done. %d rows %s.", updated, "would be updated" if dry_run else "updated")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill soundex/metaphone for given names")
    parser.add_argument("--dry-run", action="store_true", help="Read-only — log without writing")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE_DEFAULT)
    args = parser.parse_args()
    backfill(dry_run=args.dry_run, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
