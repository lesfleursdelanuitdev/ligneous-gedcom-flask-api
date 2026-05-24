"""Events: GEDCOM event instances, catalog vs custom types, time and place summaries.

Uses `gedcom_events_v2` with `event_types` / `gedcom_event_event_types` for labels
and junction counts (individuals, families, notes, sources, media).
"""

from app.db import get_connection
from app.services.analytics.utils import friendly_event_label, get_file_uuid_for_tree


def get_events_statistics(
    tree_id: str, type_limit: int, country_limit: int
) -> dict | None:
    """Aggregates from `gedcom_events_v2` and event type / junction tables."""
    file_uuid = get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)::bigint AS total,
                    COUNT(*) FILTER (WHERE date_id IS NOT NULL)::bigint AS with_date,
                    COUNT(*) FILTER (WHERE place_id IS NOT NULL)::bigint AS with_place,
                    COUNT(*) FILTER (
                        WHERE custom_type IS NOT NULL AND TRIM(custom_type) <> ''
                    )::bigint AS with_custom_type
                FROM gedcom_events_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            summary = dict(cur.fetchone())

            cur.execute(
                """
                WITH ev_class AS (
                    SELECT
                        e.id,
                        COALESCE(et.tag, e.event_type) AS type_tag,
                        COALESCE(et.is_custom, false) AS is_custom,
                        (jet.event_id IS NULL) AS unlinked
                    FROM gedcom_events_v2 e
                    LEFT JOIN gedcom_event_event_types jet ON jet.event_id = e.id
                    LEFT JOIN event_types et
                        ON et.id = jet.event_type_id AND et.file_uuid IS NULL
                    WHERE e.file_uuid = %s
                )
                SELECT
                    COUNT(*) FILTER (
                        WHERE NOT is_custom AND NOT unlinked
                    )::bigint AS standard_catalog_events,
                    COUNT(*) FILTER (WHERE is_custom)::bigint AS custom_catalog_events,
                    COUNT(*) FILTER (WHERE unlinked)::bigint AS unlinked_to_catalog,
                    COUNT(DISTINCT type_tag) FILTER (
                        WHERE NOT is_custom AND NOT unlinked
                    )::bigint AS distinct_standard_types,
                    COUNT(DISTINCT type_tag) FILTER (WHERE is_custom)::bigint
                        AS distinct_custom_types
                FROM ev_class
                """,
                (file_uuid,),
            )
            origin_row = dict(cur.fetchone())
            origin_breakdown = {
                "standard_catalog_events": origin_row["standard_catalog_events"],
                "custom_catalog_events": origin_row["custom_catalog_events"],
                "unlinked_to_catalog": origin_row["unlinked_to_catalog"],
            }
            type_catalog_breakdown = {
                "distinct_standard_types": origin_row["distinct_standard_types"],
                "distinct_custom_types": origin_row["distinct_custom_types"],
            }

            cur.execute(
                """
                SELECT
                    COALESCE(et.tag, e.event_type) AS tag,
                    COALESCE(et.label, e.event_type) AS catalog_label,
                    COALESCE(et.is_custom, false) AS is_custom,
                    COUNT(*)::bigint AS count
                FROM gedcom_events_v2 e
                LEFT JOIN gedcom_event_event_types jet ON jet.event_id = e.id
                LEFT JOIN event_types et
                    ON et.id = jet.event_type_id AND et.file_uuid IS NULL
                WHERE e.file_uuid = %s
                GROUP BY
                    COALESCE(et.tag, e.event_type),
                    COALESCE(et.label, e.event_type),
                    COALESCE(et.is_custom, false)
                ORDER BY count DESC
                LIMIT %s
                """,
                (file_uuid, type_limit),
            )
            by_event_type = []
            for row in cur.fetchall():
                r = dict(row)
                r["label"] = friendly_event_label(r.get("tag"), r.get("catalog_label"))
                del r["catalog_label"]
                by_event_type.append(r)

            cur.execute(
                """
                SELECT (FLOOR(d.year::numeric / 10) * 10)::int AS decade,
                       COUNT(*)::bigint AS count
                FROM gedcom_events_v2 e
                INNER JOIN gedcom_dates_v2 d
                    ON d.id = e.date_id AND d.file_uuid = e.file_uuid
                WHERE e.file_uuid = %s AND d.year IS NOT NULL
                GROUP BY 1
                ORDER BY 1
                """,
                (file_uuid,),
            )
            year_by_decade = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    COALESCE(NULLIF(TRIM(p.country), ''), 'Unknown') AS country,
                    COUNT(*)::bigint AS count
                FROM gedcom_events_v2 e
                INNER JOIN gedcom_places_v2 p
                    ON p.id = e.place_id AND p.file_uuid = e.file_uuid
                WHERE e.file_uuid = %s
                GROUP BY COALESCE(NULLIF(TRIM(p.country), ''), 'Unknown')
                ORDER BY count DESC
                LIMIT %s
                """,
                (file_uuid, country_limit),
            )
            place_country_distribution = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT COUNT(*)::bigint AS links_to_individuals
                FROM gedcom_individual_events_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            ind_evt = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(*)::bigint AS links_to_families
                FROM gedcom_family_events_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            fam_evt = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(DISTINCT event_id)::bigint AS events_with_notes
                FROM gedcom_event_notes_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            ev_notes = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(*)::bigint AS note_links
                FROM gedcom_event_notes_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            note_links = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(DISTINCT event_id)::bigint AS events_with_sources
                FROM gedcom_event_sources_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            ev_src = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(*)::bigint AS source_links
                FROM gedcom_event_sources_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            source_links = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(*)::bigint AS media_links
                FROM gedcom_event_media_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            media_links = dict(cur.fetchone())
    junction_counts = {
        "links_to_individuals": ind_evt["links_to_individuals"],
        "links_to_families": fam_evt["links_to_families"],
        "events_with_notes": ev_notes["events_with_notes"],
        "note_links": note_links["note_links"],
        "events_with_sources": ev_src["events_with_sources"],
        "source_links": source_links["source_links"],
        "media_links": media_links["media_links"],
    }

    return {
        "tree_id": tree_id,
        "summary": summary,
        "junction_counts": junction_counts,
        "origin_breakdown": origin_breakdown,
        "type_catalog_breakdown": type_catalog_breakdown,
        "by_event_type": by_event_type,
        "year_by_decade": year_by_decade,
        "place_country_distribution": place_country_distribution,
    }

