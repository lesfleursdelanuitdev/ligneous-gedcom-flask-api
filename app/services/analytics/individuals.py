"""Individuals (persons): demographics, lifespans, geography, and family-role patterns.

Covers `gedcom_individuals_v2` aggregates plus junction-derived metrics such as
child-only vs spouse-only roles and association counts.
"""

from app.db import get_connection
from app.services.analytics.utils import get_file_uuid_for_tree


def get_individuals_statistics(
    tree_id: str, country_limit: int, top_n: int
) -> dict | None:
    """Aggregates from `gedcom_individuals_v2` and related junction tables."""
    file_uuid = get_file_uuid_for_tree(tree_id)
    if not file_uuid:
        return None
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

    return {
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
    }

