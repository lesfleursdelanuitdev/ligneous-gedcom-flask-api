"""Vital statistics, lifespans, decades, tree summary, occupations, family size."""
from __future__ import annotations

from typing import Any

from app.db import get_connection

from app.analytics.intents.utils import _clamp, _string

def _handle_individuals_age_at_death(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    op_key = _string(params.get("op") or params.get("operator"), default="lt").lower()
    sym_map = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">=", "eq": "="}
    sql_cmp = sym_map.get(op_key)
    age_compare = _clamp(params.get("age"), default=70, lo=0, hi=130)
    limit = _clamp(params.get("limit"), default=max_rows, lo=1, hi=max_rows)
    if sql_cmp is None:
        return {"matches": [], "operator": op_key, "note": "Invalid op; use lt, lte, gt, gte, or eq"}

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, xref, full_name, age_at_death, birth_year, death_year,
                       death_place_display, birth_place_display
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s
                  AND age_at_death IS NOT NULL
                  AND age_at_death {sql_cmp} %s
                ORDER BY age_at_death, primary_surname_lower NULLS LAST, full_name
                LIMIT %s
                """,
                (file_uuid, age_compare, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {
        "operator": op_key,
        "age": age_compare,
        "matches": rows,
        "limit": limit,
    }


def _handle_individuals_lifespan_years(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    min_years = _clamp(params.get("min_years"), default=0, lo=0, hi=130)
    max_years = _clamp(params.get("max_years"), default=130, lo=0, hi=130)
    if min_years > max_years:
        min_years, max_years = max_years, min_years
    limit = _clamp(params.get("limit"), default=max_rows, lo=1, hi=max_rows)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, xref, full_name,
                       birth_year, death_year,
                       CASE
                         WHEN birth_year IS NOT NULL AND death_year IS NOT NULL THEN death_year - birth_year
                         ELSE age_at_death
                       END AS lifespan_estimate,
                       age_at_death
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s
                  AND COALESCE(
                    CASE WHEN birth_year IS NOT NULL AND death_year IS NOT NULL THEN death_year - birth_year END,
                    age_at_death
                  ) IS NOT NULL
                  AND COALESCE(
                    CASE WHEN birth_year IS NOT NULL AND death_year IS NOT NULL THEN death_year - birth_year END,
                    age_at_death
                  ) BETWEEN %s AND %s
                ORDER BY lifespan_estimate DESC NULLS LAST, primary_surname_lower NULLS LAST, full_name
                LIMIT %s
                """,
                (file_uuid, min_years, max_years, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"min_years": min_years, "max_years": max_years, "matches": rows, "limit": limit}
def _handle_tree_summary(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM gedcom_individuals_v2 WHERE file_uuid = %s) AS individuals,
                    (SELECT COUNT(*) FROM gedcom_given_names_v2 WHERE file_uuid = %s) AS given_names,
                    (SELECT COUNT(*) FROM gedcom_surnames_v2 WHERE file_uuid = %s) AS surnames
                """,
                (file_uuid, file_uuid, file_uuid),
            )
            summary = dict(cur.fetchone() or {})
    return {"summary": summary}
def _handle_born_in_decade(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    raw = params.get("decade")
    if raw is None or raw == "":
        return {
            "matches": [],
            "decade": None,
            "note": "Missing or invalid decade parameter",
        }
    try:
        yr = int(raw)
    except (TypeError, ValueError):
        return {
            "matches": [],
            "decade": None,
            "note": "Missing or invalid decade parameter",
        }
    decade = yr - (yr % 10)
    limit = _clamp(params.get("limit"), default=max_rows, lo=1, hi=max_rows)
    end_y = decade + 10
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, xref, full_name, birth_year, birth_place_display, sex
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s
                  AND birth_year IS NOT NULL
                  AND birth_year >= %s AND birth_year < %s
                ORDER BY birth_year, primary_surname_lower NULLS LAST, full_name
                LIMIT %s
                """,
                (file_uuid, decade, end_y, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"decade": decade, "matches": rows, "limit": limit, "note": None}


