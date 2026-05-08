"""Unit tests for NetworkX pedigree relationship logic (no database)."""

import networkx as nx

from app.services.pedigree_graph import analyze_relationship_between


def test_same_individual():
    G = nx.DiGraph()
    G.add_edge("R", "A")
    out = analyze_relationship_between(G, "A", "A")
    assert out["category"] == "same_individual"
    assert out["lowest_common_ancestor_id"] == "A"


def test_source_is_ancestor_of_target():
    G = nx.DiGraph()
    G.add_edges_from([("R", "A"), ("A", "S"), ("S", "T")])
    out = analyze_relationship_between(G, "A", "T")
    assert out["category"] == "source_is_ancestor_of_target"
    assert out["path_lca_to_target"] == ["A", "S", "T"]
    assert out["lowest_common_ancestor_id"] == "A"


def test_target_is_ancestor_of_source():
    G = nx.DiGraph()
    G.add_edges_from([("T", "U"), ("U", "S")])
    out = analyze_relationship_between(G, "S", "T")
    assert out["category"] == "target_is_ancestor_of_source"
    assert out["path_lca_to_source"] == ["T", "U", "S"]


def test_collateral_via_lca():
    G = nx.DiGraph()
    #        R
    #       / \
    #      A   B
    #      |   |
    #      S   T
    G.add_edges_from([("R", "A"), ("R", "B"), ("A", "S"), ("B", "T")])
    out = analyze_relationship_between(G, "S", "T")
    assert out["category"] == "collateral"
    assert out["lowest_common_ancestor_id"] == "R"
    assert out["path_lca_to_source"] == ["R", "A", "S"]
    assert out["path_lca_to_target"] == ["R", "B", "T"]
    assert out["degrees_from_lca"]["to_source_edges"] == 2
    assert out["degrees_from_lca"]["to_target_edges"] == 2


def test_unrelated_isolated_nodes():
    G = nx.DiGraph()
    G.add_edge("a", "b")
    out = analyze_relationship_between(G, "x", "y")
    assert out["category"] == "unrelated_pedigree_links"
    assert out["lowest_common_ancestor_id"] is None
