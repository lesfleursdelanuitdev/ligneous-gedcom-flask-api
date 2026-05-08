"""Intent registry for natural-language search.

Every intent the LLM is allowed to select maps to a parameterized SQL template
executed by ``run_intent``. The LLM is never permitted to author SQL directly;
it can only emit ``{"intent": <name>, "params": {...}}`` against this registry.

Add new intents by extending ``INTENT_HANDLERS`` plus an entry in
``intent_catalog`` that documents what parameters the LLM may emit.
"""
from __future__ import annotations

from typing import Any, Callable, Union

import networkx as nx

from app.db import get_connection
from app.services.pedigree_graph import analyze_relationship_between, load_pedigree_parent_child_graph


INTENT_TOP_GIVEN_NAMES = "top_given_names"
INTENT_TOP_SURNAMES = "top_surnames"
INTENT_GIVEN_NAME_LOOKUP = "given_name_lookup"
INTENT_SURNAME_LOOKUP = "surname_lookup"
INTENT_NAMES_BY_DECADE = "names_by_decade"
INTENT_NAMES_BY_SEX = "names_by_sex"
INTENT_SURNAME_SOUNDEX_GROUPS = "surname_soundex_groups"
INTENT_TREE_SUMMARY = "tree_summary"
INTENT_UNSUPPORTED = "unsupported"
# Geography, vitals, events, lineage
INTENT_INDIVIDUALS_BY_LOCALITY = "individuals_by_locality"
INTENT_MARRIAGES_BY_PLACE = "marriages_by_place"
INTENT_INDIVIDUAL_EVENTS_BY_PLACE = "individual_events_by_place"
INTENT_INDIVIDUALS_AGE_AT_DEATH = "individuals_age_at_death"
INTENT_INDIVIDUALS_LIFESPAN_YEARS = "individuals_lifespan_years"
INTENT_INDIVIDUAL_ANCESTORS = "individual_ancestors"
INTENT_INDIVIDUAL_DESCENDANTS = "individual_descendants"
INTENT_INDIVIDUAL_COUSINS = "individual_cousins"
INTENT_RELATIONSHIP_BETWEEN = "relationship_between"
# Analytics (GEDCOM aggregates & place-linked rows)
INTENT_BORN_IN_PLACE = "born_in_place"
INTENT_DIED_IN_PLACE = "died_in_place"
INTENT_BORN_IN_DECADE = "born_in_decade"
INTENT_LIFESPAN_STATS = "lifespan_stats"
INTENT_LONGEST_LIVED = "longest_lived"
INTENT_LARGEST_FAMILIES = "largest_families"
INTENT_CAUSE_OF_DEATH = "cause_of_death"
INTENT_MIGRATION_PLACES = "migration_places"
INTENT_SURNAME_BY_PLACE = "surname_by_place"
INTENT_OCCUPATION_STATS = "occupation_stats"
INTENT_SEARCH_INDIVIDUALS = "search_individuals"
INTENT_SEARCH_FAMILIES = "search_families"
INTENT_SEARCH_EVENTS = "search_events"
INTENT_SEARCH_NOTES = "search_notes"
INTENT_SEARCH_SOURCES = "search_sources"
INTENT_SEARCH_MEDIA = "search_media"

SEARCH_INTENT_NAMES = frozenset(
    {
        INTENT_SEARCH_INDIVIDUALS,
        INTENT_SEARCH_FAMILIES,
        INTENT_SEARCH_EVENTS,
        INTENT_SEARCH_NOTES,
        INTENT_SEARCH_SOURCES,
        INTENT_SEARCH_MEDIA,
    }
)