def _handle_lifespan_stats(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    _ = params
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    AVG(age_at_death)::numeric(5,1) AS avg_age,
                    MIN(age_at_death)::int AS min_age,
                    MAX(age_at_death)::int AS max_age,
                    COUNT(*)::bigint AS cnt
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s
                  AND age_at_death IS NOT NULL
                  AND age_at_death >= 0
                  AND age_at_death <= 120
                """,
                (file_uuid,),
            )
            row = dict(cur.fetchone() or {})

    n = int(row.get("cnt") or 0)
    avg_age = row.get("avg_age")
    if avg_age is not None:
        try:
            avg_age = float(avg_age)
        except (TypeError, ValueError):
            avg_age = None
    summary = {
        "avg_age": avg_age,
        "min_age": row.get("min_age"),
        "max_age": row.get("max_age"),
        "count": n,
    }
    out: dict[str, Any] = {"summary": summary, "note": None}
    if not n:
        out["note"] = "No individuals with age_at_death in range 0–120 for this tree."
    _ = max_rows
    return out


def _handle_longest_lived(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    limit = _clamp(params.get("limit"), default=min(10, max_rows), lo=1, hi=min(50, max_rows))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, xref, full_name, birth_year, death_year, age_at_death
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s
                  AND age_at_death IS NOT NULL
                  AND age_at_death >= 0
                  AND age_at_death <= 120
                ORDER BY age_at_death DESC, full_name ASC
                LIMIT %s
                """,
                (file_uuid, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"matches": rows, "limit": limit}


def _handle_largest_families(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    limit = _clamp(params.get("limit"), default=min(10, max_rows), lo=1, hi=min(50, max_rows))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, xref, husband_xref, wife_xref, marriage_year, children_count
                FROM gedcom_families_v2
                WHERE file_uuid = %s AND children_count > 0
                ORDER BY children_count DESC, xref ASC
                LIMIT %s
                """,
                (file_uuid, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"families": rows, "limit": limit}


def _handle_cause_of_death(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    limit = _clamp(params.get("limit"), default=min(15, max_rows), lo=1, hi=min(50, max_rows))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT TRIM(cause) AS cause, COUNT(*)::int AS count
                FROM gedcom_events_v2
                WHERE file_uuid = %s
                  AND event_type = 'DEAT'
                  AND cause IS NOT NULL
                  AND TRIM(cause) <> ''
                GROUP BY TRIM(cause)
                ORDER BY count DESC
                LIMIT %s
                """,
                (file_uuid, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]

    payload: dict[str, Any] = {"causes": rows, "limit": limit, "note": None}
    if not rows:
        payload["note"] = "No cause-of-death data recorded in this tree."
    return payload


def _handle_migration_places(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    limit = _clamp(params.get("limit"), default=min(15, max_rows), lo=1, hi=min(50, max_rows))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT TRIM(birth_country) AS country, COUNT(*)::int AS count
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s
                  AND birth_country IS NOT NULL
                  AND TRIM(birth_country) <> ''
                GROUP BY TRIM(birth_country)
                ORDER BY count DESC
                LIMIT %s
                """,
                (file_uuid, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"countries": rows, "limit": limit}


def _handle_surname_by_place(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    place = params.get("place")
    limit = _clamp(params.get("limit"), default=min(10, max_rows), lo=1, hi=min(50, max_rows))
    if not place or not str(place).strip():
        return {
            "surnames": [],
            "place": None,
            "limit": limit,
            "note": "Missing place parameter",
        }
    place_s = _string(place)
    needle = _ilike_pattern(place_s)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.surname AS surname, COUNT(DISTINCT ind.id)::int AS count
                FROM gedcom_individuals_v2 ind
                JOIN gedcom_individual_name_forms nf
                  ON nf.individual_id = ind.id AND nf.file_uuid = ind.file_uuid
                JOIN gedcom_name_form_surnames nfs
                  ON nfs.name_form_id = nf.id AND nfs.file_uuid = ind.file_uuid
                JOIN gedcom_surnames_v2 s ON s.id = nfs.surname_id AND s.file_uuid = ind.file_uuid
                WHERE ind.file_uuid = %s
                  AND (
                    ind.birth_place_display ILIKE %s ESCAPE '\\'
                    OR ind.birth_country ILIKE %s ESCAPE '\\'
                  )
                GROUP BY s.surname
                ORDER BY count DESC, s.surname ASC
                LIMIT %s
                """,
                (file_uuid, needle, needle, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"place": place_s, "surnames": rows, "limit": limit, "note": None}


def _handle_occupation_stats(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    limit = _clamp(params.get("limit"), default=min(15, max_rows), lo=1, hi=min(50, max_rows))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT occupation, COUNT(*)::int AS count
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s
                  AND occupation IS NOT NULL
                  AND TRIM(occupation) <> ''
                GROUP BY occupation
                ORDER BY count DESC
                LIMIT %s
                """,
                (file_uuid, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"occupations": rows, "limit": limit}
