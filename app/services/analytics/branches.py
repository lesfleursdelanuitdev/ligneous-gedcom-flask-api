"""Branches: disconnected components of the family graph.

Aggregates over the `gedcom_branches` table. A branch is a group of people
connected to each other through parent-child or marriage relationships, with
no link to anyone outside the group.
"""

from app.db import get_connection
from app.services.analytics.utils import get_file_uuid_for_tree


def get_branches_statistics(tree_id: str) -> dict | None:
    """Aggregates from the gedcom_branches table."""
    file_uuid = get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return None

    with get_connection() as conn:
        with conn.cursor() as cur:

            # ── Summary ────────────────────────────────────────────────────────
            cur.execute(
                """
                SELECT
                    COUNT(*)::bigint                              AS total_branches,
                    COALESCE(SUM(size), 0)::bigint               AS total_individuals,
                    COALESCE(MAX(size) FILTER (WHERE is_main), 0)::int AS main_branch_size,
                    COUNT(*) FILTER (WHERE NOT is_main)::bigint  AS isolated_branches,
                    COALESCE(SUM(size) FILTER (WHERE NOT is_main), 0)::bigint AS isolated_total,
                    COALESCE(MIN(earliest_year), 0)::int         AS earliest_year,
                    COALESCE(MAX(latest_year), 0)::int           AS latest_year
                FROM gedcom_branches
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            summary = dict(cur.fetchone())

            # ── All branches (ordered by size) ─────────────────────────────────
            cur.execute(
                """
                SELECT
                    name,
                    size,
                    is_main,
                    earliest_year,
                    latest_year,
                    top_surnames
                FROM gedcom_branches
                WHERE file_uuid = %s
                ORDER BY size DESC
                """,
                (file_uuid,),
            )
            all_branches = [dict(r) for r in cur.fetchall()]

            # ── Main branch coverage ───────────────────────────────────────────
            main = next((b for b in all_branches if b["is_main"]), None)
            main_pct = None
            if main and summary["total_individuals"]:
                main_pct = round(100 * main["size"] / summary["total_individuals"], 1)

    return {
        "tree_id": tree_id,
        "summary": summary,
        "all_branches": all_branches,
        "main_branch_coverage_pct": main_pct,
    }
