"""Place-linked and geography-oriented NL intents (localities, migration, vitals by place)."""
from __future__ import annotations

from typing import Any

from app.db import get_connection

from app.analytics.intents.utils import _clamp, _facet_locality, _ilike_pattern, _string

def _handle_individuals_by_locality(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    facet = _facet_locality(params.get("facet"))
    locality = _string(params.get("locality") or params.get("place"))
    if not locality:
        return {"matches": [], "facet": facet, "note": "Missing locality"}
    needle = _ilike_pattern(locality)
    sur_hint = _string(params.get("primary_surname_substring"))
    surname_needle = _ilike_pattern(sur_hint) if sur_hint else ""
    limit = _clamp(params.get("limit"), default=min(50, max_rows), lo=1, hi=max_rows)
    if facet == "burial":
        sur_clause = ""
        sur_args_sql: list[Any] = []
        if surname_needle:
            sur_clause = " AND COALESCE(i.primary_surname_lower, '') ILIKE %s ESCAPE '\\'"
            sur_args_sql.append(surname_needle)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT DISTINCT i.id, i.xref, i.full_name,
                           e.event_type, e.custom_type, e.event_label,
                           COALESCE(pl.original, pl.name, '') AS place_text
                    FROM gedcom_individual_events_v2 ie
                    JOIN gedcom_individuals_v2 i ON i.id = ie.individual_id AND i.file_uuid = ie.file_uuid
                    JOIN gedcom_events_v2 e ON e.id = ie.event_id AND e.file_uuid = ie.file_uuid
                    LEFT JOIN gedcom_places_v2 pl ON pl.id = e.place_id AND pl.file_uuid = e.file_uuid
                    WHERE ie.file_uuid = %s
                      {sur_clause}
                      AND (
                        e.event_type ILIKE '%BUR%'
                        OR COALESCE(e.custom_type, '') ILIKE '%BUR%'
                        OR COALESCE(e.event_label, '') ILIKE '%bur%'
                      )
                      AND (
                        pl.original ILIKE %s ESCAPE '\\'
                        OR COALESCE(pl.name, '') ILIKE %s ESCAPE '\\'
                        OR COALESCE(pl.country, '') ILIKE %s ESCAPE '\\'
                        OR COALESCE(pl.state, '') ILIKE %s ESCAPE '\\'
                      )
                    ORDER BY i.primary_surname_lower NULLS LAST, i.full_name
                    LIMIT %s
                    """,
                    (file_uuid, *sur_args_sql, needle, needle, needle, needle, limit),
                )
                rows = [dict(r) for r in cur.fetchall()]
        out = {"facet": facet, "locality": locality, "matches": rows, "limit": limit}
        if sur_hint:
            out["primary_surname_substring"] = sur_hint
        return out

    birth_cols = ("i.birth_place_display", "i.birth_country", "i.birth_country_lower")
    death_cols = ("i.death_place_display", "i.death_country", "i.death_country_lower")

    def clause_fragment(cols: tuple[str, ...]) -> tuple[str, list[Any]]:
        parts: list[str] = []
        frag_args: list[Any] = []
        for col in cols:
            parts.append(f"COALESCE({col}, '') ILIKE %s ESCAPE '\\'")
            frag_args.append(needle)
        return "(" + " OR ".join(parts) + ")", frag_args

    clauses_sql: list[str] = []
    args_tail: list[Any] = []
    if facet == "birth":
        sq, aq = clause_fragment(birth_cols)
        clauses_sql.append(sq)
        args_tail.extend(aq)
    elif facet == "death":
        sq, aq = clause_fragment(death_cols)
        clauses_sql.append(sq)
        args_tail.extend(aq)
    else:  # both
        bq, ba = clause_fragment(birth_cols)
        dq, da = clause_fragment(death_cols)
        clauses_sql.append(f"(({bq}) OR ({dq}))")
        args_tail.extend(ba + da)

    sql_where = clauses_sql[0]
    sur_clause = ""
    sur_extra: list[Any] = []
    if surname_needle:
        sur_clause = " AND COALESCE(i.primary_surname_lower, '') ILIKE %s ESCAPE '\\'"
        sur_extra.append(surname_needle)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT i.id, i.xref, i.full_name, i.sex,
                       i.birth_place_display, i.death_place_display,
                       i.birth_country, i.death_country, i.age_at_death,
                       i.birth_year, i.death_year
                FROM gedcom_individuals_v2 i
                WHERE i.file_uuid = %s AND ({sql_where}){sur_clause}
                ORDER BY i.primary_surname_lower NULLS LAST, i.full_name
                LIMIT %s
                """,
                (file_uuid, *args_tail, *sur_extra, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    out = {"facet": facet, "locality": locality, "matches": rows, "limit": limit}
    if sur_hint:
        out["primary_surname_substring"] = sur_hint
    return out


def _handle_marriages_by_place(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    locality = _string(params.get("locality") or params.get("place"))
    if not locality:
        return {"matches": [], "note": "Missing locality"}
    needle = _ilike_pattern(locality)
    limit = _clamp(params.get("limit"), default=min(40, max_rows), lo=1, hi=max_rows)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, xref, marriage_place_display, marriage_year, marriage_date_display,
                       husband_xref, wife_xref
                FROM gedcom_families_v2
                WHERE file_uuid = %s
                  AND marriage_place_display ILIKE %s ESCAPE '\\'
                ORDER BY marriage_year NULLS LAST, xref
                LIMIT %s
                """,
                (file_uuid, needle, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"locality": locality, "matches": rows, "limit": limit}


def _handle_individual_events_by_place(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    locality = _string(params.get("locality") or params.get("place"))
    if not locality:
        return {"matches": [], "note": "Missing locality"}
    needle = _ilike_pattern(locality)
    limit = _clamp(params.get("limit"), default=min(50, max_rows), lo=1, hi=max_rows)
    evt = _string(params.get("event_type_substring")).lower()
    evt_filter = ""
    extra_args: list[Any] = []
    if evt:
        evt_filter = " AND (LOWER(COALESCE(e.event_type,'')) LIKE %s OR LOWER(COALESCE(e.custom_type,'')) LIKE %s)"
        sub = _ilike_pattern(evt)[1:-1]
        pct = f"%{sub}%"
        extra_args.extend([pct, pct])
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ie.individual_id, i.xref, i.full_name,
                       e.event_type, e.custom_type, e.event_label,
                       COALESCE(pl.original, pl.name, '') AS place_text
                FROM gedcom_individual_events_v2 ie
                JOIN gedcom_individuals_v2 i ON i.id = ie.individual_id AND i.file_uuid = ie.file_uuid
                JOIN gedcom_events_v2 e ON e.id = ie.event_id AND e.file_uuid = ie.file_uuid
                LEFT JOIN gedcom_places_v2 pl ON pl.id = e.place_id AND pl.file_uuid = e.file_uuid
                WHERE ie.file_uuid = %s
                  AND (
                    pl.original ILIKE %s ESCAPE '\\'
                    OR COALESCE(pl.name, '') ILIKE %s ESCAPE '\\'
                    OR COALESCE(pl.country, '') ILIKE %s ESCAPE '\\'
                    OR COALESCE(pl.state, '') ILIKE %s ESCAPE '\\'
                  )
                  {evt_filter}
                ORDER BY i.primary_surname_lower NULLS LAST, i.full_name, e.event_type
                LIMIT %s
                """,
                (file_uuid, needle, needle, needle, needle, *extra_args, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"locality": locality, "matches": rows, "limit": limit, "event_type_substring": evt or None}
def _handle_born_in_place(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    place = params.get("place")
    limit = _clamp(params.get("limit"), default=min(20, max_rows), lo=1, hi=min(200, max_rows))
    if not place or not str(place).strip():
        return {
            "matches": [],
            "place": None,
            "note": "Missing place parameter",
        }
    place_s = _string(place)
    needle = _ilike_pattern(place_s)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, xref, full_name, birth_year, birth_place_display, death_year
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s AND birth_place_display ILIKE %s ESCAPE '\\'
                ORDER BY birth_year NULLS LAST, id
                LIMIT %s
                """,
                (file_uuid, needle, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"matches": rows, "place": place_s, "limit": limit, "note": None}


def _handle_died_in_place(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    place = params.get("place")
    limit = _clamp(params.get("limit"), default=min(20, max_rows), lo=1, hi=min(200, max_rows))
    if not place or not str(place).strip():
        return {
            "matches": [],
            "place": None,
            "note": "Missing place parameter",
        }
    place_s = _string(place)
    needle = _ilike_pattern(place_s)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, xref, full_name, birth_year, birth_place_display, death_year, death_place_display
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s AND death_place_display ILIKE %s ESCAPE '\\'
                ORDER BY death_year NULLS LAST, id
                LIMIT %s
                """,
                (file_uuid, needle, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"matches": rows, "place": place_s, "limit": limit, "note": None}


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
    limit = _clamp(params.get("limit"), default=min(20, max_rows), lo=1, hi=min(200, max_rows))
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
