"""Notes: GEDCOM NOTE records, orphan detection, link volumes, top entities.

`gedcom_notes_v2` and junctions to individuals, families, events, and sources.
"""

from app.db import get_connection
from app.services.analytics.utils import get_file_uuid_for_tree


def get_notes_statistics(tree_id: str, top_n: int) -> dict | None:
    """Aggregates from `gedcom_notes_v2` and note junction tables."""
    file_uuid = get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)::bigint AS total_notes,
                    COUNT(*) FILTER (WHERE is_top_level)::bigint AS top_level_notes,
                    COUNT(*) FILTER (
                        WHERE xref IS NOT NULL AND TRIM(xref) <> ''
                    )::bigint AS with_xref,
                    ROUND(AVG(LENGTH(content))::numeric, 1)::float AS avg_content_length
                FROM gedcom_notes_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            summary = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(DISTINCT note_id)::bigint AS distinct_notes_linked
                FROM (
                    SELECT note_id FROM gedcom_individual_notes_v2
                    WHERE file_uuid = %s
                    UNION
                    SELECT note_id FROM gedcom_family_notes_v2
                    WHERE file_uuid = %s
                    UNION
                    SELECT note_id FROM gedcom_event_notes_v2
                    WHERE file_uuid = %s
                    UNION
                    SELECT note_id FROM gedcom_source_notes_v2
                    WHERE file_uuid = %s
                ) u
                """,
                (file_uuid, file_uuid, file_uuid, file_uuid),
            )
            summary["distinct_notes_linked"] = dict(cur.fetchone())[
                "distinct_notes_linked"
            ]

            cur.execute(
                """
                SELECT COUNT(*)::bigint AS orphan_notes
                FROM gedcom_notes_v2 n
                WHERE n.file_uuid = %s
                    AND NOT EXISTS (
                        SELECT 1 FROM gedcom_individual_notes_v2 i
                        WHERE i.note_id = n.id AND i.file_uuid = n.file_uuid
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM gedcom_family_notes_v2 fn
                        WHERE fn.note_id = n.id AND fn.file_uuid = n.file_uuid
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM gedcom_event_notes_v2 en
                        WHERE en.note_id = n.id AND en.file_uuid = n.file_uuid
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM gedcom_source_notes_v2 sn
                        WHERE sn.note_id = n.id AND sn.file_uuid = n.file_uuid
                    )
                """,
                (file_uuid,),
            )
            summary["orphan_notes"] = dict(cur.fetchone())["orphan_notes"]

            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM gedcom_individual_notes_v2
                     WHERE file_uuid = %s)::bigint AS individual_note_links,
                    (SELECT COUNT(*) FROM gedcom_family_notes_v2
                     WHERE file_uuid = %s)::bigint AS family_note_links,
                    (SELECT COUNT(*) FROM gedcom_event_notes_v2
                     WHERE file_uuid = %s)::bigint AS event_note_links,
                    (SELECT COUNT(*) FROM gedcom_source_notes_v2
                     WHERE file_uuid = %s)::bigint AS source_note_links
                """,
                (file_uuid, file_uuid, file_uuid, file_uuid),
            )
            link_counts = dict(cur.fetchone())

            cur.execute(
                """
                WITH per AS (
                    SELECT note_id, COUNT(*)::bigint AS c
                    FROM gedcom_individual_notes_v2
                    WHERE file_uuid = %s
                    GROUP BY note_id
                    UNION ALL
                    SELECT note_id, COUNT(*)::bigint
                    FROM gedcom_family_notes_v2
                    WHERE file_uuid = %s
                    GROUP BY note_id
                    UNION ALL
                    SELECT note_id, COUNT(*)::bigint
                    FROM gedcom_event_notes_v2
                    WHERE file_uuid = %s
                    GROUP BY note_id
                    UNION ALL
                    SELECT note_id, COUNT(*)::bigint
                    FROM gedcom_source_notes_v2
                    WHERE file_uuid = %s
                    GROUP BY note_id
                ),
                agg AS (
                    SELECT note_id, SUM(c)::bigint AS link_count
                    FROM per
                    GROUP BY note_id
                )
                SELECT
                    n.id::text AS note_id,
                    COALESCE(NULLIF(TRIM(n.xref), ''), '') AS xref,
                    LEFT(
                        REGEXP_REPLACE(TRIM(n.content), E'\\\\s+', ' ', 'g'),
                        120
                    ) AS preview,
                    agg.link_count::bigint AS link_count
                FROM agg
                INNER JOIN gedcom_notes_v2 n
                    ON n.id = agg.note_id AND n.file_uuid = %s
                ORDER BY link_count DESC
                LIMIT %s
                """,
                (file_uuid, file_uuid, file_uuid, file_uuid, file_uuid, top_n),
            )
            top_notes = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    ind.id::text AS individual_id,
                    ind.full_name AS full_name,
                    COUNT(*)::bigint AS note_link_count
                FROM gedcom_individual_notes_v2 inn
                INNER JOIN gedcom_individuals_v2 ind
                    ON ind.id = inn.individual_id
                    AND ind.file_uuid = inn.file_uuid
                WHERE inn.file_uuid = %s
                GROUP BY ind.id, ind.full_name
                ORDER BY note_link_count DESC
                LIMIT %s
                """,
                (file_uuid, top_n),
            )
            top_individuals = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    f.id::text AS family_id,
                    f.xref AS xref,
                    CASE
                        WHEN NULLIF(TRIM(MAX(h.full_name)), '') IS NOT NULL
                            AND NULLIF(TRIM(MAX(w.full_name)), '') IS NOT NULL
                        THEN 'Family of '
                            || TRIM(MAX(h.full_name))
                            || ' and '
                            || TRIM(MAX(w.full_name))
                        WHEN NULLIF(TRIM(MAX(h.full_name)), '') IS NOT NULL
                        THEN 'Family of ' || TRIM(MAX(h.full_name))
                        WHEN NULLIF(TRIM(MAX(w.full_name)), '') IS NOT NULL
                        THEN 'Family of ' || TRIM(MAX(w.full_name))
                        ELSE COALESCE(NULLIF(TRIM(MAX(f.xref)), ''), 'Family')
                    END AS label,
                    COUNT(*)::bigint AS note_link_count
                FROM gedcom_family_notes_v2 fn
                INNER JOIN gedcom_families_v2 f
                    ON f.id = fn.family_id AND f.file_uuid = fn.file_uuid
                LEFT JOIN gedcom_individuals_v2 h
                    ON h.id = f.husband_id AND h.file_uuid = f.file_uuid
                LEFT JOIN gedcom_individuals_v2 w
                    ON w.id = f.wife_id AND w.file_uuid = f.file_uuid
                WHERE fn.file_uuid = %s
                GROUP BY f.id, f.xref
                ORDER BY note_link_count DESC
                LIMIT %s
                """,
                (file_uuid, top_n),
            )
            top_families = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    e.id::text AS event_id,
                    COALESCE(
                        NULLIF(TRIM(e.event_label), ''),
                        e.event_type
                        || CASE
                            WHEN NULLIF(TRIM(e.custom_type), '') IS NOT NULL
                            THEN ' — ' || TRIM(e.custom_type)
                            ELSE ''
                        END
                    ) AS label,
                    e.event_type::text AS event_type,
                    COUNT(*)::bigint AS note_link_count
                FROM gedcom_event_notes_v2 en
                INNER JOIN gedcom_events_v2 e
                    ON e.id = en.event_id AND e.file_uuid = en.file_uuid
                WHERE en.file_uuid = %s
                GROUP BY e.id, e.event_label, e.event_type, e.custom_type
                ORDER BY note_link_count DESC
                LIMIT %s
                """,
                (file_uuid, top_n),
            )
            top_events = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    s.id::text AS source_id,
                    s.xref AS xref,
                    COALESCE(
                        NULLIF(TRIM(s.title), ''),
                        NULLIF(TRIM(s.xref), ''),
                        s.id::text
                    ) AS label,
                    COUNT(*)::bigint AS note_link_count
                FROM gedcom_source_notes_v2 sn
                INNER JOIN gedcom_sources_v2 s
                    ON s.id = sn.source_id AND s.file_uuid = sn.file_uuid
                WHERE sn.file_uuid = %s
                GROUP BY s.id, s.xref, s.title
                ORDER BY note_link_count DESC
                LIMIT %s
                """,
                (file_uuid, top_n),
            )
            top_sources = [dict(row) for row in cur.fetchall()]
    return {
        "tree_id": tree_id,
        "summary": summary,
        "link_counts": link_counts,
        "top_notes": top_notes,
        "top_individuals": top_individuals,
        "top_families": top_families,
        "top_events": top_events,
        "top_sources": top_sources,
    }

