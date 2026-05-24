"""Given names, surnames, and name-frequency analytics intents."""
from __future__ import annotations

from typing import Any

from app.db import get_connection

from app.analytics.intents.utils import _clamp, _string

def _handle_top_given_names(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    limit = _clamp(params.get("limit"), default=10, lo=1, hi=max_rows)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, given_name AS name, frequency
                FROM gedcom_given_names_v2
                WHERE file_uuid = %s
                ORDER BY frequency DESC, given_name ASC
                LIMIT %s
                """,
                (file_uuid, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"top_given_names": rows, "limit": limit}


def _handle_top_surnames(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    limit = _clamp(params.get("limit"), default=10, lo=1, hi=max_rows)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, surname AS name, frequency, soundex, metaphone
                FROM gedcom_surnames_v2
                WHERE file_uuid = %s
                ORDER BY frequency DESC, surname ASC
                LIMIT %s
                """,
                (file_uuid, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"top_surnames": rows, "limit": limit}


def _handle_given_name_lookup(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    needle = _string(params.get("name"))
    if not needle:
        return {"matches": [], "name": None, "note": "Missing name parameter"}
    limit = _clamp(params.get("limit"), default=20, lo=1, hi=max_rows)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, given_name AS name, frequency
                FROM gedcom_given_names_v2
                WHERE file_uuid = %s
                  AND given_name ILIKE %s
                ORDER BY frequency DESC, given_name ASC
                LIMIT %s
                """,
                (file_uuid, f"%{needle}%", limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"matches": rows, "name": needle, "limit": limit}


def _handle_surname_lookup(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    needle = _string(params.get("name"))
    if not needle:
        return {"matches": [], "name": None, "note": "Missing name parameter"}
    limit = _clamp(params.get("limit"), default=20, lo=1, hi=max_rows)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, surname AS name, frequency, soundex, metaphone
                FROM gedcom_surnames_v2
                WHERE file_uuid = %s
                  AND surname ILIKE %s
                ORDER BY frequency DESC, surname ASC
                LIMIT %s
                """,
                (file_uuid, f"%{needle}%", limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"matches": rows, "name": needle, "limit": limit}


def _handle_names_by_decade(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    """Top given-name popularity grouped by decade for the top-N names."""
    top_n = _clamp(params.get("top_names"), default=10, lo=1, hi=20)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH top_names AS (
                    SELECT id FROM gedcom_given_names_v2
                    WHERE file_uuid = %s
                    ORDER BY frequency DESC
                    LIMIT %s
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
                (file_uuid, top_n, file_uuid),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"by_decade": rows, "top_names": top_n}


def _handle_names_by_sex(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    sex = _string(params.get("sex"), default="M").upper()
    if sex not in {"M", "F"}:
        sex = "M"
    limit = _clamp(params.get("limit"), default=10, lo=1, hi=max_rows)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT gn.given_name AS name, gn.id,
                    COALESCE(SUM(CASE WHEN ind.sex::text = %s THEN 1 ELSE 0 END), 0)::int AS count
                FROM gedcom_given_names_v2 gn
                JOIN gedcom_name_form_given_names nfgn ON nfgn.given_name_id = gn.id
                JOIN gedcom_individual_name_forms nf ON nf.id = nfgn.name_form_id
                JOIN gedcom_individuals_v2 ind ON ind.id = nf.individual_id
                WHERE gn.file_uuid = %s
                GROUP BY gn.id, gn.given_name
                HAVING COALESCE(SUM(CASE WHEN ind.sex::text = %s THEN 1 ELSE 0 END), 0) > 0
                ORDER BY count DESC, gn.given_name ASC
                LIMIT %s
                """,
                (sex, file_uuid, sex, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"sex": sex, "names": rows, "limit": limit}


def _handle_surname_soundex_groups(
    file_uuid: str, params: dict[str, Any], max_rows: int
) -> dict[str, Any]:
    limit = _clamp(params.get("limit"), default=15, lo=1, hi=50)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT soundex,
                       COUNT(*) AS name_count,
                       SUM(frequency) AS total_frequency,
                       ARRAY_AGG(surname ORDER BY frequency DESC) AS surnames
                FROM gedcom_surnames_v2
                WHERE file_uuid = %s
                  AND soundex IS NOT NULL
                  AND soundex <> ''
                GROUP BY soundex
                HAVING COUNT(*) > 1
                ORDER BY total_frequency DESC
                LIMIT %s
                """,
                (file_uuid, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"soundex_groups": rows, "limit": limit}
