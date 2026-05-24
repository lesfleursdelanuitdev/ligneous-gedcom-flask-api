"""Relationship label computation from pedigree graph paths."""

from __future__ import annotations

from typing import Any

import networkx as nx

from app.services.pedigree_graph import (
    analyze_all_relationships_between,
    find_minimal_common_ancestors,
    get_or_load_graph,
    path_has_step,
    _ancestor_set_with_self,
)
from app.analytics.intents.utils import _hydrate_pedigree_id_chain


# ── Label primitives ──────────────────────────────────────────────────────────

def _ordinal(n: int) -> str:
    if n == 1: return "1st"
    if n == 2: return "2nd"
    if n == 3: return "3rd"
    return f"{n}th"


def _sex(m: str, f: str, neutral: str, sex: str | None) -> str:
    if sex == "M": return m
    if sex == "F": return f
    return neutral


def compute_label(
    ds: int,
    dt: int,
    source_sex: str | None,
    target_sex: str | None,
    is_half: bool,
    is_step: bool,
) -> str:
    """Return a human-readable relationship label.

    *ds* = degrees from LCA to source, *dt* = degrees from LCA to target.
    The label describes what SOURCE is relative to TARGET.
    """
    if ds == 0 and dt == 0:
        return "same individual"

    # Source is a direct ancestor of target
    if ds == 0:
        gen = dt
        if gen == 1: return _sex("father", "mother", "parent", source_sex)
        if gen == 2: return _sex("grandfather", "grandmother", "grandparent", source_sex)
        return "great-" * (gen - 2) + _sex("grandfather", "grandmother", "grandparent", source_sex)

    # Source is a direct descendant of target
    if dt == 0:
        gen = ds
        if gen == 1: return _sex("son", "daughter", "child", source_sex)
        if gen == 2: return _sex("grandson", "granddaughter", "grandchild", source_sex)
        return "great-" * (gen - 2) + _sex("grandson", "granddaughter", "grandchild", source_sex)

    pfx = "step-" if is_step else ("half-" if is_half else "")

    # Siblings
    if ds == 1 and dt == 1:
        return pfx + _sex("brother", "sister", "sibling", source_sex)

    # Uncle / aunt  (source is 1 hop from LCA, target is further down)
    if ds == 1:
        great = "great-" * (dt - 2) if dt > 2 else ""
        return pfx + great + _sex("uncle", "aunt", "parent's sibling", source_sex)

    # Nephew / niece  (target is 1 hop from LCA, source is further down)
    if dt == 1:
        great = "great-" * (ds - 2) if ds > 2 else ""
        return pfx + great + _sex("nephew", "niece", "sibling's child", source_sex)

    # Cousins
    degree = min(ds, dt) - 1
    removed = abs(ds - dt)
    base = f"{pfx}{_ordinal(degree)} cousin"
    if removed == 0:
        return base
    removed_str = "once" if removed == 1 else ("twice" if removed == 2 else f"{removed} times")
    # ascending = source looks UP to reach target (target is in an older generation)
    direction = "ascending" if ds > dt else "descending"
    return f"{base}, {removed_str} removed ({direction})"


# ── Half-relationship detection ───────────────────────────────────────────────

def _are_co_parents(G: nx.DiGraph, a: str, b: str) -> bool:
    return bool(set(G.successors(a)) & set(G.successors(b)))


def _is_half(G: nx.DiGraph, mcas_for_group: list[str]) -> bool:
    """Return True when the group of MCAs does NOT contain a co-parent pair."""
    if len(mcas_for_group) < 2:
        return True
    for i, a in enumerate(mcas_for_group):
        for b in mcas_for_group[i + 1:]:
            if _are_co_parents(G, a, b):
                return False
    return True


# ── Relationship grouping ─────────────────────────────────────────────────────

def _group_by_degree(paths: list[dict[str, Any]]) -> dict[tuple[int, int], list[dict[str, Any]]]:
    """Group collateral paths by their (degrees_to_source, degrees_to_target) pair."""
    groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for p in paths:
        key = (p["degrees_to_source"], p["degrees_to_target"])
        groups.setdefault(key, []).append(p)
    return groups


# ── Main computation ──────────────────────────────────────────────────────────

