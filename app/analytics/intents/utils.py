"""Shared helpers for intent SQL params and anchor resolution."""
from __future__ import annotations

from typing import Any, Union

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
        SELECT id::text AS id, xref, full_name, sex, birth_year, death_year
        FROM gedcom_individuals_v2
        WHERE file_uuid = %s AND id IN %s
        """,
        (file_uuid, tuple(uniq)),
    )
    by_id = {r["id"]: dict(r) for r in cur.fetchall()}
    return [by_id[u] for u in uniq if u in by_id]

def _sex_code_from_param(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        u = value.strip().upper()
        return u if u in {"M", "F", "U", "X"} else None
    return None

