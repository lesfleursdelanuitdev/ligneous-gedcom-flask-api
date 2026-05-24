"""Open research questions: resolution status and entities with the most question links.

`open_questions` scoped by `file_uuid` with per-entity rankings.
"""

from app.db import get_connection
from app.services.analytics.utils import get_file_uuid_for_tree


def get_open_questions_statistics(tree_id: str, top_n: int) -> dict | None:
    """Aggregates from `open_questions` and per-entity question links."""
    file_uuid = get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)::bigint AS total,
                    COUNT(*) FILTER (WHERE status::text = 'resolved')::bigint
                        AS resolved,
                    COUNT(*) FILTER (WHERE status::text <> 'resolved')::bigint
                        AS unresolved
                FROM open_questions
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            summary = dict(cur.fetchone())

            cur.execute(
                """
                SELECT
                    ind.id::text AS individual_id,
                    ind.full_name AS full_name,
                    COUNT(*)::bigint AS question_link_count
                FROM open_question_individuals oqi
                INNER JOIN open_questions oq
                    ON oq.id = oqi.open_question_id AND oq.file_uuid = %s
                INNER JOIN gedcom_individuals_v2 ind
                    ON ind.id = oqi.individual_id AND ind.file_uuid = %s
                GROUP BY ind.id, ind.full_name
                ORDER BY question_link_count DESC
                LIMIT %s
                """,
                (file_uuid, file_uuid, top_n),
            )
            top_individuals = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    m.id::text AS media_id,
                    COALESCE(
                        NULLIF(TRIM(m.title), ''),
                        NULLIF(TRIM(m.file_ref), ''),
                        m.id::text
                    ) AS label,
                    COUNT(*)::bigint AS question_link_count
                FROM open_question_media oqm
                INNER JOIN open_questions oq
                    ON oq.id = oqm.open_question_id AND oq.file_uuid = %s
                INNER JOIN gedcom_media_v2 m
                    ON m.id = oqm.media_id AND m.file_uuid = %s
                GROUP BY m.id, m.title, m.file_ref
                ORDER BY question_link_count DESC
                LIMIT %s
                """,
                (file_uuid, file_uuid, top_n),
            )
            top_media = [dict(row) for row in cur.fetchall()]

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
                    COUNT(*)::bigint AS question_link_count
                FROM open_question_families oqf
                INNER JOIN open_questions oq
                    ON oq.id = oqf.open_question_id AND oq.file_uuid = %s
                INNER JOIN gedcom_families_v2 f
                    ON f.id = oqf.family_id AND f.file_uuid = %s
                LEFT JOIN gedcom_individuals_v2 h
                    ON h.id = f.husband_id AND h.file_uuid = f.file_uuid
                LEFT JOIN gedcom_individuals_v2 w
                    ON w.id = f.wife_id AND w.file_uuid = f.file_uuid
                GROUP BY f.id, f.xref
                ORDER BY question_link_count DESC
                LIMIT %s
                """,
                (file_uuid, file_uuid, top_n),
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
                    COUNT(*)::bigint AS question_link_count
                FROM open_question_events oqe
                INNER JOIN open_questions oq
                    ON oq.id = oqe.open_question_id AND oq.file_uuid = %s
                INNER JOIN gedcom_events_v2 e
                    ON e.id = oqe.event_id AND e.file_uuid = %s
                GROUP BY e.id, e.event_label, e.event_type, e.custom_type
                ORDER BY question_link_count DESC
                LIMIT %s
                """,
                (file_uuid, file_uuid, top_n),
            )
            top_events = [dict(row) for row in cur.fetchall()]
    return {
        "tree_id": tree_id,
        "summary": summary,
        "top_individuals": top_individuals,
        "top_media": top_media,
        "top_families": top_families,
        "top_events": top_events,
    }

