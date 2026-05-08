"""Analytics endpoints — entity statistics for charts (names, individuals, …)."""
from flask import Blueprint, jsonify, request

from app.db import get_connection

bp = Blueprint("analytics", __name__, url_prefix="/api/research/trees")

# Display names when the DB stores the raw tag as `label` (unlinked rows / legacy).
_GEDCOM_EVENT_TAG_LABELS: dict[str, str] = {
    "ADOP": "Adoption",
    "ANUL": "Annulment",
    "BAPM": "Baptism (LDS)",
    "BARM": "Bar mitzvah",
    "BASM": "Bas mitzvah",
    "BIRT": "Birth",
    "BLES": "Blessing",
    "BURI": "Burial",
    "CENS": "Census",
    "CHR": "Christening",
    "CHRA": "Adult christening",
    "CONF": "Confirmation",
    "CREM": "Cremation",
    "DEAT": "Death",
    "DIV": "Divorce",
    "DIVF": "Divorce filed",
    "EMIG": "Emigration",
    "ENGA": "Engagement",
    "EVEN": "Event",
    "FCOM": "First communion",
    "GRAD": "Graduation",
    "IMMI": "Immigration",
    "MARR": "Marriage",
    "MARB": "Marriage bann",
    "MARC": "Marriage contract",
    "MARL": "Marriage license",
    "MARS": "Marriage settlement",
    "NATU": "Naturalization",
    "ORDN": "Ordination",
    "PROB": "Probate",
    "PROP": "Property",
    "RELI": "Religion",
    "RESI": "Residence",
    "RETI": "Retirement",
    "WILL": "Will",
    "CUST": "Custom",
}


def _friendly_event_label(tag: str | None, catalog_label: str | None) -> str:
    """Prefer catalog label; otherwise map common GEDCOM tags to plain language."""
    t = (tag or "").strip().upper()
    raw = (catalog_label or "").strip()
    if raw and raw.upper() != t:
        return raw
    return _GEDCOM_EVENT_TAG_LABELS.get(t, raw or tag or "Unknown")


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


