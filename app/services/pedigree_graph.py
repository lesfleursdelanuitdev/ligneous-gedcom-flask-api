"""Pedigree as a directed graph (parent → child) for relationship queries."""

from __future__ import annotations

from typing import Any

import networkx as nx

from app.db import get_connection


def load_pedigree_parent_child_graph(file_uuid: str) -> nx.DiGraph:
    """Directed edges: ``parent_id`` → ``child_id`` from ``gedcom_parent_child_v2``."""
    G = nx.DiGraph()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT parent_id::text AS p, child_id::text AS c
                FROM gedcom_parent_child_v2
                WHERE file_uuid = %s AND parent_id IS NOT NULL AND child_id IS NOT NULL
                """,
                (file_uuid,),
            )
            for row in cur.fetchall():
                G.add_edge(row["p"], row["c"])
    return G


def _ancestor_set_with_self(G: nx.DiGraph, node_id: str) -> set[str]:
    """Individuals with a directed path ``u → … → node_id`` including ``node_id`` itself."""
    nid = str(node_id)
    if nid not in G:
        return {nid}
    return set(nx.ancestors(G, nid)) | {nid}


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
