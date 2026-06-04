"""Structured record search intents (individuals, families, events, notes, sources, media)."""
from __future__ import annotations

from typing import Any

from app.db import get_connection

from app.analytics.intents.utils import _clamp, _ilike_pattern, _sex_code_from_param, _string

def _handle_search_individuals(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    limit = _clamp(params.get("limit"), default=max_rows, lo=1, hi=max_rows)
    clauses: list[str] = ["file_uuid = %s"]
    args: list[Any] = [file_uuid]

    gn = _string(params.get("given_name"))
    if gn:
        clauses.append("full_name_lower ILIKE %s ESCAPE '\\'")
        args.append(_ilike_pattern(gn))
    sn = _string(params.get("surname"))
    if sn:
        clauses.append("primary_surname_lower ILIKE %s ESCAPE '\\'")
        args.append(_ilike_pattern(sn))
    bp = _string(params.get("birth_place"))
    if bp:
        clauses.append("birth_place_display ILIKE %s ESCAPE '\\'")
        args.append(_ilike_pattern(bp))
    dp = _string(params.get("death_place"))
    if dp:
        clauses.append("death_place_display ILIKE %s ESCAPE '\\'")
        args.append(_ilike_pattern(dp))
    bd = params.get("birth_decade")
    if bd not in (None, ""):
        try:
            d0 = int(bd) - (int(bd) % 10)
            clauses.append("birth_year >= %s AND birth_year < %s")
            args.extend([d0, d0 + 10])
        except (TypeError, ValueError):
            pass
    dd = params.get("death_decade")
    if dd not in (None, ""):
        try:
            d0 = int(dd) - (int(dd) % 10)
            clauses.append("death_year >= %s AND death_year < %s")
            args.extend([d0, d0 + 10])
        except (TypeError, ValueError):
            pass
    sex_v = params.get("sex")
    code = _sex_code_from_param(sex_v)
    if code is not None:
        clauses.append("sex::text = %s")
        args.append(code)
    if "is_living" in params and params.get("is_living") is not None:
        clauses.append("is_living = %s")
        args.append(bool(params.get("is_living")))
    occ = _string(params.get("occupation"))
    if occ:
        clauses.append("occupation ILIKE %s ESCAPE '\\'")
        args.append(_ilike_pattern(occ))
    nat = _string(params.get("nationality"))
    if nat:
        clauses.append("nationality ILIKE %s ESCAPE '\\'")
        args.append(_ilike_pattern(nat))

    where_sql = " AND ".join(clauses)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, xref, full_name, sex, birth_year, birth_place_display,
                       death_year, death_place_display, age_at_death, occupation, is_living
                FROM gedcom_individuals_v2
                WHERE {where_sql}
                ORDER BY primary_surname_lower NULLS LAST, full_name
                LIMIT %s
                """,
                (*args, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"matches": rows, "limit": limit}


def _sex_code_from_param(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        u = value.strip().upper()
        return u if u in {"M", "F", "U", "X"} else None
    return None


def _handle_search_families(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    limit = _clamp(params.get("limit"), default=max_rows, lo=1, hi=max_rows)
    clauses: list[str] = ["file_uuid = %s"]
    args: list[Any] = [file_uuid]

    ps = _string(params.get("partner_surname"))
    if ps:
        clauses.append(
            "id IN ("
            "SELECT fs.family_id FROM gedcom_family_surnames_v2 fs "
            "JOIN gedcom_surnames_v2 s ON s.id = fs.surname_id AND s.file_uuid = fs.file_uuid "
            "WHERE fs.file_uuid = %s AND s.surname_lower ILIKE %s ESCAPE '\\'"
            ")"
        )
        args.extend([file_uuid, _ilike_pattern(ps)])
    mp = _string(params.get("marriage_place"))
    if mp:
        clauses.append("marriage_place_display ILIKE %s ESCAPE '\\'")
        args.append(_ilike_pattern(mp))
    md = params.get("marriage_decade")
    if md not in (None, ""):
        try:
            d0 = int(md) - (int(md) % 10)
            clauses.append("marriage_year IS NOT NULL AND marriage_year >= %s AND marriage_year < %s")
            args.extend([d0, d0 + 10])
        except (TypeError, ValueError):
            pass
    mc = params.get("min_children")
    if mc not in (None, ""):
        try:
            clauses.append("children_count >= %s")
            args.append(int(mc))
        except (TypeError, ValueError):
            pass
    if "is_divorced" in params and params.get("is_divorced") is not None:
        clauses.append("is_divorced = %s")
        args.append(bool(params.get("is_divorced")))

    where_sql = " AND ".join(clauses)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, xref, husband_xref, wife_xref, marriage_year, marriage_place_display,
                       is_divorced, children_count
                FROM gedcom_families_v2
                WHERE {where_sql}
                ORDER BY children_count DESC NULLS LAST, xref
                LIMIT %s
                """,
                (*args, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"matches": rows, "limit": limit}


def _handle_search_events(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    limit = _clamp(params.get("limit"), default=max_rows, lo=1, hi=max_rows)
    joins = (
        " LEFT JOIN gedcom_dates_v2 d ON d.id = ev.date_id AND d.file_uuid = ev.file_uuid"
        " LEFT JOIN gedcom_places_v2 p ON p.id = ev.place_id AND p.file_uuid = ev.file_uuid"
    )
    clauses = ["ev.file_uuid = %s"]
    args: list[Any] = [file_uuid]

    et = _string(params.get("event_type"))
    if et:
        clauses.append("ev.event_type ILIKE %s ESCAPE '\\'")
        args.append(_ilike_pattern(et))
    pl = _string(params.get("place"))
    if pl:
        clauses.append("p.original ILIKE %s ESCAPE '\\'")
        args.append(_ilike_pattern(pl))
    dec = params.get("decade")
    if dec not in (None, ""):
        try:
            d0 = int(dec) - (int(dec) % 10)
            clauses.append("d.year IS NOT NULL AND d.year >= %s AND d.year < %s")
            args.extend([d0, d0 + 10])
        except (TypeError, ValueError):
            pass
    cause = _string(params.get("cause"))
    if cause:
        clauses.append("ev.cause ILIKE %s ESCAPE '\\'")
        args.append(_ilike_pattern(cause))

    where_sql = " AND ".join(clauses)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ev.id, ev.event_type, ev.event_label, ev.cause, ev.value,
                       d.year AS event_year, d.original AS date_display, p.original AS place_display
                FROM gedcom_events_v2 ev
                {joins}
                WHERE {where_sql}
                ORDER BY ev.sort_order, ev.id
                LIMIT %s
                """,
                (*args, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"matches": rows, "limit": limit}


def _handle_search_notes(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    limit = _clamp(params.get("limit"), default=max_rows, lo=1, hi=max_rows)
    tx = _string(params.get("text"))
    if not tx:
        return {"matches": [], "note": "Missing text parameter", "limit": limit}
    needle = _ilike_pattern(tx)
    clauses = ["file_uuid = %s", "content ILIKE %s ESCAPE '\\'"]
    args: list[Any] = [file_uuid, needle]
    if "is_top_level" in params and params.get("is_top_level") is not None:
        clauses.append("is_top_level = %s")
        args.append(bool(params.get("is_top_level")))
    where_sql = " AND ".join(clauses)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, xref, LEFT(content, 300) AS snippet, is_top_level
                FROM gedcom_notes_v2
                WHERE {where_sql}
                ORDER BY id
                LIMIT %s
                """,
                (*args, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"matches": rows, "limit": limit, "note": None}


def _handle_search_sources(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    limit = _clamp(params.get("limit"), default=max_rows, lo=1, hi=max_rows)
    clauses = ["file_uuid = %s"]
    args: list[Any] = [file_uuid]
    for key, col in (
        ("title", "title"),
        ("author", "author"),
        ("text", "text"),
    ):
        v = _string(params.get(key))
        if v:
            clauses.append(f"{col} ILIKE %s ESCAPE '\\'")
            args.append(_ilike_pattern(v))
    where_sql = " AND ".join(clauses)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, xref, title, author, abbreviation, publication, repository_xref
                FROM gedcom_sources_v2
                WHERE {where_sql}
                ORDER BY title NULLS LAST, xref
                LIMIT %s
                """,
                (*args, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"matches": rows, "limit": limit}


def _handle_search_media(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    limit = _clamp(params.get("limit"), default=max_rows, lo=1, hi=max_rows)
    clauses = ["file_uuid = %s"]
    args: list[Any] = [file_uuid]
    for key, col in (("title", "title"), ("description", "description"), ("form", "form")):
        v = _string(params.get(key))
        if v:
            clauses.append(f"{col} ILIKE %s ESCAPE '\\'")
            args.append(_ilike_pattern(v))
    where_sql = " AND ".join(clauses)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, xref, file_ref, form, title, description
                FROM gedcom_media_v2
                WHERE {where_sql}
                ORDER BY title NULLS LAST, id
                LIMIT %s
                """,
                (*args, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"matches": rows, "limit": limit}
