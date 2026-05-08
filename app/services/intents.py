"""Intent registry for natural-language search.

Every intent the LLM is allowed to select maps to a parameterized SQL template
executed by ``run_intent``. The LLM is never permitted to author SQL directly;
it can only emit ``{"intent": <name>, "params": {...}}`` against this registry.

Add new intents by extending ``INTENT_HANDLERS`` plus an entry in
``intent_catalog`` that documents what parameters the LLM may emit.
"""
from __future__ import annotations

from typing import Any, Callable

from app.db import get_connection


INTENT_TOP_GIVEN_NAMES = "top_given_names"
INTENT_TOP_SURNAMES = "top_surnames"
INTENT_GIVEN_NAME_LOOKUP = "given_name_lookup"
INTENT_SURNAME_LOOKUP = "surname_lookup"
INTENT_NAMES_BY_DECADE = "names_by_decade"
INTENT_NAMES_BY_SEX = "names_by_sex"
INTENT_SURNAME_SOUNDEX_GROUPS = "surname_soundex_groups"
INTENT_TREE_SUMMARY = "tree_summary"
INTENT_UNSUPPORTED = "unsupported"


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
