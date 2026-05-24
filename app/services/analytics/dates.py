"""Dates: parsed date components, qualifiers, calendars, decade histograms, top dates.

`gedcom_dates_v2` and how individuals, families, events, and media reference them.
"""

from app.db import get_connection
from app.services.analytics.utils import get_file_uuid_for_tree


def get_dates_statistics(
    tree_id: str, top_limit: int, calendar_limit: int
) -> dict | None:
    """Aggregates from `gedcom_dates_v2` and entity date references."""
    file_uuid = get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)::bigint AS total_dates,
                    COUNT(*) FILTER (WHERE year IS NOT NULL)::bigint AS with_year,
                    COUNT(*) FILTER (WHERE month IS NOT NULL)::bigint AS with_month,
                    COUNT(*) FILTER (WHERE day IS NOT NULL)::bigint AS with_day,
                    COUNT(*) FILTER (
                        WHERE original IS NOT NULL AND TRIM(original) <> ''
                    )::bigint AS with_original_text,
                    COUNT(*) FILTER (
                        WHERE end_year IS NOT NULL
                            OR end_month IS NOT NULL
                            OR end_day IS NOT NULL
                    )::bigint AS with_end_components,
                    COUNT(*) FILTER (
                        WHERE date_type::text IN ('BETWEEN', 'FROM_TO')
                    )::bigint AS range_style_records
                FROM gedcom_dates_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            summary = dict(cur.fetchone())

            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*)
                     FROM gedcom_individuals_v2
                     WHERE file_uuid = %s AND birth_date_id IS NOT NULL
                    )::bigint AS birth_date_links,
                    (SELECT COUNT(*)
                     FROM gedcom_individuals_v2
                     WHERE file_uuid = %s AND death_date_id IS NOT NULL
                    )::bigint AS death_date_links,
                    (SELECT COUNT(*)
                     FROM gedcom_families_v2
                     WHERE file_uuid = %s AND marriage_date_id IS NOT NULL
                    )::bigint AS marriage_date_links,
                    (SELECT COUNT(*)
                     FROM gedcom_families_v2
                     WHERE file_uuid = %s AND divorce_date_id IS NOT NULL
                    )::bigint AS divorce_date_links,
                    (SELECT COUNT(*)
                     FROM gedcom_events_v2
                     WHERE file_uuid = %s AND date_id IS NOT NULL
                    )::bigint AS event_date_links,
                    (SELECT COUNT(*)
                     FROM gedcom_media_dates_v2
                     WHERE file_uuid = %s
                    )::bigint AS media_date_links
                """,
                (
                    file_uuid,
                    file_uuid,
                    file_uuid,
                    file_uuid,
                    file_uuid,
                    file_uuid,
                ),
            )
            reference_counts = dict(cur.fetchone())

            cur.execute(
                """
                SELECT date_type::text AS date_type, COUNT(*)::bigint AS count
                FROM gedcom_dates_v2
                WHERE file_uuid = %s
                GROUP BY date_type
                ORDER BY count DESC
                """,
                (file_uuid,),
            )
            by_date_type = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    COALESCE(NULLIF(UPPER(TRIM(calendar)), ''), 'UNKNOWN') AS calendar,
                    COUNT(*)::bigint AS count
                FROM gedcom_dates_v2
                WHERE file_uuid = %s
                GROUP BY COALESCE(NULLIF(UPPER(TRIM(calendar)), ''), 'UNKNOWN')
                ORDER BY count DESC
                LIMIT %s
                """,
                (file_uuid, calendar_limit),
            )
            calendar_distribution = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT (FLOOR(year::numeric / 10) * 10)::int AS decade,
                       COUNT(*)::bigint AS count
                FROM gedcom_dates_v2
                WHERE file_uuid = %s AND year IS NOT NULL
                GROUP BY 1
                ORDER BY 1
                """,
                (file_uuid,),
            )
            year_by_decade = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                WITH refs AS (
                    SELECT birth_date_id AS date_id
                    FROM gedcom_individuals_v2
                    WHERE file_uuid = %s AND birth_date_id IS NOT NULL
                    UNION ALL
                    SELECT death_date_id
                    FROM gedcom_individuals_v2
                    WHERE file_uuid = %s AND death_date_id IS NOT NULL
                    UNION ALL
                    SELECT marriage_date_id
                    FROM gedcom_families_v2
                    WHERE file_uuid = %s AND marriage_date_id IS NOT NULL
                    UNION ALL
                    SELECT divorce_date_id
                    FROM gedcom_families_v2
                    WHERE file_uuid = %s AND divorce_date_id IS NOT NULL
                    UNION ALL
                    SELECT date_id
                    FROM gedcom_events_v2
                    WHERE file_uuid = %s AND date_id IS NOT NULL
                    UNION ALL
                    SELECT date_id
                    FROM gedcom_media_dates_v2
                    WHERE file_uuid = %s
                )
                SELECT
                    d.id::text AS date_id,
                    COALESCE(
                        NULLIF(TRIM(d.original), ''),
                        CASE
                            WHEN d.year IS NOT NULL THEN
                                d.year::text
                                || CASE
                                    WHEN d.month IS NOT NULL
                                    THEN '-' || LPAD(d.month::text, 2, '0')
                                    ELSE ''
                                END
                                || CASE
                                    WHEN d.day IS NOT NULL
                                    THEN '-' || LPAD(d.day::text, 2, '0')
                                    ELSE ''
                                END
                            ELSE '(no parsed year)'
                        END
                    ) AS label,
                    d.date_type::text AS date_type,
                    COUNT(*)::bigint AS reference_count
                FROM refs r
                JOIN gedcom_dates_v2 d
                    ON d.id = r.date_id AND d.file_uuid = %s
                GROUP BY d.id, d.original, d.year, d.month, d.day, d.date_type
                ORDER BY reference_count DESC
                LIMIT %s
                """,
                (
                    file_uuid,
                    file_uuid,
                    file_uuid,
                    file_uuid,
                    file_uuid,
                    file_uuid,
                    file_uuid,
                    top_limit,
                ),
            )
            top_dates = [dict(row) for row in cur.fetchall()]
    return {
        "tree_id": tree_id,
        "summary": summary,
        "reference_counts": reference_counts,
        "by_date_type": by_date_type,
        "calendar_distribution": calendar_distribution,
        "year_by_decade": year_by_decade,
        "top_dates": top_dates,
    }

