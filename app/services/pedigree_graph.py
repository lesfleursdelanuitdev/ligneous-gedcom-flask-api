"""Pedigree as a directed graph (parent → child) for relationship queries."""

from __future__ import annotations

import time
from typing import Any

import networkx as nx

from app.db import get_connection


# ── Graph loading ─────────────────────────────────────────────────────────────

def load_pedigree_parent_child_graph(file_uuid: str) -> nx.DiGraph:
    """Directed edges: ``parent_id`` → ``child_id`` from ``gedcom_parent_child_v2``.

    Edge attribute ``rel_type``: 'biological' | 'adoptive' | 'step'.
    """
    G = nx.DiGraph()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT parent_id::text AS p, child_id::text AS c,
                       COALESCE(relationship_type, 'biological') AS rel_type
                FROM gedcom_parent_child_v2
                WHERE file_uuid = %s AND parent_id IS NOT NULL AND child_id IS NOT NULL
                """,
                (file_uuid,),
            )
            for row in cur.fetchall():
                G.add_edge(row["p"], row["c"], rel_type=row["rel_type"])
    return G


# ── Graph cache ───────────────────────────────────────────────────────────────

_GRAPH_CACHE: dict[str, tuple[nx.DiGraph, float]] = {}
_CACHE_TTL = 300.0  # seconds


def get_or_load_graph(file_uuid: str) -> nx.DiGraph:
    """Return cached graph for *file_uuid*, refreshing after TTL expires."""
    cached = _GRAPH_CACHE.get(file_uuid)
    now = time.monotonic()
    if cached is not None and (now - cached[1]) < _CACHE_TTL:
        return cached[0]
    G = load_pedigree_parent_child_graph(file_uuid)
    _GRAPH_CACHE[file_uuid] = (G, now)
    return G


def invalidate_graph_cache(file_uuid: str | None = None) -> None:
    """Evict one tree's graph (or all if *file_uuid* is None)."""
    if file_uuid is None:
        _GRAPH_CACHE.clear()
    else:
        _GRAPH_CACHE.pop(file_uuid, None)


# ── Ancestor helpers ──────────────────────────────────────────────────────────

def _ancestor_set_with_self(G: nx.DiGraph, node_id: str) -> set[str]:
    """Individuals with a directed path ``u → … → node_id`` including ``node_id`` itself."""
    nid = str(node_id)
    if nid not in G:
        return {nid}
    return set(nx.ancestors(G, nid)) | {nid}


def find_minimal_common_ancestors(G: nx.DiGraph, common: set[str]) -> list[str]:
    """Return the subset of *common* where no member is an ancestor of another.

    In pedigree semantics (parent→child edges) an ancestor of node X is any
    node that has a directed path *to* X.  A minimal common ancestor (MCA) is
    therefore a common ancestor that is not reachable *from* any other common
    ancestor — it is as close (in time) to the endpoints as possible.
    """
    mcas: list[str] = []
    for c in common:
        # c is NOT minimal if some other common node is its descendant
        # i.e. there exists c2 in common s.t. path c → c2 exists
        dominated = any(
            c2 != c and nx.has_path(G, c, c2)
            for c2 in common
        )
        if not dominated:
            mcas.append(c)
    return mcas


def pick_lowest_common_ancestor(G: nx.DiGraph, common: set[str], sid: str, tid: str) -> str | None:
    """Among ancestors common to both, pick ``c`` minimizing ``dist(c,sid)+dist(c,tid)`` down-tree."""
    sid, tid = str(sid), str(tid)
    best: str | None = None
    best_score: int | None = None
    for c in common:
        try:
            d1 = nx.shortest_path_length(G, c, sid)
            d2 = nx.shortest_path_length(G, c, tid)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        score = d1 + d2
        if best_score is None or score < best_score:
            best_score = score
            best = c
    return best


# ── Path edge-type helpers ────────────────────────────────────────────────────

def path_has_non_biological(G: nx.DiGraph, path: list[str]) -> bool:
    """Return True if any edge in *path* has rel_type not 'biological'."""
    for i in range(len(path) - 1):
        data = G.get_edge_data(path[i], path[i + 1]) or {}
        if data.get("rel_type", "biological") != "biological":
            return True
    return False


def path_has_step(G: nx.DiGraph, path: list[str]) -> bool:
    for i in range(len(path) - 1):
        data = G.get_edge_data(path[i], path[i + 1]) or {}
        if data.get("rel_type", "biological") == "step":
            return True
    return False


# ── Single-path analysis (original, retained for analytics intents) ───────────

