"""Pedigree lineage and pairwise relationship intents."""
from __future__ import annotations

from typing import Any, Union

import networkx as nx

from app.db import get_connection
from app.services.pedigree_graph import analyze_relationship_between, load_pedigree_parent_child_graph

from app.analytics.intents.utils import (
    _clamp,
    _hydrate_pedigree_id_chain,
    _resolve_anchor_individual_id,
    _resolve_prefixed_anchor,
)

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
