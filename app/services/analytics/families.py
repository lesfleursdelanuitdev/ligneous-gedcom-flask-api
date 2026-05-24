"""Families: unions, marriage timing and place, children, notes/sources/events links.

Aggregates over `gedcom_families_v2`, parent–child relationships, and family
junction tables (notes, sources, events).
"""

from app.db import get_connection
from app.services.analytics.utils import get_file_uuid_for_tree


def get_families_statistics(tree_id: str, country_limit: int) -> dict | None:
    """Aggregates from `gedcom_families_v2` and family junction tables."""
    file_uuid = get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)::bigint AS total,
                    COUNT(*) FILTER (
                        WHERE husband_id IS NOT NULL AND wife_id IS NOT NULL
                    )::bigint AS both_partners,
                    COUNT(*) FILTER (
                        WHERE husband_id IS NOT NULL AND wife_id IS NULL
                    )::bigint AS husband_only,
                    COUNT(*) FILTER (
                        WHERE husband_id IS NULL AND wife_id IS NOT NULL
                    )::bigint AS wife_only,
                    COUNT(*) FILTER (
                        WHERE husband_id IS NULL AND wife_id IS NULL
                    )::bigint AS no_partner_record,
                    COUNT(*) FILTER (WHERE marriage_year IS NOT NULL)::bigint AS with_marriage_year,
                    COUNT(*) FILTER (WHERE is_divorced = true)::bigint AS divorced,
                    COUNT(*) FILTER (WHERE children_count > 0)::bigint AS with_children_denorm,
                    COUNT(*) FILTER (WHERE marriage_place_id IS NOT NULL)::bigint AS with_marriage_place
                FROM gedcom_families_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            summary = dict(cur.fetchone())

            cur.execute(
                """
                SELECT
                    COALESCE(MAX(children_count), 0)::int AS max_children,
                    COALESCE(MIN(children_count), 0)::int AS min_children
                FROM gedcom_families_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            children_record_extremes = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(DISTINCT family_id)::bigint AS families_with_nonbiological_children
                FROM gedcom_parent_child_v2
                WHERE file_uuid = %s
                  AND family_id IS NOT NULL
                  AND LOWER(TRIM(relationship_type)) <> 'biological'
                """,
                (file_uuid,),
            )
            nonbio_families = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(DISTINCT fe.family_id)::bigint AS families_with_marriage_event
                FROM gedcom_family_events_v2 fe
                INNER JOIN gedcom_events_v2 e
                    ON e.id = fe.event_id AND e.file_uuid = fe.file_uuid
                WHERE fe.file_uuid = %s AND e.event_type = 'MARR'
                """,
                (file_uuid,),
            )
            marriage_event_families = dict(cur.fetchone())

            cur.execute(
                """
                SELECT (FLOOR(marriage_year::numeric / 10) * 10)::int AS decade,
                       COUNT(*)::bigint AS count
                FROM gedcom_families_v2
                WHERE file_uuid = %s AND marriage_year IS NOT NULL
                GROUP BY 1
                ORDER BY 1
                """,
                (file_uuid,),
            )
            marriage_by_decade = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    COALESCE(NULLIF(TRIM(p.country), ''), 'Unknown') AS country,
                    COUNT(*)::bigint AS count
                FROM gedcom_families_v2 f
                JOIN gedcom_places_v2 p ON p.id = f.marriage_place_id
                WHERE f.file_uuid = %s
                GROUP BY COALESCE(NULLIF(TRIM(p.country), ''), 'Unknown')
                ORDER BY count DESC
                LIMIT %s
                """,
                (file_uuid, country_limit),
            )
            marriage_country_distribution = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT COUNT(*)::bigint AS note_links
                FROM gedcom_family_notes_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            note_links = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(DISTINCT family_id)::bigint AS families_with_notes
                FROM gedcom_family_notes_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            families_with_notes = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(*)::bigint AS source_links
                FROM gedcom_family_sources_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            source_links = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(DISTINCT family_id)::bigint AS families_with_sources
                FROM gedcom_family_sources_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            families_with_sources = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(*)::bigint AS event_links
                FROM gedcom_family_events_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            event_links = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(DISTINCT family_id)::bigint AS families_with_events
                FROM gedcom_family_events_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            families_with_events = dict(cur.fetchone())
    junction_counts = {
        "note_links": note_links["note_links"],
        "families_with_notes": families_with_notes["families_with_notes"],
        "source_links": source_links["source_links"],
        "families_with_sources": families_with_sources["families_with_sources"],
        "event_links": event_links["event_links"],
        "families_with_events": families_with_events["families_with_events"],
    }

    return {
        "tree_id": tree_id,
        "summary": summary,
        "junction_counts": junction_counts,
        "children_record_extremes": children_record_extremes,
        "families_with_nonbiological_children": nonbio_families[
            "families_with_nonbiological_children"
        ],
        "families_with_marriage_event": marriage_event_families[
            "families_with_marriage_event"
        ],
        "marriage_by_decade": marriage_by_decade,
        "marriage_country_distribution": marriage_country_distribution,
    }