def analyze_relationship_between(G: nx.DiGraph, source_id: str, target_id: str) -> dict[str, Any]:
    """
    Use parent→child digraph semantics.

    Returns keys: ``category``, optional ``lowest_common_ancestor_id``, ``path_lca_to_source``,
    ``path_lca_to_target`` (both lists of ``id`` strings), ``dag``, ``notes`` (optional list).
    """
    sid = str(source_id)
    tid = str(target_id)
    notes: list[str] = []

    Gw = G.copy()
    if sid not in Gw:
        Gw.add_node(sid)
    if tid not in Gw:
        Gw.add_node(tid)

    if not nx.is_directed_acyclic_graph(Gw):
        notes.append("Pedigree links contain directed cycles; path results may not be canonical.")

    if sid == tid:
        return {
            "category": "same_individual",
            "source_id": sid,
            "target_id": tid,
            "lowest_common_ancestor_id": sid,
            "path_lca_to_source": [sid],
            "path_lca_to_target": [tid],
            "dag": nx.is_directed_acyclic_graph(G),
            "notes": notes or None,
        }

    direct_anc = nx.has_path(Gw, sid, tid)
    direct_dec = nx.has_path(Gw, tid, sid)

    if direct_anc:
        path = nx.shortest_path(Gw, sid, tid)
        return {
            "category": "source_is_ancestor_of_target",
            "source_id": sid,
            "target_id": tid,
            "lowest_common_ancestor_id": sid,
            "path_lca_to_source": [sid],
            "path_lca_to_target": path,
            "dag": nx.is_directed_acyclic_graph(G),
            "notes": notes or None,
        }

    if direct_dec:
        path = nx.shortest_path(Gw, tid, sid)
        return {
            "category": "target_is_ancestor_of_source",
            "source_id": sid,
            "target_id": tid,
            "lowest_common_ancestor_id": tid,
            "path_lca_to_source": path,
            "path_lca_to_target": [tid],
            "dag": nx.is_directed_acyclic_graph(G),
            "notes": notes or None,
        }

    common = _ancestor_set_with_self(Gw, sid) & _ancestor_set_with_self(Gw, tid)
    if not common:
        return {
            "category": "unrelated_pedigree_links",
            "source_id": sid,
            "target_id": tid,
            "lowest_common_ancestor_id": None,
            "path_lca_to_source": [],
            "path_lca_to_target": [],
            "dag": nx.is_directed_acyclic_graph(G),
            "notes": (notes + ["No common ancestor reachable via parent-child links."]) if notes else None,
        }

    lca = pick_lowest_common_ancestor(Gw, common, sid, tid)
    if lca is None:
        return {
            "category": "unrelated_pedigree_links",
            "source_id": sid,
            "target_id": tid,
            "lowest_common_ancestor_id": None,
            "path_lca_to_source": [],
            "path_lca_to_target": [],
            "dag": nx.is_directed_acyclic_graph(G),
            "notes": (notes + ["Could not derive a shortest path between common ancestors and endpoints."]) or None,
        }

    path_s = nx.shortest_path(Gw, lca, sid)
    path_t = nx.shortest_path(Gw, lca, tid)
    return {
        "category": "collateral",
        "source_id": sid,
        "target_id": tid,
        "lowest_common_ancestor_id": lca,
        "path_lca_to_source": path_s,
        "path_lca_to_target": path_t,
        "degrees_from_lca": {"to_source_edges": len(path_s) - 1, "to_target_edges": len(path_t) - 1},
        "dag": nx.is_directed_acyclic_graph(G),
        "notes": notes or None,
    }


# ── Multi-path analysis (relationship calculator) ─────────────────────────────

def analyze_all_relationships_between(
    G: nx.DiGraph, source_id: str, target_id: str
) -> list[dict[str, Any]]:
    """Return one dict per distinct minimal-common-ancestor path, sorted simplest first.

    Each dict contains:
      ``category``, ``lca_id``, ``path_to_source``, ``path_to_target``,
      ``degrees_to_source``, ``degrees_to_target``.
    """
    sid, tid = str(source_id), str(target_id)

    # Ensure both nodes exist in a working copy
    Gw = G
    if sid not in G or tid not in G:
        Gw = G.copy()
        if sid not in Gw:
            Gw.add_node(sid)
        if tid not in Gw:
            Gw.add_node(tid)

    if sid == tid:
        return [{"category": "same_individual", "lca_id": sid,
                 "path_to_source": [sid], "path_to_target": [tid],
                 "degrees_to_source": 0, "degrees_to_target": 0}]

    if nx.has_path(Gw, sid, tid):
        path = nx.shortest_path(Gw, sid, tid)
        return [{"category": "source_is_ancestor_of_target", "lca_id": sid,
                 "path_to_source": [sid], "path_to_target": path,
                 "degrees_to_source": 0, "degrees_to_target": len(path) - 1}]

    if nx.has_path(Gw, tid, sid):
        path = nx.shortest_path(Gw, tid, sid)
        return [{"category": "target_is_ancestor_of_source", "lca_id": tid,
                 "path_to_source": path, "path_to_target": [tid],
                 "degrees_to_source": len(path) - 1, "degrees_to_target": 0}]

    common = _ancestor_set_with_self(Gw, sid) & _ancestor_set_with_self(Gw, tid)
    if not common:
        return [{"category": "unrelated_pedigree_links"}]

    mcas = find_minimal_common_ancestors(Gw, common)
    if not mcas:
        return [{"category": "unrelated_pedigree_links"}]

    results: list[dict[str, Any]] = []
    for mca in mcas:
        try:
            path_s = nx.shortest_path(Gw, mca, sid)
            path_t = nx.shortest_path(Gw, mca, tid)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        results.append({
            "category": "collateral",
            "lca_id": mca,
            "path_to_source": path_s,
            "path_to_target": path_t,
            "degrees_to_source": len(path_s) - 1,
            "degrees_to_target": len(path_t) - 1,
        })

    if not results:
        return [{"category": "unrelated_pedigree_links"}]

    results.sort(key=lambda r: r["degrees_to_source"] + r["degrees_to_target"])
    return results