def compute_relationships(
    file_uuid: str,
    source_id: str,
    target_id: str,
) -> dict[str, Any]:
    """Return the full relationship response dict for a (source, target) pair."""
    G = get_or_load_graph(file_uuid)
    raw_paths = analyze_all_relationships_between(G, source_id, target_id)

    # Fast-path: unrelated or same individual
    first = raw_paths[0] if raw_paths else {}
    if first.get("category") in ("unrelated_pedigree_links", "same_individual"):
        label = "same individual" if first.get("category") == "same_individual" else "not related"
        return {
            "sourceId": source_id,
            "targetId": target_id,
            "label": label,
            "relatedInMultipleWays": False,
            "relationships": [{
                "label": label,
                "isSimplest": True,
                "isHalf": False,
                "isStep": False,
                "degreesToSource": 0,
                "degreesToTarget": 0,
                "pathToSource": [],
                "pathToTarget": [],
            }],
        }

    # Hydrate all node IDs appearing in paths
    all_ids: list[str] = []
    seen: set[str] = set()
    for p in raw_paths:
        for nid in p.get("path_to_source", []) + p.get("path_to_target", []):
            if nid not in seen:
                seen.add(nid)
                all_ids.append(nid)

    with __import__("app.db", fromlist=["get_connection"]).get_connection() as conn:
        with conn.cursor() as cur:
            raw_hydrated = _hydrate_pedigree_id_chain(cur, file_uuid, all_ids)

    by_id: dict[str, dict[str, Any]] = {r["id"]: r for r in raw_hydrated}

    def hydrate(ids: list[str]) -> list[dict[str, Any]]:
        return [by_id[i] for i in ids if i in by_id]

    # Extract source/target sex for labelling
    source_rec = by_id.get(source_id) or {}
    target_rec = by_id.get(target_id) or {}
    source_sex: str | None = source_rec.get("sex")
    target_sex: str | None = target_rec.get("sex")

    # Handle direct ancestor/descendant (single path, no half/step grouping needed)
    if first["category"] in ("source_is_ancestor_of_target", "target_is_ancestor_of_source"):
        ds = first["degrees_to_source"]
        dt = first["degrees_to_target"]
        is_step = (
            path_has_step(G, first["path_to_source"]) or
            path_has_step(G, first["path_to_target"])
        )
        label = compute_label(ds, dt, source_sex, target_sex, is_half=False, is_step=is_step)
        return {
            "sourceId": source_id,
            "targetId": target_id,
            "label": label,
            "relatedInMultipleWays": False,
            "relationships": [{
                "label": label,
                "isSimplest": True,
                "isHalf": False,
                "isStep": is_step,
                "degreesToSource": ds,
                "degreesToTarget": dt,
                "pathToSource": hydrate(first["path_to_source"]),
                "pathToTarget": hydrate(first["path_to_target"]),
            }],
        }

    # Collateral — group by (ds, dt) to detect half and deduplicate
    collateral = [p for p in raw_paths if p["category"] == "collateral"]
    groups = _group_by_degree(collateral)

    relationships: list[dict[str, Any]] = []
    for (ds, dt), group_paths in sorted(groups.items(), key=lambda kv: kv[0][0] + kv[0][1]):
        mcas = [p["lca_id"] for p in group_paths]
        is_h = _is_half(G, mcas)
        # Step: any path in this group has a step edge
        is_s = any(
            path_has_step(G, p["path_to_source"]) or path_has_step(G, p["path_to_target"])
            for p in group_paths
        )
        label = compute_label(ds, dt, source_sex, target_sex, is_half=is_h, is_step=is_s)
        # Use the first (simplest representative) path for display
        rep = group_paths[0]
        relationships.append({
            "label": label,
            "isSimplest": False,  # set below
            "isHalf": is_h,
            "isStep": is_s,
            "degreesToSource": ds,
            "degreesToTarget": dt,
            "pathToSource": hydrate(rep["path_to_source"]),
            "pathToTarget": hydrate(rep["path_to_target"]),
        })

    if relationships:
        relationships[0]["isSimplest"] = True

    primary_label = relationships[0]["label"] if relationships else "not related"
    return {
        "sourceId": source_id,
        "targetId": target_id,
        "label": primary_label,
        "relatedInMultipleWays": len(relationships) > 1,
        "relationships": relationships,
    }