@bp.route("/<tree_id>/analytics/individuals", methods=["GET"])
def individuals_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/individuals

    Aggregates from gedcom_individuals_v2: counts, sex, birth/decade histograms,
    age-at-death buckets, top birth countries.     family_roles uses
    gedcom_family_children_v2 (as child) and husband_id/wife_id on gedcom_families_v2
    (as spouse in a family). Lifespan uses age_at_death; ASSO count is
    gedcom_individual_associations_v2. Optional query param: top_n (default 10, max 50)
    for oldest_lived / youngest_died.
    """
    file_uuid = _get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return jsonify({"error": "Tree not found"}), 404

    country_limit = min(int(request.args.get("country_limit", 20)), 100)
    top_n = min(int(request.args.get("top_n", 10)), 50)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)::bigint AS total,
                    COUNT(*) FILTER (WHERE is_living = true)::bigint AS living,
                    COUNT(*) FILTER (WHERE is_living = false)::bigint AS deceased,
                    COUNT(*) FILTER (WHERE sex::text = 'M')::bigint AS male,
                    COUNT(*) FILTER (WHERE sex::text = 'F')::bigint AS female,
                    COUNT(*) FILTER (WHERE sex IS NULL OR sex::text NOT IN ('M', 'F'))::bigint AS sex_unknown,
                    COUNT(*) FILTER (WHERE birth_year IS NOT NULL)::bigint AS with_birth_year,
                    COUNT(*) FILTER (WHERE death_year IS NOT NULL)::bigint AS with_death_year,
                    COUNT(*) FILTER (WHERE birth_place_id IS NOT NULL)::bigint AS with_birth_place,
                    COUNT(*) FILTER (WHERE birth_country IS NOT NULL AND TRIM(birth_country) <> '')::bigint AS with_birth_country,
                    COUNT(*) FILTER (WHERE has_parents = true)::bigint AS has_parents,
                    COUNT(*) FILTER (WHERE has_children = true)::bigint AS has_children,
                    COUNT(*) FILTER (WHERE has_spouse = true)::bigint AS has_spouse,
                    COUNT(*) FILTER (WHERE age_at_death IS NOT NULL)::bigint AS with_age_at_death
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            summary = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COALESCE(sex::text, 'U') AS sex, COUNT(*)::bigint AS count
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s
                GROUP BY COALESCE(sex::text, 'U')
                ORDER BY count DESC
                """,
                (file_uuid,),
            )
            by_sex = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE is_living = true AND sex::text = 'M'
                    )::bigint AS living_male,
                    COUNT(*) FILTER (
                        WHERE is_living = false AND sex::text = 'M'
                    )::bigint AS dead_male,
                    COUNT(*) FILTER (
                        WHERE is_living = true AND sex::text = 'F'
                    )::bigint AS living_female,
                    COUNT(*) FILTER (
                        WHERE is_living = false AND sex::text = 'F'
                    )::bigint AS dead_female,
                    COUNT(*) FILTER (
                        WHERE is_living = true
                        AND (sex IS NULL OR sex::text NOT IN ('M', 'F'))
                    )::bigint AS living_unknown,
                    COUNT(*) FILTER (
                        WHERE is_living = false
                        AND (sex IS NULL OR sex::text NOT IN ('M', 'F'))
                    )::bigint AS dead_unknown
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            sex_by_living = dict(cur.fetchone())

            cur.execute(
                """
                SELECT (FLOOR(birth_year::numeric / 10) * 10)::int AS decade, COUNT(*)::bigint AS count
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s AND birth_year IS NOT NULL
                GROUP BY 1
                ORDER BY 1
                """,
                (file_uuid,),
            )
            birth_by_decade = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT (FLOOR(death_year::numeric / 10) * 10)::int AS decade, COUNT(*)::bigint AS count
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s AND death_year IS NOT NULL
                GROUP BY 1
                ORDER BY 1
                """,
                (file_uuid,),
            )
            death_by_decade = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT bucket, count FROM (
                    SELECT
                        CASE
                            WHEN age_at_death < 1 THEN '<1'
                            WHEN age_at_death < 10 THEN '1-9'
                            WHEN age_at_death < 20 THEN '10-19'
                            WHEN age_at_death < 30 THEN '20-29'
                            WHEN age_at_death < 40 THEN '30-39'
                            WHEN age_at_death < 50 THEN '40-49'
                            WHEN age_at_death < 60 THEN '50-59'
                            WHEN age_at_death < 70 THEN '60-69'
                            WHEN age_at_death < 80 THEN '70-79'
                            WHEN age_at_death < 90 THEN '80-89'
                            WHEN age_at_death < 100 THEN '90-99'
                            ELSE '100+'
                        END AS bucket,
                        COUNT(*)::bigint AS count
                    FROM gedcom_individuals_v2
                    WHERE file_uuid = %s AND age_at_death IS NOT NULL
                    GROUP BY 1
                ) x
                ORDER BY CASE bucket
                    WHEN '<1' THEN 1
                    WHEN '1-9' THEN 2
                    WHEN '10-19' THEN 3
                    WHEN '20-29' THEN 4
                    WHEN '30-39' THEN 5
                    WHEN '40-49' THEN 6
                    WHEN '50-59' THEN 7
                    WHEN '60-69' THEN 8
                    WHEN '70-79' THEN 9
                    WHEN '80-89' THEN 10
                    WHEN '90-99' THEN 11
                    ELSE 12
                END
                """,
                (file_uuid,),
            )
            age_at_death_buckets = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    COALESCE(NULLIF(TRIM(birth_country), ''), 'Unknown') AS country,
                    COUNT(*)::bigint AS count
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s
                GROUP BY COALESCE(NULLIF(TRIM(birth_country), ''), 'Unknown')
                ORDER BY count DESC
                LIMIT %s
                """,
                (file_uuid, country_limit),
            )
            top_birth_countries = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    ROUND(
                        AVG(age_at_death) FILTER (
                            WHERE sex::text = 'M' AND age_at_death IS NOT NULL
                        )::numeric,
                        2
                    )::double precision AS avg_lifespan_male,
                    ROUND(
                        AVG(age_at_death) FILTER (
                            WHERE sex::text = 'F' AND age_at_death IS NOT NULL
                        )::numeric,
                        2
                    )::double precision AS avg_lifespan_female,
                    COUNT(*) FILTER (
                        WHERE sex::text = 'M' AND age_at_death IS NOT NULL
                    )::bigint AS males_with_age_at_death,
                    COUNT(*) FILTER (
                        WHERE sex::text = 'F' AND age_at_death IS NOT NULL
                    )::bigint AS females_with_age_at_death
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            lifespan_averages = dict(cur.fetchone())

            cur.execute(
                """
                SELECT id::text AS id,
                       full_name,
                       age_at_death,
                       birth_year,
                       death_year,
                       sex::text AS sex
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s AND age_at_death IS NOT NULL
                ORDER BY age_at_death DESC,
                         COALESCE(full_name, '') ASC,
                         id ASC
                LIMIT %s
                """,
                (file_uuid, top_n),
            )
            oldest_lived = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT id::text AS id,
                       full_name,
                       age_at_death,
                       birth_year,
                       death_year,
                       sex::text AS sex
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s AND age_at_death IS NOT NULL
                ORDER BY age_at_death ASC,
                         COALESCE(full_name, '') ASC,
                         id ASC
                LIMIT %s
                """,
                (file_uuid, top_n),
            )
            youngest_died = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT COUNT(*)::bigint AS association_records
                FROM gedcom_individual_associations_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            associations = dict(cur.fetchone())

            # Family roles: child rows vs husband/wife on families (same file).
            cur.execute(
                """
                SELECT COUNT(*)::bigint AS only_as_child
                FROM gedcom_individuals_v2 ind
                WHERE ind.file_uuid = %s
                  AND EXISTS (
                      SELECT 1 FROM gedcom_family_children_v2 fc
                      WHERE fc.file_uuid = %s AND fc.child_id = ind.id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM gedcom_families_v2 f
                      WHERE f.file_uuid = %s
                        AND (f.husband_id = ind.id OR f.wife_id = ind.id)
                  )
                """,
                (file_uuid, file_uuid, file_uuid),
            )
            only_as_child = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(*)::bigint AS only_as_spouse
                FROM gedcom_individuals_v2 ind
                WHERE ind.file_uuid = %s
                  AND EXISTS (
                      SELECT 1 FROM gedcom_families_v2 f
                      WHERE f.file_uuid = %s
                        AND (f.husband_id = ind.id OR f.wife_id = ind.id)
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM gedcom_family_children_v2 fc
                      WHERE fc.file_uuid = %s AND fc.child_id = ind.id
                  )
                """,
                (file_uuid, file_uuid, file_uuid),
            )
            only_as_spouse = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(*)::bigint AS multiple_families_as_child
                FROM (
                    SELECT fc.child_id
                    FROM gedcom_family_children_v2 fc
                    WHERE fc.file_uuid = %s
                    GROUP BY fc.child_id
                    HAVING COUNT(DISTINCT fc.family_id) > 1
                ) t
                """,
                (file_uuid,),
            )
            multiple_families_as_child = dict(cur.fetchone())

            cur.execute(
                """
                SELECT COUNT(*)::bigint AS multiple_families_as_spouse
                FROM (
                    SELECT individual_id
                    FROM (
                        SELECT f.husband_id AS individual_id, f.id AS family_id
                        FROM gedcom_families_v2 f
                        WHERE f.file_uuid = %s AND f.husband_id IS NOT NULL
                        UNION ALL
                        SELECT f.wife_id, f.id
                        FROM gedcom_families_v2 f
                        WHERE f.file_uuid = %s AND f.wife_id IS NOT NULL
                    ) roles
                    GROUP BY individual_id
                    HAVING COUNT(DISTINCT family_id) > 1
                ) t
                """,
                (file_uuid, file_uuid),
            )
            multiple_families_as_spouse = dict(cur.fetchone())

    family_roles = {
        "only_as_child": only_as_child["only_as_child"],
        "only_as_spouse": only_as_spouse["only_as_spouse"],
        "multiple_families_as_child": multiple_families_as_child[
            "multiple_families_as_child"
        ],
        "multiple_families_as_spouse": multiple_families_as_spouse[
            "multiple_families_as_spouse"
        ],
    }

    return jsonify({
        "tree_id": tree_id,
        "summary": summary,
        "family_roles": family_roles,
        "sex_by_living": sex_by_living,
        "lifespan_averages": lifespan_averages,
        "oldest_lived": oldest_lived,
        "youngest_died": youngest_died,
        "associations": associations,
        "by_sex": by_sex,
        "birth_by_decade": birth_by_decade,
        "death_by_decade": death_by_decade,
        "age_at_death_buckets": age_at_death_buckets,
        "top_birth_countries": top_birth_countries,
    })


