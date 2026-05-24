"""Places: canonical place rows, geographic rollups, and cross-entity reference heat.

`gedcom_places_v2` plus references from individuals, families, events, and media.
"""

from app.db import get_connection
from app.services.analytics.utils import get_file_uuid_for_tree


def get_places_statistics(
    tree_id: str, top_limit: int, country_limit: int, state_limit: int
) -> dict | None:
    """Aggregates from `gedcom_places_v2` and entity place references."""
    file_uuid = get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)::bigint AS total_places,
                    COUNT(*) FILTER (
                        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                    )::bigint AS with_coordinates,
                    COUNT(*) FILTER (
                        WHERE country IS NOT NULL AND TRIM(country) <> ''
                    )::bigint AS with_country,
                    COUNT(*) FILTER (
                        WHERE state IS NOT NULL AND TRIM(state) <> ''
                    )::bigint AS with_state,
                    COUNT(*) FILTER (
                        WHERE county IS NOT NULL AND TRIM(county) <> ''
                    )::bigint AS with_county,
                    COUNT(*) FILTER (
                        WHERE name IS NOT NULL AND TRIM(name) <> ''
                    )::bigint AS with_parsed_name
                FROM gedcom_places_v2
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
                     WHERE file_uuid = %s AND birth_place_id IS NOT NULL
                    )::bigint AS birth_place_links,
                    (SELECT COUNT(*)
                     FROM gedcom_individuals_v2
                     WHERE file_uuid = %s AND death_place_id IS NOT NULL
                    )::bigint AS death_place_links,
                    (SELECT COUNT(*)
                     FROM gedcom_families_v2
                     WHERE file_uuid = %s AND marriage_place_id IS NOT NULL
                    )::bigint AS marriage_place_links,
                    (SELECT COUNT(*)
                     FROM gedcom_families_v2
                     WHERE file_uuid = %s AND divorce_place_id IS NOT NULL
                    )::bigint AS divorce_place_links,
                    (SELECT COUNT(*)
                     FROM gedcom_events_v2
                     WHERE file_uuid = %s AND place_id IS NOT NULL
                    )::bigint AS event_place_links,
                    (SELECT COUNT(*)
                     FROM gedcom_media_places_v2
                     WHERE file_uuid = %s
                    )::bigint AS media_place_links
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
                SELECT
                    COALESCE(NULLIF(TRIM(country), ''), 'Unknown') AS country,
                    COUNT(*)::bigint AS count
                FROM gedcom_places_v2
                WHERE file_uuid = %s
                GROUP BY COALESCE(NULLIF(TRIM(country), ''), 'Unknown')
                ORDER BY count DESC
                LIMIT %s
                """,
                (file_uuid, country_limit),
            )
            country_distribution = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    COALESCE(NULLIF(TRIM(state), ''), 'Unknown') AS state,
                    COUNT(*)::bigint AS count
                FROM gedcom_places_v2
                WHERE file_uuid = %s
                GROUP BY COALESCE(NULLIF(TRIM(state), ''), 'Unknown')
                ORDER BY count DESC
                LIMIT %s
                """,
                (file_uuid, state_limit),
            )
            state_distribution = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                WITH refs AS (
                    SELECT birth_place_id AS place_id
                    FROM gedcom_individuals_v2
                    WHERE file_uuid = %s AND birth_place_id IS NOT NULL
                    UNION ALL
                    SELECT death_place_id
                    FROM gedcom_individuals_v2
                    WHERE file_uuid = %s AND death_place_id IS NOT NULL
                    UNION ALL
                    SELECT marriage_place_id
                    FROM gedcom_families_v2
                    WHERE file_uuid = %s AND marriage_place_id IS NOT NULL
                    UNION ALL
                    SELECT divorce_place_id
                    FROM gedcom_families_v2
                    WHERE file_uuid = %s AND divorce_place_id IS NOT NULL
                    UNION ALL
                    SELECT place_id
                    FROM gedcom_events_v2
                    WHERE file_uuid = %s AND place_id IS NOT NULL
                    UNION ALL
                    SELECT place_id
                    FROM gedcom_media_places_v2
                    WHERE file_uuid = %s
                )
                SELECT
                    p.id::text AS place_id,
                    COALESCE(
                        NULLIF(TRIM(p.name), ''),
                        NULLIF(TRIM(p.original), ''),
                        '(unnamed place)'
                    ) AS label,
                    COALESCE(NULLIF(TRIM(p.country), ''), '') AS country,
                    COUNT(*)::bigint AS reference_count
                FROM refs r
                JOIN gedcom_places_v2 p
                    ON p.id = r.place_id AND p.file_uuid = %s
                GROUP BY p.id, p.name, p.original, p.country
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
            top_places = [dict(row) for row in cur.fetchall()]
    return {
        "tree_id": tree_id,
        "summary": summary,
        "reference_counts": reference_counts,
        "country_distribution": country_distribution,
        "state_distribution": state_distribution,
        "top_places": top_places,
    }

