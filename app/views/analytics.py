"""Analytics endpoints — name statistics for charts and force-directed graphs."""
from flask import Blueprint, jsonify, request

from app.db import get_connection

bp = Blueprint("analytics", __name__, url_prefix="/api/research/trees")


def _get_file_uuid_for_tree(tree_id: str) -> str | None:
    """Resolve tree_id to gedcom file_uuid. Returns None if tree not found."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # trees.file_id -> gedcom_files.file_id; gedcom_files.id is file_uuid
            cur.execute(
                """
                SELECT gf.id AS file_uuid
                FROM trees t
                JOIN gedcom_files gf ON gf.file_id = t.file_id
                WHERE t.id = %s
                """,
                (tree_id,),
            )
            row = cur.fetchone()
            return row["file_uuid"] if row else None


@bp.route("/<tree_id>/analytics/given-names", methods=["GET"])
def given_names_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/given-names

    Returns statistics for given names: aggregates, top names, frequency distribution,
    optionally by decade and sex (for charts, force-directed graph data).
    """
    file_uuid = _get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return jsonify({"error": "Tree not found"}), 404

    limit = min(int(request.args.get("limit", 50)), 200)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_unique_names,
                    SUM(frequency) AS total_individuals_with_names,
                    COUNT(*) FILTER (WHERE frequency = 1) AS names_appearing_once,
                    COUNT(*) FILTER (WHERE frequency >= 2 AND frequency < 10) AS names_2_to_9,
                    COUNT(*) FILTER (WHERE frequency >= 10) AS names_10_plus
                FROM gedcom_given_names_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            summary = dict(cur.fetchone())

            cur.execute(
                """
                SELECT id, given_name AS name, frequency
                FROM gedcom_given_names_v2
                WHERE file_uuid = %s
                ORDER BY frequency DESC
                LIMIT %s
                """,
                (file_uuid, limit),
            )
            top_names = [dict(row) for row in cur.fetchall()]

            # Frequency distribution buckets (for histogram)
            cur.execute(
                """
                SELECT bucket, count FROM (
                    SELECT
                        CASE
                            WHEN frequency = 1 THEN '1'
                            WHEN frequency BETWEEN 2 AND 5 THEN '2-5'
                            WHEN frequency BETWEEN 6 AND 10 THEN '6-10'
                            WHEN frequency BETWEEN 11 AND 25 THEN '11-25'
                            WHEN frequency BETWEEN 26 AND 50 THEN '26-50'
                            ELSE '50+'
                        END AS bucket,
                        COUNT(*) AS count
                    FROM gedcom_given_names_v2
                    WHERE file_uuid = %s
                    GROUP BY 1
                ) x
                ORDER BY CASE bucket
                    WHEN '1' THEN 1
                    WHEN '2-5' THEN 2
                    WHEN '6-10' THEN 3
                    WHEN '11-25' THEN 4
                    WHEN '26-50' THEN 5
                    ELSE 6
                END
                """,
                (file_uuid,),
            )
            frequency_distribution = [dict(row) for row in cur.fetchall()]

            # By sex (if available): join through name forms -> individuals
            cur.execute(
                """
                SELECT
                    gn.given_name AS name,
                    gn.frequency,
                    COALESCE(SUM(CASE WHEN ind.sex::text = 'M' THEN 1 ELSE 0 END), 0)::int AS males_count,
                    COALESCE(SUM(CASE WHEN ind.sex::text = 'F' THEN 1 ELSE 0 END), 0)::int AS females_count,
                    COALESCE(SUM(CASE WHEN ind.sex IS NULL OR ind.sex::text NOT IN ('M', 'F') THEN 1 ELSE 0 END), 0)::int AS unknown_count
                FROM gedcom_given_names_v2 gn
                JOIN gedcom_name_form_given_names nfgn ON nfgn.given_name_id = gn.id
                JOIN gedcom_individual_name_forms nf ON nf.id = nfgn.name_form_id
                JOIN gedcom_individuals_v2 ind ON ind.id = nf.individual_id
                WHERE gn.file_uuid = %s
                GROUP BY gn.id, gn.given_name, gn.frequency
                ORDER BY gn.frequency DESC
                LIMIT %s
                """,
                (file_uuid, limit),
            )
            names_with_sex = [dict(row) for row in cur.fetchall()]

            # Top 10 names for men (by males_count)
            cur.execute(
                """
                SELECT gn.given_name AS name, gn.id,
                    COALESCE(SUM(CASE WHEN ind.sex::text = 'M' THEN 1 ELSE 0 END), 0)::int AS males_count
                FROM gedcom_given_names_v2 gn
                JOIN gedcom_name_form_given_names nfgn ON nfgn.given_name_id = gn.id
                JOIN gedcom_individual_name_forms nf ON nf.id = nfgn.name_form_id
                JOIN gedcom_individuals_v2 ind ON ind.id = nf.individual_id
                WHERE gn.file_uuid = %s
                GROUP BY gn.id, gn.given_name
                HAVING COALESCE(SUM(CASE WHEN ind.sex::text = 'M' THEN 1 ELSE 0 END), 0) > 0
                ORDER BY males_count DESC
                LIMIT 10
                """,
                (file_uuid,),
            )
            top_10_male = [dict(row) for row in cur.fetchall()]

            # Top 10 names for women (by females_count)
            cur.execute(
                """
                SELECT gn.given_name AS name, gn.id,
                    COALESCE(SUM(CASE WHEN ind.sex::text = 'F' THEN 1 ELSE 0 END), 0)::int AS females_count
                FROM gedcom_given_names_v2 gn
                JOIN gedcom_name_form_given_names nfgn ON nfgn.given_name_id = gn.id
                JOIN gedcom_individual_name_forms nf ON nf.id = nfgn.name_form_id
                JOIN gedcom_individuals_v2 ind ON ind.id = nf.individual_id
                WHERE gn.file_uuid = %s
                GROUP BY gn.id, gn.given_name
                HAVING COALESCE(SUM(CASE WHEN ind.sex::text = 'F' THEN 1 ELSE 0 END), 0) > 0
                ORDER BY females_count DESC
                LIMIT 10
                """,
                (file_uuid,),
            )
            top_10_female = [dict(row) for row in cur.fetchall()]

            # By decade (birth year) - for temporal charts (top 20 names only)
            cur.execute(
                """
                WITH top_names AS (
                    SELECT id FROM gedcom_given_names_v2
                    WHERE file_uuid = %s
                    ORDER BY frequency DESC
                    LIMIT 20
                )
                SELECT
                    gn.given_name AS name,
                    (FLOOR(ind.birth_year::numeric / 10) * 10)::int AS decade,
                    COUNT(DISTINCT ind.id) AS count
                FROM gedcom_given_names_v2 gn
                JOIN gedcom_name_form_given_names nfgn ON nfgn.given_name_id = gn.id
                JOIN gedcom_individual_name_forms nf ON nf.id = nfgn.name_form_id
                JOIN gedcom_individuals_v2 ind ON ind.id = nf.individual_id
                WHERE gn.file_uuid = %s
                  AND ind.birth_year IS NOT NULL
                  AND gn.id IN (SELECT id FROM top_names)
                GROUP BY gn.given_name, decade
                ORDER BY gn.given_name, decade
                """,
                (file_uuid, file_uuid),
            )
            by_decade = [dict(row) for row in cur.fetchall()]

    return jsonify({
        "tree_id": tree_id,
        "summary": summary,
        "top_names": top_names,
        "top_names_with_sex": names_with_sex,
        "top_10_male": top_10_male,
        "top_10_female": top_10_female,
        "frequency_distribution": frequency_distribution,
        "popularity_by_decade": by_decade,
    })