@bp.route("/<tree_id>/analytics/families", methods=["GET"])
def families_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/families

    Aggregates from gedcom_families_v2 (partners, marriage year, children_count, divorce),
    junction counts, marriage place by country, child count min/max, non-biological
    parent–child links per family, families with a MARR event.
    """
    file_uuid = _get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return jsonify({"error": "Tree not found"}), 404

    country_limit = min(int(request.args.get("country_limit", 15)), 50)

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

    return jsonify({
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
    })


@bp.route("/<tree_id>/analytics/events", methods=["GET"])
def events_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/events

    Aggregates from gedcom_events_v2 + event_types / gedcom_event_event_types:
    friendly labels, standard vs custom instance breakdown, decade and country
    distributions, links to individuals/families and citations.

    Query params: type_limit, country_limit (optional caps).
    """
    file_uuid = _get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return jsonify({"error": "Tree not found"}), 404

    type_limit = min(int(request.args.get("type_limit", 30)), 150)
    country_limit = min(int(request.args.get("country_limit", 15)), 50)

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
                r["label"] = _friendly_event_label(r.get("tag"), r.get("catalog_label"))
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

    return jsonify({
        "tree_id": tree_id,
        "summary": summary,
        "junction_counts": junction_counts,
        "origin_breakdown": origin_breakdown,
        "type_catalog_breakdown": type_catalog_breakdown,
        "by_event_type": by_event_type,
        "year_by_decade": year_by_decade,
        "place_country_distribution": place_country_distribution,
    })


