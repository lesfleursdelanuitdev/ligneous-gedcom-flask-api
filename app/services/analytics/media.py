"""Media: GEDCOM OBJE rows, link topology, albums, app tags, ranked link targets.

`gedcom_media_v2` with per-entity link rankings and tree-scoped album counts.
"""

from app.db import get_connection
from app.services.analytics.utils import get_file_uuid_for_tree


def get_media_statistics(tree_id: str, top_n: int) -> dict | None:
    """Aggregates from `gedcom_media_v2` and media junction / album tables."""
    file_uuid = get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)::bigint AS total_gedcom_media,
                    COUNT(*) FILTER (
                        WHERE title IS NOT NULL AND TRIM(title) <> ''
                    )::bigint AS with_title,
                    COUNT(*) FILTER (
                        WHERE form IS NOT NULL AND TRIM(form) <> ''
                    )::bigint AS with_form
                FROM gedcom_media_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            summary_media = dict(cur.fetchone())

            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM gedcom_individual_media_v2
                     WHERE file_uuid = %s)::bigint AS individual_media_links,
                    (SELECT COUNT(*) FROM gedcom_family_media_v2
                     WHERE file_uuid = %s)::bigint AS family_media_links,
                    (SELECT COUNT(*) FROM gedcom_event_media_v2
                     WHERE file_uuid = %s)::bigint AS event_media_links,
                    (SELECT COUNT(*) FROM gedcom_source_media_v2
                     WHERE file_uuid = %s)::bigint AS source_media_links,
                    (SELECT COUNT(*) FROM gedcom_media_places_v2
                     WHERE file_uuid = %s)::bigint AS media_place_links,
                    (SELECT COUNT(*) FROM gedcom_media_dates_v2
                     WHERE file_uuid = %s)::bigint AS media_date_links
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
            link_counts = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(*)::bigint AS cnt
                FROM gedcom_media_app_tags gt
                INNER JOIN gedcom_media_v2 m
                    ON m.id = gt.gedcom_media_id AND m.file_uuid = %s
                """,
                (file_uuid,),
            )
            media_tag_assignment_rows = dict(cur.fetchone())["cnt"]

            cur.execute(
                """
                SELECT COUNT(DISTINCT gt.tag_id)::bigint AS cnt
                FROM gedcom_media_app_tags gt
                INNER JOIN gedcom_media_v2 m
                    ON m.id = gt.gedcom_media_id AND m.file_uuid = %s
                """,
                (file_uuid,),
            )
            distinct_tags_on_media = dict(cur.fetchone())["cnt"]

            cur.execute(
                """
                SELECT COUNT(*)::bigint AS album_count
                FROM albums
                WHERE tree_id = %s::uuid
                """,
                (tree_id,),
            )
            album_count_for_tree = dict(cur.fetchone())["album_count"]

            cur.execute(
                """
                SELECT COUNT(*)::bigint AS album_gedcom_media_links
                FROM album_gedcom_media agm
                INNER JOIN albums a ON a.id = agm.album_id
                WHERE a.tree_id = %s::uuid
                """,
                (tree_id,),
            )
            album_gedcom_media_links = dict(cur.fetchone())[
                "album_gedcom_media_links"
            ]

            cur.execute(
                """
                SELECT
                    p.id::text AS place_id,
                    COALESCE(
                        NULLIF(TRIM(p.name), ''),
                        NULLIF(TRIM(p.original), ''),
                        '(unnamed place)'
                    ) AS label,
                    COALESCE(NULLIF(TRIM(p.country), ''), '') AS country,
                    COUNT(*)::bigint AS link_count
                FROM gedcom_media_places_v2 mp
                INNER JOIN gedcom_places_v2 p
                    ON p.id = mp.place_id AND p.file_uuid = mp.file_uuid
                WHERE mp.file_uuid = %s
                GROUP BY p.id, p.name, p.original, p.country
                ORDER BY link_count DESC
                LIMIT %s
                """,
                (file_uuid, top_n),
            )
            top_places_for_media = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
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
                    COUNT(*)::bigint AS link_count
                FROM gedcom_media_dates_v2 md
                INNER JOIN gedcom_dates_v2 d
                    ON d.id = md.date_id AND d.file_uuid = md.file_uuid
                WHERE md.file_uuid = %s
                GROUP BY d.id, d.original, d.year, d.month, d.day, d.date_type
                ORDER BY link_count DESC
                LIMIT %s
                """,
                (file_uuid, top_n),
            )
            top_dates_for_media = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    ind.id::text AS individual_id,
                    ind.full_name AS full_name,
                    COUNT(*)::bigint AS media_link_count
                FROM gedcom_individual_media_v2 im
                INNER JOIN gedcom_individuals_v2 ind
                    ON ind.id = im.individual_id
                    AND ind.file_uuid = im.file_uuid
                WHERE im.file_uuid = %s
                GROUP BY ind.id, ind.full_name
                ORDER BY media_link_count DESC
                LIMIT %s
                """,
                (file_uuid, top_n),
            )
            top_individuals_by_media = [dict(row) for row in cur.fetchall()]

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
                    COUNT(*)::bigint AS media_link_count
                FROM gedcom_family_media_v2 fm
                INNER JOIN gedcom_families_v2 f
                    ON f.id = fm.family_id AND f.file_uuid = fm.file_uuid
                LEFT JOIN gedcom_individuals_v2 h
                    ON h.id = f.husband_id AND h.file_uuid = f.file_uuid
                LEFT JOIN gedcom_individuals_v2 w
                    ON w.id = f.wife_id AND w.file_uuid = f.file_uuid
                WHERE fm.file_uuid = %s
                GROUP BY f.id, f.xref
                ORDER BY media_link_count DESC
                LIMIT %s
                """,
                (file_uuid, top_n),
            )
            top_families_by_media = [dict(row) for row in cur.fetchall()]

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
                    COUNT(*)::bigint AS media_link_count
                FROM gedcom_event_media_v2 em
                INNER JOIN gedcom_events_v2 e
                    ON e.id = em.event_id AND e.file_uuid = em.file_uuid
                WHERE em.file_uuid = %s
                GROUP BY e.id, e.event_label, e.event_type, e.custom_type
                ORDER BY media_link_count DESC
                LIMIT %s
                """,
                (file_uuid, top_n),
            )
            top_events_by_media = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    t.id::text AS tag_id,
                    t.name AS name,
                    COALESCE(NULLIF(TRIM(t.color), ''), '#6B7280') AS color,
                    COUNT(*)::bigint AS tag_count
                FROM gedcom_media_app_tags gt
                INNER JOIN gedcom_media_v2 m
                    ON m.id = gt.gedcom_media_id AND m.file_uuid = %s
                INNER JOIN tags t ON t.id = gt.tag_id
                GROUP BY t.id, t.name, t.color
                ORDER BY tag_count DESC
                LIMIT %s
                """,
                (file_uuid, top_n),
            )
            top_media_tags = [dict(row) for row in cur.fetchall()]
    summary_media["media_tag_assignment_rows"] = media_tag_assignment_rows
    summary_media["distinct_tags_on_media"] = distinct_tags_on_media

    return {
        "tree_id": tree_id,
        "summary": summary_media,
        "link_counts": link_counts,
        "albums": {
            "album_count_for_tree": album_count_for_tree,
            "album_gedcom_media_links": album_gedcom_media_links,
        },
        "top_places_for_media": top_places_for_media,
        "top_dates_for_media": top_dates_for_media,
        "top_individuals_by_media": top_individuals_by_media,
        "top_families_by_media": top_families_by_media,
        "top_events_by_media": top_events_by_media,
        "top_media_tags": top_media_tags,
    }

