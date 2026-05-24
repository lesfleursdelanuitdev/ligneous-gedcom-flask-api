"""Unit tests for relationship label computation (no database)."""

from __future__ import annotations

import networkx as nx
import pytest

from app.services.relationship_label import compute_label, _is_half, _are_co_parents
from app.services.pedigree_graph import (
    analyze_all_relationships_between,
    find_minimal_common_ancestors,
    _ancestor_set_with_self,
)


# ── compute_label ─────────────────────────────────────────────────────────────

def test_direct_ancestor_father():
    assert compute_label(0, 1, "M", None, False, False) == "father"

def test_direct_ancestor_mother():
    assert compute_label(0, 1, "F", None, False, False) == "mother"

def test_direct_ancestor_parent_unknown_sex():
    assert compute_label(0, 1, None, None, False, False) == "parent"

def test_direct_ancestor_grandfather():
    assert compute_label(0, 2, "M", None, False, False) == "grandfather"

def test_direct_ancestor_great_grandfather():
    assert compute_label(0, 3, "M", None, False, False) == "great-grandfather"

def test_direct_ancestor_2x_great_grandmother():
    assert compute_label(0, 4, "F", None, False, False) == "great-great-grandmother"

def test_direct_descendant_son():
    assert compute_label(1, 0, None, "M", False, False) == "son"

def test_direct_descendant_daughter():
    assert compute_label(1, 0, None, "F", False, False) == "daughter"

def test_direct_descendant_grandchild():
    assert compute_label(2, 0, None, None, False, False) == "grandchild"

def test_direct_descendant_great_grandson():
    assert compute_label(3, 0, None, "M", False, False) == "great-grandson"

def test_full_brother():
    assert compute_label(1, 1, None, "M", False, False) == "brother"

def test_half_sister():
    assert compute_label(1, 1, None, "F", True, False) == "half-sister"

def test_step_sibling():
    assert compute_label(1, 1, None, None, False, True) == "step-sibling"

def test_uncle():
    assert compute_label(1, 2, "M", None, False, False) == "uncle"

def test_aunt():
    assert compute_label(1, 2, "F", None, False, False) == "aunt"

def test_great_uncle():
    assert compute_label(1, 3, "M", None, False, False) == "great-uncle"

def test_nephew():
    assert compute_label(2, 1, "M", None, False, False) == "nephew"

def test_niece():
    assert compute_label(2, 1, "F", None, False, False) == "niece"

def test_great_niece():
    assert compute_label(3, 1, "F", None, False, False) == "great-niece"

def test_first_cousin():
    assert compute_label(2, 2, None, None, False, False) == "1st cousin"

def test_second_cousin():
    assert compute_label(3, 3, None, None, False, False) == "2nd cousin"

def test_half_first_cousin():
    assert compute_label(2, 2, None, None, True, False) == "half-1st cousin"

def test_first_cousin_once_removed_descending():
    # source has fewer hops (2) than target (3) → source is older gen → descending from source's pov
    assert compute_label(2, 3, None, None, False, False) == "1st cousin, once removed (descending)"

def test_first_cousin_once_removed_ascending():
    # source has more hops (3) → source is younger → ascending
    assert compute_label(3, 2, None, None, False, False) == "1st cousin, once removed (ascending)"

def test_first_cousin_twice_removed_descending():
    assert compute_label(2, 4, None, None, False, False) == "1st cousin, twice removed (descending)"

def test_same_individual():
    assert compute_label(0, 0, None, None, False, False) == "same individual"


# ── find_minimal_common_ancestors ─────────────────────────────────────────────

def test_mcas_full_siblings():
    # P1 and P2 are both parents of S and T
    G = nx.DiGraph()
    G.add_edges_from([("P1", "S"), ("P1", "T"), ("P2", "S"), ("P2", "T")])
    common = _ancestor_set_with_self(G, "S") & _ancestor_set_with_self(G, "T")
    mcas = find_minimal_common_ancestors(G, common)
    assert set(mcas) == {"P1", "P2"}

def test_mcas_half_siblings():
    # Only P1 is a common parent; P2 is unique to S
    G = nx.DiGraph()
    G.add_edges_from([("P1", "S"), ("P1", "T"), ("P2", "S")])
    common = _ancestor_set_with_self(G, "S") & _ancestor_set_with_self(G, "T")
    mcas = find_minimal_common_ancestors(G, common)
    assert mcas == ["P1"]

def test_mcas_cousins():
    # GP is single shared grandparent (half-cousins)
    G = nx.DiGraph()
    G.add_edges_from([("GP", "PA"), ("GP", "PB"), ("PA", "S"), ("PB", "T")])
    common = _ancestor_set_with_self(G, "S") & _ancestor_set_with_self(G, "T")
    mcas = find_minimal_common_ancestors(G, common)
    assert set(mcas) == {"GP"}

def test_mcas_excludes_ancestor_of_another_mca():
    # GGP → GP → P → S;  GP is also ancestor of T directly
    # Common ancestors: GGP, GP — but GGP is an ancestor of GP, so GP is MCA only
    G = nx.DiGraph()
    G.add_edges_from([("GGP", "GP"), ("GP", "PA"), ("GP", "T"), ("PA", "S")])
    common = _ancestor_set_with_self(G, "S") & _ancestor_set_with_self(G, "T")
    mcas = find_minimal_common_ancestors(G, common)
    assert set(mcas) == {"GP"}


# ── _is_half ──────────────────────────────────────────────────────────────────

def test_is_half_one_mca():
    G = nx.DiGraph()
    assert _is_half(G, ["P1"]) is True

def test_not_half_co_parents():
    G = nx.DiGraph()
    G.add_edges_from([("P1", "child"), ("P2", "child")])
    assert _is_half(G, ["P1", "P2"]) is False

def test_is_half_two_mcas_no_shared_child():
    G = nx.DiGraph()
    G.add_edges_from([("P1", "childA"), ("P2", "childB")])
    assert _is_half(G, ["P1", "P2"]) is True


# ── analyze_all_relationships_between ─────────────────────────────────────────

def test_all_rels_full_siblings():
    G = nx.DiGraph()
    G.add_edges_from([("P1", "S"), ("P1", "T"), ("P2", "S"), ("P2", "T")])
    results = analyze_all_relationships_between(G, "S", "T")
    # Two MCAs → two paths in collateral results
    assert all(r["category"] == "collateral" for r in results)
    assert all(r["degrees_to_source"] == 1 and r["degrees_to_target"] == 1 for r in results)
    lcas = {r["lca_id"] for r in results}
    assert lcas == {"P1", "P2"}

def test_all_rels_simplest_first():
    G = nx.DiGraph()
    #        GP
    #       /  \
    #      PA   PB
    #     /      \
    #    S         T
    # Also GP2 → GGP → GP so there's another common ancestor further up
    G.add_edges_from([
        ("GGP", "GP"), ("GP", "PA"), ("GP", "PB"), ("PA", "S"), ("PB", "T"),
    ])
    results = analyze_all_relationships_between(G, "S", "T")
    # GP (ds=2, dt=2) should come before GGP (ds=3, dt=3)
    assert results[0]["lca_id"] == "GP"
    assert results[0]["degrees_to_source"] + results[0]["degrees_to_target"] <= \
           results[-1]["degrees_to_source"] + results[-1]["degrees_to_target"]