@bp.route("/<tree_id>/analytics/places", methods=["GET"])
def places_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/places

    Aggregates from gedcom_places_v2 and references from individuals, families,
    events, and media-place links: coverage, usage by entity type, geographic
    distributions, and most-referenced places.

    Query params: top_limit, country_limit, state_limit (optional caps).
    """
    file_uuid = _get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return jsonify({"error": "Tree not found"}), 404

    top_limit = min(int(request.args.get("top_limit", 25)), 150)
    country_limit = min(int(request.args.get("country_limit", 20)), 80)
    state_limit = min(int(request.args.get("state_limit", 20)), 80)

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

    return jsonify({
        "tree_id": tree_id,
        "summary": summary,
        "reference_counts": reference_counts,
        "country_distribution": country_distribution,
        "state_distribution": state_distribution,
        "top_places": top_places,
    })


@bp.route("/<tree_id>/analytics/dates", methods=["GET"])
def dates_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/dates

    Aggregates from gedcom_dates_v2 and references from individuals, families,
    events, and media-date links: coverage, usage by entity type, qualifier
    (date_type) mix, calendar tag, year-by-decade, and most-referenced dates.

    Query params: top_limit, calendar_limit (optional caps).
    """
    file_uuid = _get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return jsonify({"error": "Tree not found"}), 404

    top_limit = min(int(request.args.get("top_limit", 25)), 150)
    calendar_limit = min(int(request.args.get("calendar_limit", 15)), 50)

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

    return jsonify({
        "tree_id": tree_id,
        "summary": summary,
        "reference_counts": reference_counts,
        "by_date_type": by_date_type,
        "calendar_distribution": calendar_distribution,
        "year_by_decade": year_by_decade,
        "top_dates": top_dates,
    })


@bp.route("/<tree_id>/analytics/media", methods=["GET"])
def media_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/media

    GEDCOM media (gedcom_media_v2) for the tree: link counts, albums scoped to
    the tree, app tags on media, and ranked places, dates, individuals, families,
    and events by how many media links they have.

    Query param: top_n (default 10, max 40) for ranked lists and tag pie.
    """
    file_uuid = _get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return jsonify({"error": "Tree not found"}), 404

    top_n = min(int(request.args.get("top_n", 10)), 40)

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

    return jsonify({
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
    })


@bp.route("/<tree_id>/analytics/open-questions", methods=["GET"])
def open_questions_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/open-questions

    Open questions for the GEDCOM file (open_questions.file_uuid): totals,
    resolved vs unresolved, and entities ranked by how many question links
    they have (individual, media, family, event).

    Query param: top_n (default 10, max 40).
    """
    file_uuid = _get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return jsonify({"error": "Tree not found"}), 404

    top_n = min(int(request.args.get("top_n", 10)), 40)

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

    return jsonify({
        "tree_id": tree_id,
        "summary": summary,
        "top_individuals": top_individuals,
        "top_media": top_media,
        "top_families": top_families,
        "top_events": top_events,
    })


@bp.route("/<tree_id>/analytics/notes", methods=["GET"])
def notes_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/notes

    GEDCOM notes (gedcom_notes_v2): counts, link rows to individuals, families,
    events, and sources; top entities and notes by link volume.

    Query param: top_n (default 10, max 40).
    """
    file_uuid = _get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return jsonify({"error": "Tree not found"}), 404

    top_n = min(int(request.args.get("top_n", 10)), 40)

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

    return jsonify({
        "tree_id": tree_id,
        "summary": summary,
        "link_counts": link_counts,
        "top_notes": top_notes,
        "top_individuals": top_individuals,
        "top_families": top_families,
        "top_events": top_events,
        "top_sources": top_sources,
    })