@bp.route("/<tree_id>/analytics/surnames", methods=["GET"])
def surnames_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/surnames

    Returns statistics for surnames: aggregates, top names, frequency distribution,
    optionally by decade (for charts, force-directed graph data).
    """
    file_uuid = _get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return jsonify({"error": "Tree not found"}), 404

    limit = min(int(request.args.get("limit", 50)), 200)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_unique_surnames,
                    SUM(frequency) AS total_occurrences,
                    COUNT(*) FILTER (WHERE frequency = 1) AS surnames_appearing_once,
                    COUNT(*) FILTER (WHERE frequency >= 2 AND frequency < 10) AS surnames_2_to_9,
                    COUNT(*) FILTER (WHERE frequency >= 10) AS surnames_10_plus
                FROM gedcom_surnames_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            summary = dict(cur.fetchone())

            cur.execute(
                """
                SELECT id, surname AS name, frequency, soundex, metaphone
                FROM gedcom_surnames_v2
                WHERE file_uuid = %s
                ORDER BY frequency DESC
                LIMIT %s
                """,
                (file_uuid, limit),
            )
            top_surnames = [dict(row) for row in cur.fetchall()]

            # Frequency distribution buckets
            cur.execute(
                """
                SELECT bucket, count FROM (
                    SELECT
                        CASE
                            WHEN frequency = 1 THEN '1'
                            WHEN frequency BETWEEN 2 AND 5 THEN '2-5'
                            WHEN frequency BETWEEN 6 AND 10 THEN '6-10'
                            WHEN frequency BETWEEN 11 AND 25 THEN '11-25'
                            WHEN frequency BETWEEN 26 AND 50 THEN '26-50'
                            ELSE '50+'
                        END AS bucket,
                        COUNT(*) AS count
                    FROM gedcom_surnames_v2
                    WHERE file_uuid = %s
                    GROUP BY 1
                ) x
                ORDER BY CASE bucket
                    WHEN '1' THEN 1
                    WHEN '2-5' THEN 2
                    WHEN '6-10' THEN 3
                    WHEN '11-25' THEN 4
                    WHEN '26-50' THEN 5
                    ELSE 6
                END
                """,
                (file_uuid,),
            )
            frequency_distribution = [dict(row) for row in cur.fetchall()]

            # Surnames with Soundex/Phonetic similarity (for force-directed edges)
            # Group by soundex to show phonetically similar names
            cur.execute(
                """
                SELECT soundex, COUNT(*) AS name_count, SUM(frequency) AS total_frequency
                FROM gedcom_surnames_v2
                WHERE file_uuid = %s AND soundex IS NOT NULL AND soundex != ''
                GROUP BY soundex
                HAVING COUNT(*) > 1
                ORDER BY total_frequency DESC
                LIMIT 30
                """,
                (file_uuid,),
            )
            soundex_groups = [dict(row) for row in cur.fetchall()]

            # By decade (birth year) - for temporal charts (top 20 surnames only)
            cur.execute(
                """
                WITH top_surnames AS (
                    SELECT id FROM gedcom_surnames_v2
                    WHERE file_uuid = %s
                    ORDER BY frequency DESC
                    LIMIT 20
                )
                SELECT
                    s.surname AS name,
                    (FLOOR(ind.birth_year::numeric / 10) * 10)::int AS decade,
                    COUNT(DISTINCT ind.id) AS count
                FROM gedcom_surnames_v2 s
                JOIN gedcom_name_form_surnames nfs ON nfs.surname_id = s.id
                JOIN gedcom_individual_name_forms nf ON nf.id = nfs.name_form_id
                JOIN gedcom_individuals_v2 ind ON ind.id = nf.individual_id
                WHERE s.file_uuid = %s
                  AND ind.birth_year IS NOT NULL
                  AND s.id IN (SELECT id FROM top_surnames)
                GROUP BY s.surname, decade
                ORDER BY s.surname, decade
                """,
                (file_uuid, file_uuid),
            )
            popularity_by_decade = [dict(row) for row in cur.fetchall()]

            # By place (birth country) - for location charts (top 15 surnames, top 20 countries)
            cur.execute(
                """
                WITH top_surnames AS (
                    SELECT id FROM gedcom_surnames_v2
                    WHERE file_uuid = %s
                    ORDER BY frequency DESC
                    LIMIT 15
                ),
                top_countries AS (
                    SELECT COALESCE(p.country, 'Unknown') AS place_country
                    FROM gedcom_individuals_v2 ind
                    JOIN gedcom_places_v2 p ON p.id = ind.birth_place_id
                    WHERE ind.file_uuid = %s AND ind.birth_place_id IS NOT NULL
                    GROUP BY COALESCE(p.country, 'Unknown')
                    ORDER BY COUNT(*) DESC
                    LIMIT 20
                )
                SELECT
                    s.surname AS name,
                    COALESCE(p.country, 'Unknown') AS place_country,
                    COUNT(DISTINCT ind.id) AS count
                FROM gedcom_surnames_v2 s
                JOIN gedcom_name_form_surnames nfs ON nfs.surname_id = s.id
                JOIN gedcom_individual_name_forms nf ON nf.id = nfs.name_form_id
                JOIN gedcom_individuals_v2 ind ON ind.id = nf.individual_id
                LEFT JOIN gedcom_places_v2 p ON p.id = ind.birth_place_id
                WHERE s.file_uuid = %s
                  AND ind.birth_place_id IS NOT NULL
                  AND s.id IN (SELECT id FROM top_surnames)
                  AND COALESCE(p.country, 'Unknown') IN (SELECT place_country FROM top_countries)
                GROUP BY s.surname, COALESCE(p.country, 'Unknown')
                ORDER BY s.surname, place_country
                """,
                (file_uuid, file_uuid, file_uuid),
            )
            popularity_by_place = [dict(row) for row in cur.fetchall()]

    return jsonify({
        "tree_id": tree_id,
        "summary": summary,
        "top_surnames": top_surnames,
        "frequency_distribution": frequency_distribution,
        "soundex_groups": soundex_groups,
        "popularity_by_decade": popularity_by_decade,
        "popularity_by_place": popularity_by_place,
    })
