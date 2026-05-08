"""Smoke tests for the Flask app: routes register and suggestions endpoint serves."""
from __future__ import annotations

import json

import pytest

from app.application import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.testing = True
    return app.test_client()


def test_health_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_nl_search_suggestions_endpoint(client):
    res = client.get("/api/research/trees/00000000-0000-0000-0000-000000000000/nl-search/suggestions")
    assert res.status_code == 200
    body = res.get_json()
    assert isinstance(body.get("suggestions"), list)
    assert "intents" in body
    assert "top_given_names" in body["intents"]


def test_nl_search_rejects_empty_query(client):
    res = client.post(
        "/api/research/trees/00000000-0000-0000-0000-000000000000/nl-search",
        data=json.dumps({"query": ""}),
        content_type="application/json",
    )
    assert res.status_code == 400


def test_routes_registered():
    app = create_app()
    paths = {str(rule) for rule in app.url_map.iter_rules()}
    assert "/api/research/trees/<tree_id>/nl-search" in paths
    assert "/api/research/trees/<tree_id>/nl-search/suggestions" in paths
