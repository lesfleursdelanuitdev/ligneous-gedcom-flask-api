"""Lineages: surname-based descent groups computed from pedigree founders.

Aggregates over the `lineages` and `individual_lineages` tables.
"""

from app.db import get_connection
from app.services.analytics.utils import get_file_uuid_for_tree


def get_lineages_statistics(tree_id: str, top_n: int = 20) -> dict | None:
    """Aggregates from the lineages and individual_lineages tables."""
    file_uuid = get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return None

    with get_connection() as conn:
        with conn.cursor() as cur:

            # ── Summary ────────────────────────────────────────────────────────
            cur.execute(
                """
                SELECT
                    COUNT(*)::bigint                          AS total_lineages,
                    COALESCE(SUM(size), 0)::bigint           AS total_members,
                    COALESCE(AVG(size), 0)::float            AS avg_size,
                    COALESCE(MAX(size), 0)::int              AS largest_lineage_size,
                    COALESCE(MIN(size), 0)::int              AS smallest_lineage_size,
                    COALESCE(MIN(earliest_year), 0)::int     AS earliest_year,
                    COALESCE(MAX(latest_year), 0)::int       AS latest_year,
                    COUNT(*) FILTER (WHERE size = 1)::bigint AS singleton_lineages,
                    COUNT(*) FILTER (WHERE size >= 10)::bigint AS large_lineages
                FROM lineages
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            summary = dict(cur.fetchone())
            summary["avg_size"] = round(summary["avg_size"], 1)

            # ── Top lineages by size ───────────────────────────────────────────
            cur.execute(
                """
                SELECT
                    name,
                    surname,
                    size,
                    earliest_year,
                    latest_year,
                    top_surnames
                FROM lineages
                WHERE file_uuid = %s
                ORDER BY size DESC
                LIMIT %s
                """,
                (file_uuid, top_n),
            )
            top_lineages = [dict(r) for r in cur.fetchall()]

            # ── Size distribution buckets ──────────────────────────────────────
            cur.execute(
                """
                SELECT bucket, COUNT(*)::bigint AS count FROM (
                    SELECT
                        CASE
                            WHEN size = 1   THEN '1'
                            WHEN size <= 5  THEN '2–5'
                            WHEN size <= 10 THEN '6–10'
                            WHEN size <= 25 THEN '11–25'
                            WHEN size <= 50 THEN '26–50'
                            WHEN size <= 100 THEN '51–100'
                            ELSE '100+'
                        END AS bucket
                    FROM lineages
                    WHERE file_uuid = %s
                ) x
                GROUP BY bucket
                ORDER BY MIN(CASE bucket
                    WHEN '1'     THEN 1
                    WHEN '2–5'   THEN 2
                    WHEN '6–10'  THEN 3
                    WHEN '11–25' THEN 4
                    WHEN '26–50' THEN 5
                    WHEN '51–100' THEN 6
                    ELSE 7 END)
                """,
                (file_uuid,),
            )
            size_distribution = [dict(r) for r in cur.fetchall()]

            # ── Span in years distribution ─────────────────────────────────────
            cur.execute(
                """
                SELECT
                    name,
                    surname,
                    size,
                    earliest_year,
                    latest_year,
                    (latest_year - earliest_year) AS span_years
                FROM lineages
                WHERE file_uuid = %s
                  AND earliest_year IS NOT NULL
                  AND latest_year IS NOT NULL
                ORDER BY span_years DESC
                LIMIT %s
                """,
                (file_uuid, top_n),
            )
            longest_spans = [dict(r) for r in cur.fetchall()]

            # ── Earliest-founding lineages ─────────────────────────────────────
            cur.execute(
                """
                SELECT name, surname, size, earliest_year, latest_year
                FROM lineages
                WHERE file_uuid = %s
                  AND earliest_year IS NOT NULL
                ORDER BY earliest_year ASC
                LIMIT %s
                """,
                (file_uuid, top_n),
            )
            earliest_lineages = [dict(r) for r in cur.fetchall()]

    return {
        "tree_id": tree_id,
        "summary": summary,
        "top_lineages": top_lineages,
        "size_distribution": size_distribution,
        "longest_spans": longest_spans,
        "earliest_lineages": earliest_lineages,
    }