def _clamp(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _string(value: Any, default: str = "") -> str:
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default


def _ilike_pattern(fragment: str, max_chars: int = 200) -> str:
    """Wrap fragment for ILIKE with wildcards; escape LIKE metachars (\\, %, _)."""
    s = _string(fragment, default="")[:max_chars]
    if not s:
        return ""
    escaped = s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _facet_locality(raw: Any) -> str:
    facet = _string(raw, default="birth").lower()
    if facet not in {"birth", "death", "both", "burial"}:
        return "birth"
    return facet


def _resolve_anchor_individual_id(
    cur: Any, file_uuid: str, params: dict[str, Any]
) -> tuple[Any, Union[str, dict[str, Any], None]]:
    xref = _string(params.get("xref"))
    name = _string(params.get("name"))
    if xref:
        cur.execute(
            """
            SELECT id, xref, full_name
            FROM gedcom_individuals_v2
            WHERE file_uuid = %s AND xref = %s
            LIMIT 2
            """,
            (file_uuid, xref),
        )
        rows = cur.fetchall()
        if not rows:
            return None, f"No individual with xref {xref!r} in this tree."
        return rows[0]["id"], None
    if name:
        needle = _ilike_pattern(name, max_chars=200)
        if not needle:
            return None, "Provide a non-empty anchor name."
        cur.execute(
            """
            SELECT id, xref, full_name
            FROM gedcom_individuals_v2
            WHERE file_uuid = %s AND full_name ILIKE %s ESCAPE '\\'
            ORDER BY xref ASC
            LIMIT 5
            """,
            (file_uuid, needle),
        )
        rows = cur.fetchall()
        if not rows:
            return None, f"No individual matching name {name!r}."
        if len(rows) > 1:
            preview = [{"xref": r["xref"], "full_name": r["full_name"]} for r in rows[:5]]
            return None, {"ambiguous_matches": preview, "message": "Name matches multiple people; refine xref or full name."}
        return rows[0]["id"], None
    return None, "Provide xref or name for anchor individual."


def _resolve_prefixed_anchor(
    cur: Any, file_uuid: str, params: dict[str, Any], prefix: str
) -> tuple[Any, Union[str, dict[str, Any], None]]:
    xr = _string(params.get(f"{prefix}_xref"))
    nm = _string(params.get(f"{prefix}_name"))
    snap: dict[str, Any] = {}
    if xr:
        snap["xref"] = xr
    if nm:
        snap["name"] = nm
    if not snap:
        return None, f"Provide {prefix}_xref or {prefix}_name."
    return _resolve_anchor_individual_id(cur, file_uuid, snap)


def _hydrate_pedigree_id_chain(
    cur: Any, file_uuid: str, ids: list[str]
) -> list[dict[str, Any]]:
    if not ids:
        return []
    uniq: list[str] = []
    seen: set[str] = set()
    for u in ids:
        uu = str(u)
        if uu not in seen:
            seen.add(uu)
            uniq.append(uu)
    cur.execute(
        """
        SELECT id::text AS id, xref, full_name, birth_year, death_year
        FROM gedcom_individuals_v2
        WHERE file_uuid = %s AND id IN %s
        """,
        (file_uuid, tuple(uniq)),
    )
    by_id = {r["id"]: dict(r) for r in cur.fetchall()}
    return [by_id[u] for u in uniq if u in by_id]


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


def _handle_individuals_age_at_death(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    op_key = _string(params.get("op") or params.get("operator"), default="lt").lower()
    sym_map = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">=", "eq": "="}
    sql_cmp = sym_map.get(op_key)
    age_compare = _clamp(params.get("age"), default=70, lo=0, hi=130)
    limit = _clamp(params.get("limit"), default=min(75, max_rows), lo=1, hi=max_rows)
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
    limit = _clamp(params.get("limit"), default=min(75, max_rows), lo=1, hi=max_rows)
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


def _lineage_anchor_error_payload(
    err: Union[str, dict[str, Any], None], limit: int, extra: dict[str, Any]
) -> dict[str, Any]:
    out = {"matches": [], "limit": limit, **extra}
    if isinstance(err, dict):
        out["ambiguous_anchor"] = err
    elif isinstance(err, str):
        out["note"] = err
    return out


def _relationship_anchor_error_payload(
    err: Union[str, dict[str, Any], None],
    *,
    role: str,
    source_id: str | None,
    target_id: str | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "category": None,
        "role": role,
        "source_id": source_id,
        "target_id": target_id,
        "graph": None,
    }
    if isinstance(err, dict):
        out["ambiguous_anchor"] = err
    elif isinstance(err, str):
        out["note"] = err
    return out


def _handle_individual_ancestors(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    gen_cap = _clamp(params.get("max_generations"), default=15, lo=1, hi=40)
    limit = _clamp(params.get("limit"), default=min(100, max_rows), lo=1, hi=max_rows)
    with get_connection() as conn:
        with conn.cursor() as cur:
            anchor_id, err = _resolve_anchor_individual_id(cur, file_uuid, params)
            if anchor_id is None:
                return _lineage_anchor_error_payload(err, limit, {"max_generations": gen_cap})

            cur.execute(
                """
                WITH RECURSIVE walk AS (
                  SELECT pc.parent_id AS ancestor_id, 1 AS generation
                  FROM gedcom_parent_child_v2 pc
                  WHERE pc.file_uuid = %s AND pc.child_id = %s AND pc.parent_id IS NOT NULL
                  UNION ALL
                  SELECT pc.parent_id, w.generation + 1
                  FROM gedcom_parent_child_v2 pc
                  INNER JOIN walk w ON pc.child_id = w.ancestor_id AND pc.file_uuid = %s
                  WHERE pc.parent_id IS NOT NULL AND w.generation < %s
                )
                SELECT MIN(w.generation) AS generation,
                       i.id, i.xref, i.full_name, i.birth_year, i.death_year
                FROM walk w
                JOIN gedcom_individuals_v2 i ON i.id = w.ancestor_id AND i.file_uuid = %s
                GROUP BY i.id, i.xref, i.full_name, i.birth_year, i.death_year
                ORDER BY generation ASC, full_name ASC
                LIMIT %s
                """,
                (file_uuid, anchor_id, file_uuid, gen_cap, file_uuid, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {
        "anchor_id": str(anchor_id),
        "max_generations": gen_cap,
        "matches": rows,
        "limit": limit,
    }


def _handle_individual_descendants(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    gen_cap = _clamp(params.get("max_generations"), default=15, lo=1, hi=40)
    limit = _clamp(params.get("limit"), default=min(100, max_rows), lo=1, hi=max_rows)
    with get_connection() as conn:
        with conn.cursor() as cur:
            anchor_id, err = _resolve_anchor_individual_id(cur, file_uuid, params)
            if anchor_id is None:
                return _lineage_anchor_error_payload(err, limit, {"max_generations": gen_cap})

            cur.execute(
                """
                WITH RECURSIVE walk AS (
                  SELECT pc.child_id AS descendant_id, 1 AS generation
                  FROM gedcom_parent_child_v2 pc
                  WHERE pc.file_uuid = %s AND pc.parent_id = %s AND pc.child_id IS NOT NULL
                  UNION ALL
                  SELECT pc.child_id, w.generation + 1
                  FROM gedcom_parent_child_v2 pc
                  INNER JOIN walk w ON pc.parent_id = w.descendant_id AND pc.file_uuid = %s
                  WHERE pc.child_id IS NOT NULL AND w.generation < %s
                )
                SELECT MIN(w.generation) AS generation,
                       i.id, i.xref, i.full_name, i.birth_year, i.death_year
                FROM walk w
                JOIN gedcom_individuals_v2 i ON i.id = w.descendant_id AND i.file_uuid = %s
                GROUP BY i.id, i.xref, i.full_name, i.birth_year, i.death_year
                ORDER BY generation ASC, full_name ASC
                LIMIT %s
                """,
                (file_uuid, anchor_id, file_uuid, gen_cap, file_uuid, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {
        "anchor_id": str(anchor_id),
        "max_generations": gen_cap,
        "matches": rows,
        "limit": limit,
    }


def _handle_individual_cousins(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    limit = _clamp(params.get("limit"), default=min(100, max_rows), lo=1, hi=max_rows)
    with get_connection() as conn:
        with conn.cursor() as cur:
            anchor_id, err = _resolve_anchor_individual_id(cur, file_uuid, params)
            if anchor_id is None:
                return _lineage_anchor_error_payload(err, limit, {"degree": "first"})

            cur.execute(
                """
                WITH anchor AS (
                  SELECT %s::uuid AS aid
                ),
                parents AS (
                  SELECT DISTINCT parent_id
                  FROM gedcom_parent_child_v2
                  WHERE file_uuid = %s
                    AND child_id = (SELECT aid FROM anchor)
                    AND parent_id IS NOT NULL
                ),
                parent_siblings AS (
                  SELECT DISTINCT pc2.child_id AS psid
                  FROM gedcom_parent_child_v2 pc1
                  JOIN gedcom_parent_child_v2 pc2 ON pc1.parent_id = pc2.parent_id
                    AND pc2.child_id <> pc1.child_id
                    AND pc1.file_uuid = pc2.file_uuid
                  WHERE pc1.file_uuid = %s
                    AND pc1.child_id IN (SELECT parent_id FROM parents)
                ),
                sibling_ids AS (
                  SELECT DISTINCT pc2.child_id AS sid
                  FROM gedcom_parent_child_v2 pc1
                  JOIN gedcom_parent_child_v2 pc2 ON pc1.parent_id = pc2.parent_id
                    AND pc2.child_id <> pc1.child_id
                    AND pc1.file_uuid = pc2.file_uuid
                  WHERE pc1.file_uuid = %s
                    AND pc2.file_uuid = %s
                    AND pc1.child_id = (SELECT aid FROM anchor)
                ),
                cousin_ids AS (
                  SELECT DISTINCT pc.child_id AS cid
                  FROM gedcom_parent_child_v2 pc
                  WHERE pc.file_uuid = %s
                    AND pc.parent_id IN (SELECT psid FROM parent_siblings)
                )
                SELECT i.id, i.xref, i.full_name, i.birth_year, i.death_year
                FROM gedcom_individuals_v2 i
                WHERE i.file_uuid = %s
                  AND i.id IN (SELECT cid FROM cousin_ids)
                  AND i.id <> (SELECT aid FROM anchor)
                  AND NOT EXISTS (
                    SELECT 1 FROM sibling_ids s WHERE s.sid = i.id
                  )
                ORDER BY primary_surname_lower NULLS LAST, full_name ASC
                LIMIT %s
                """,
                (anchor_id, file_uuid, file_uuid, file_uuid, file_uuid, file_uuid, file_uuid, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"anchor_id": str(anchor_id), "degree": "first", "matches": rows, "limit": limit}


def _handle_relationship_between(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    _ = max_rows
    with get_connection() as conn:
        with conn.cursor() as cur:
            sid, err_s = _resolve_prefixed_anchor(cur, file_uuid, params, "source")
            if sid is None:
                return _relationship_anchor_error_payload(err_s, role="source", source_id=None, target_id=None)
            tid, err_t = _resolve_prefixed_anchor(cur, file_uuid, params, "target")
            if tid is None:
                return _relationship_anchor_error_payload(
                    err_t, role="target", source_id=str(sid), target_id=None
                )

            sid_s, tid_s = str(sid), str(tid)
            G = load_pedigree_parent_child_graph(file_uuid)
            analysis = analyze_relationship_between(G, sid_s, tid_s)

            path_ids_s = list(analysis.get("path_lca_to_source") or [])
            path_ids_t = list(analysis.get("path_lca_to_target") or [])
            raw_s = _hydrate_pedigree_id_chain(cur, file_uuid, path_ids_s)
            raw_t = _hydrate_pedigree_id_chain(cur, file_uuid, path_ids_t)

            out: dict[str, Any] = {
                "source_id": analysis.get("source_id"),
                "target_id": analysis.get("target_id"),
                "category": analysis.get("category"),
                "lowest_common_ancestor_id": analysis.get("lowest_common_ancestor_id"),
                "path_lca_to_source": raw_s,
                "path_lca_to_target": raw_t,
                "graph": {
                    "node_count": G.number_of_nodes(),
                    "edge_count": G.number_of_edges(),
                    "dag": bool(nx.is_directed_acyclic_graph(G)),
                },
            }
            if analysis.get("degrees_from_lca"):
                out["degrees_from_lca"] = analysis["degrees_from_lca"]
            if analysis.get("notes"):
                out["notes"] = analysis["notes"]
            return out


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


def _handle_search_individuals(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    limit = _clamp(params.get("limit"), default=min(20, max_rows), lo=1, hi=min(200, max_rows))
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
    limit = _clamp(params.get("limit"), default=min(20, max_rows), lo=1, hi=min(200, max_rows))
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
    limit = _clamp(params.get("limit"), default=min(20, max_rows), lo=1, hi=min(200, max_rows))
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
    limit = _clamp(params.get("limit"), default=min(20, max_rows), lo=1, hi=min(200, max_rows))
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
    limit = _clamp(params.get("limit"), default=min(20, max_rows), lo=1, hi=min(200, max_rows))
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
    limit = _clamp(params.get("limit"), default=min(20, max_rows), lo=1, hi=min(200, max_rows))
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


def _handle_unsupported(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    return {
        "supported_intents": list(intent_catalog().keys()),
        "note": _string(
            params.get("reason"),
            default="Query was not recognized; try rephrasing or pick a supported intent.",
        ),
    }


IntentHandler = Callable[[str, dict[str, Any], int], dict[str, Any]]


INTENT_HANDLERS: dict[str, IntentHandler] = {
    INTENT_TOP_GIVEN_NAMES: _handle_top_given_names,
    INTENT_TOP_SURNAMES: _handle_top_surnames,
    INTENT_GIVEN_NAME_LOOKUP: _handle_given_name_lookup,
    INTENT_SURNAME_LOOKUP: _handle_surname_lookup,
    INTENT_NAMES_BY_DECADE: _handle_names_by_decade,
    INTENT_NAMES_BY_SEX: _handle_names_by_sex,
    INTENT_SURNAME_SOUNDEX_GROUPS: _handle_surname_soundex_groups,
    INTENT_TREE_SUMMARY: _handle_tree_summary,
    INTENT_INDIVIDUALS_BY_LOCALITY: _handle_individuals_by_locality,
    INTENT_MARRIAGES_BY_PLACE: _handle_marriages_by_place,
    INTENT_INDIVIDUAL_EVENTS_BY_PLACE: _handle_individual_events_by_place,
    INTENT_INDIVIDUALS_AGE_AT_DEATH: _handle_individuals_age_at_death,
    INTENT_INDIVIDUALS_LIFESPAN_YEARS: _handle_individuals_lifespan_years,
    INTENT_INDIVIDUAL_ANCESTORS: _handle_individual_ancestors,
    INTENT_INDIVIDUAL_DESCENDANTS: _handle_individual_descendants,
    INTENT_INDIVIDUAL_COUSINS: _handle_individual_cousins,
    INTENT_RELATIONSHIP_BETWEEN: _handle_relationship_between,
    INTENT_BORN_IN_PLACE: _handle_born_in_place,
    INTENT_DIED_IN_PLACE: _handle_died_in_place,
    INTENT_BORN_IN_DECADE: _handle_born_in_decade,
    INTENT_LIFESPAN_STATS: _handle_lifespan_stats,
    INTENT_LONGEST_LIVED: _handle_longest_lived,
    INTENT_LARGEST_FAMILIES: _handle_largest_families,
    INTENT_CAUSE_OF_DEATH: _handle_cause_of_death,
    INTENT_MIGRATION_PLACES: _handle_migration_places,
    INTENT_SURNAME_BY_PLACE: _handle_surname_by_place,
    INTENT_OCCUPATION_STATS: _handle_occupation_stats,
    INTENT_SEARCH_INDIVIDUALS: _handle_search_individuals,
    INTENT_SEARCH_FAMILIES: _handle_search_families,
    INTENT_SEARCH_EVENTS: _handle_search_events,
    INTENT_SEARCH_NOTES: _handle_search_notes,
    INTENT_SEARCH_SOURCES: _handle_search_sources,
    INTENT_SEARCH_MEDIA: _handle_search_media,
    INTENT_UNSUPPORTED: _handle_unsupported,
}


def intent_catalog() -> dict[str, dict[str, Any]]:
    """Documented intent contract used to build the LLM system prompt and UI hints."""
    return {
        INTENT_TOP_GIVEN_NAMES: {
            "description": "Most common given (first) names in the tree.",
            "params": {"limit": "int (1-200, default 10)"},
            "examples": ["What are the most common first names?", "top 20 given names"],
        },
        INTENT_TOP_SURNAMES: {
            "description": "Most common surnames in the tree.",
            "params": {"limit": "int (1-200, default 10)"},
            "examples": ["Most popular surnames", "top 25 last names"],
        },
        INTENT_GIVEN_NAME_LOOKUP: {
            "description": "Find given names matching a substring (e.g. 'Maria').",
            "params": {"name": "string (required)", "limit": "int (1-200, default 20)"},
            "examples": ["how many people are named Maria", "given names containing Jose"],
        },
        INTENT_SURNAME_LOOKUP: {
            "description": "Find surnames matching a substring (e.g. 'Gonsalves').",
            "params": {"name": "string (required)", "limit": "int (1-200, default 20)"},
            "examples": ["surnames like Gonsalves", "search for last name Silva"],
        },
        INTENT_NAMES_BY_DECADE: {
            "description": "Top given-name popularity grouped by birth decade.",
            "params": {"top_names": "int (1-20, default 10)"},
            "examples": ["how have first names changed over time?", "names by decade"],
        },
        INTENT_NAMES_BY_SEX: {
            "description": "Top given names restricted to one sex (M or F).",
            "params": {"sex": "'M' or 'F' (default 'M')", "limit": "int (1-200, default 10)"},
            "examples": ["most common male first names", "popular female names"],
        },
        INTENT_SURNAME_SOUNDEX_GROUPS: {
            "description": "Phonetic surname clusters via Soundex (spelling variants).",
            "params": {"limit": "int (1-50, default 15)"},
            "examples": ["surname spelling variants", "phonetically similar last names"],
        },
        INTENT_TREE_SUMMARY: {
            "description": "High-level counts: individuals, unique given names, unique surnames.",
            "params": {},
            "examples": ["how big is the tree?", "tree overview"],
        },
        INTENT_INDIVIDUALS_BY_LOCALITY: {
            "description": "Individuals whose birth/death locality text matches (country, county, "
            "city string on individual rows); facet 'burial' scans BUR-type events.",
            "params": {
                "locality": "string (substring, required)",
                "facet": "birth | death | both | burial (default birth)",
                "primary_surname_substring": "optional filter on primary_surname_lower",
                "limit": "int (1-200)",
            },
            "examples": ["Who was born in Guyana?", "Who died in London?", "Buried in Toronto cemetery"],
        },
        INTENT_MARRIAGES_BY_PLACE: {
            "description": "Families whose marriage_place_display matches a locality substring.",
            "params": {"locality": "string (required)", "limit": "int"},
            "examples": ["Marriages in Toronto, Canada"],
        },
        INTENT_INDIVIDUAL_EVENTS_BY_PLACE: {
            "description": "Individual events tied to gedcom_events_v2 rows whose gedcom Places match.",
            "params": {
                "locality": "string (required)",
                "event_type_substring": "optional filter on event_type/custom_type",
                "limit": "int",
            },
            "examples": ["Baptisms in Lisbon", "Any event recorded in São Paulo"],
        },
        INTENT_INDIVIDUALS_AGE_AT_DEATH: {
            "description": "Individuals with known age_at_death compared to threshold.",
            "params": {
                "op": "lt | lte | gt | gte | eq",
                "age": "integer years (0–130)",
                "limit": "int",
            },
            "examples": ["Who died before age 70?"],
        },
        INTENT_INDIVIDUALS_LIFESPAN_YEARS: {
            "description": "Individuals whose inferred lifespan-years fall in a numeric band "
            "(prefers birth_year−death_year, else falls back to age_at_death).",
            "params": {"min_years": "int", "max_years": "int", "limit": "int"},
            "examples": ["People who lived between 80 and 90 years"],
        },
        INTENT_INDIVIDUAL_ANCESTORS: {
            "description": "Recursive ancestors via gedcom_parent_child_v2.",
            "params": {
                "xref": "GEDCOM xref (preferred)",
                "name": "full_name substring fallback (single fuzzy match)",
                "max_generations": "cap",
                "limit": "max rows returned",
            },
            "examples": ["Ancestors of @I123@"],
        },
        INTENT_INDIVIDUAL_DESCENDANTS: {
            "description": "Recursive descendants down parent→child edges.",
            "params": {
                "xref": "GEDCOM xref (preferred)",
                "name": "full_name substring fallback",
                "max_generations": "cap",
                "limit": "max rows returned",
            },
            "examples": ["All descendants of John Smith Sr."],
        },
        INTENT_INDIVIDUAL_COUSINS: {
            "description": "First cousins: children of parents' siblings of the anchor (pedigree graph).",
            "params": {
                "xref": "GEDCOM xref (preferred)",
                "name": "full_name substring fallback",
                "limit": "max rows returned",
            },
            "examples": ["First cousins of Mary Jones"],
        },
        INTENT_RELATIONSHIP_BETWEEN: {
            "description": "NetworkX shortest-path relationship between two people using gedcom_parent_child_v2 "
            "(ancestor/descendant, collateral via lowest common ancestor, or unrelated subgraphs).",
            "params": {
                "source_xref": "optional if source_name set",
                "source_name": "full_name substring (single fuzzy match)",
                "target_xref": "optional if target_name set",
                "target_name": "full_name substring (single fuzzy match)",
            },
            "examples": [
                "Relationship between @I1@ and @I2@",
                "How are Anne Smith and John Brown related?",
            ],
        },
        INTENT_BORN_IN_PLACE: {
            "description": "Individuals whose birth_place_display matches a place substring.",
            "params": {"place": "string (required, ILIKE %place%)", "limit": "int (default 20, max 200)"},
            "examples": ["Who was born in Guyana?", "people born in Trinidad"],
        },
        INTENT_DIED_IN_PLACE: {
            "description": "Individuals whose death_place_display matches a place substring.",
            "params": {"place": "string (required)", "limit": "int (default 20, max 200)"},
            "examples": ["Who died in Canada?", "deaths in Georgetown"],
        },
        INTENT_BORN_IN_DECADE: {
            "description": "Individuals with birth_year inside [decade, decade+10).",
            "params": {"decade": "int (required, e.g. 1880)", "limit": "int (default 20, max 200)"},
            "examples": ["people born in the 1880s"],
        },
        INTENT_LIFESPAN_STATS: {
            "description": "Aggregate avg/min/max/count of age_at_death (0–120) on gedcom_individuals_v2.",
            "params": {},
            "examples": ["average lifespan", "life expectancy at death"],
        },
        INTENT_LONGEST_LIVED: {
            "description": "Individuals ordered by age_at_death descending (non-null, 0–120).",
            "params": {"limit": "int default 10, max 50"},
            "examples": ["who lived the longest", "oldest people in the tree"],
        },
        INTENT_LARGEST_FAMILIES: {
            "description": "Families with children_count > 0, ordered by children_count descending (xrefs only).",
            "params": {"limit": "int default 10, max 50"},
            "examples": ["biggest families", "most children"],
        },
        INTENT_CAUSE_OF_DEATH: {
            "description": "Top causes from gedcom_events_v2 rows with event_type = DEAT and non-empty cause.",
            "params": {"limit": "int default 15, max 50"},
            "examples": ["common causes of death", "what did people die of"],
        },
        INTENT_MIGRATION_PLACES: {
            "description": "Top birth_country values on individuals (non-empty).",
            "params": {"limit": "int default 15, max 50"},
            "examples": ["where did people come from", "migration origins"],
        },
        INTENT_SURNAME_BY_PLACE: {
            "description": "Top surnames for individuals whose birth place or birth country matches a needle.",
            "params": {"place": "string (required)", "limit": "int default 10, max 50"},
            "examples": ["surnames common in Guyana"],
        },
        INTENT_OCCUPATION_STATS: {
            "description": "Top occupation strings on gedcom_individuals_v2 (non-empty).",
            "params": {"limit": "int default 15, max 50"},
            "examples": ["occupations in the tree", "common jobs"],
        },
        INTENT_SEARCH_INDIVIDUALS: {
            "description": "Filter individuals via allow-listed columns only (ILIKE substrings where noted).",
            "params": {
                "given_name": "substring → full_name_lower",
                "surname": "substring → primary_surname_lower",
                "birth_place": "birth_place_display",
                "death_place": "death_place_display",
                "birth_decade": "int",
                "death_decade": "int",
                "sex": "M|F|U|X",
                "is_living": "bool",
                "occupation": "substring",
                "nationality": "substring",
                "limit": "int default 20 max 200",
            },
            "examples": ["Find males named Silva born in the 1890s"],
        },
        INTENT_SEARCH_FAMILIES: {
            "description": "Filter gedcom_families_v2 via allow-listed fields and partner surname subquery.",
            "params": {
                "partner_surname": "gedcom_family_surnames_v2 + surnames",
                "marriage_place": "marriage_place_display",
                "marriage_decade": "int → marriage_year window",
                "min_children": "int",
                "is_divorced": "bool",
                "limit": "int",
            },
            "examples": ["Families with surname Pereira tied to the union"],
        },
        INTENT_SEARCH_EVENTS: {
            "description": "Filter gedcom_events_v2 with optional gedcom_dates_v2 / gedcom_places_v2 joins.",
            "params": {
                "event_type": "substring (e.g. DEAT, BIRT, MARR)",
                "place": "places.original",
                "decade": "int → event date year window",
                "cause": "substring",
                "limit": "int",
            },
            "examples": ["IMMIG events in the 1920s"],
        },
        INTENT_SEARCH_NOTES: {
            "description": "Search gedcom_notes_v2 note text.",
            "params": {"text": "string (required)", "is_top_level": "bool", "limit": "int"},
            "examples": ["Notes mentioning Georgetown"],
        },
        INTENT_SEARCH_SOURCES: {
            "description": "Search gedcom_sources_v2.",
            "params": {"title": "substring", "author": "substring", "text": "substring (text column)", "limit": "int"},
            "examples": ["Sources by author …"],
        },
        INTENT_SEARCH_MEDIA: {
            "description": "Search gedcom_media_v2.",
            "params": {"title": "substring", "description": "substring", "form": "substring (jpg/pdf/…)", "limit": "int"},
            "examples": ["Find photos"],
        },
        INTENT_UNSUPPORTED: {
            "description": "Fallback when the user's question cannot be answered.",
            "params": {"reason": "string (optional explanation)"},
            "examples": [],
        },
    }


def run_intent(
    intent: str, file_uuid: str, params: dict[str, Any] | None, max_rows: int
) -> dict[str, Any]:
    """Execute the named intent. Returns ``{ ok, result|error }``-shaped payload."""
    handler = INTENT_HANDLERS.get(intent)
    if handler is None:
        return {
            "ok": False,
            "error": f"Unknown intent: {intent}",
            "result": _handle_unsupported(file_uuid, {"reason": f"Unknown intent: {intent}"}, max_rows),
        }
    try:
        result = handler(file_uuid, params or {}, max_rows)
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "result": None}
