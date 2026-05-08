"""Integration tests: compare intent handlers and NL search against real DB counts.

Requires a reachable PostgreSQL database (see ``DATABASE_URL``, loaded via
``tests/conftest`` dotenv discovery). Marked ``integration`` for optional filtering::

    pytest tests/test_nl_integration.py -m integration   # integration file only

When ``DATABASE_URL`` is unset or empty, tests in this module are skipped at the
``nl_tree_context`` fixture.
"""
from __future__ import annotations

import json

import pytest

from app.services import intents


pytestmark = pytest.mark.integration


def _database_available() -> bool:
    import os

    return bool((os.environ.get("DATABASE_URL") or "").strip())


@pytest.fixture(scope="module")
def nl_tree_context():
    if not _database_available():
        pytest.skip("DATABASE_URL not set or empty.")

    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.id::text AS tree_id, gf.id::text AS file_uuid,
                       COUNT(i.id)::int AS n_individuals
                FROM trees t
                JOIN gedcom_files gf ON gf.file_id = t.file_id
                JOIN gedcom_individuals_v2 i ON i.file_uuid = gf.id
                GROUP BY t.id, gf.id
                ORDER BY n_individuals DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
    if not row:
        pytest.skip("No tree with gedcom_individuals_v2 rows found.")
    return dict(row)


def test_run_intent_tree_summary_matches_db(nl_tree_context):
    file_uuid = nl_tree_context["file_uuid"]

    out = intents.run_intent(intents.INTENT_TREE_SUMMARY, file_uuid, {}, 200)
    assert out["ok"] is True
    summary = (out["result"] or {}).get("summary") or {}

    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*)::int AS c FROM gedcom_individuals_v2 WHERE file_uuid = %s",
                (file_uuid,),
            )
            expected = cur.fetchone()["c"]

    assert summary.get("individuals") == expected


def test_run_intent_top_surnames_contains_db_leader(nl_tree_context):
    file_uuid = nl_tree_context["file_uuid"]

    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT surname AS name FROM gedcom_surnames_v2
                WHERE file_uuid = %s
                ORDER BY frequency DESC NULLS LAST, surname ASC
                LIMIT 1
                """,
                (file_uuid,),
            )
            leader = cur.fetchone()
    if not leader or not leader.get("name"):
        pytest.skip("No surname-frequency rows for this file_uuid.")

    out = intents.run_intent(intents.INTENT_TOP_SURNAMES, file_uuid, {"limit": 50}, 200)
    assert out["ok"] is True
    rows = (out["result"] or {}).get("top_surnames") or []
    names = [r["name"] for r in rows if isinstance(r, dict) and r.get("name")]
    assert leader["name"] in names


def test_nl_search_keyword_e2e(nl_tree_context):
    tree_id = nl_tree_context["tree_id"]

    from app.services import nl_search

    body = nl_search.run_nl_search(
        tree_id=tree_id,
        query="how big is the tree?",
        persist_runs=False,
    )
    assert body["intent"] == intents.INTENT_TREE_SUMMARY
    assert body["meta"]["persisted"] is False
    assert (body["result"] or {}).get("summary", {}).get("individuals") == nl_tree_context[
        "n_individuals"
    ]


def test_nl_http_post_integration(nl_tree_context, monkeypatch):
    monkeypatch.setattr("app.views.nl_search.NL_PERSIST_QUERY_RUNS", False)

    from app.application import create_app

    tree_id = nl_tree_context["tree_id"]
    app = create_app()
    app.testing = True
    client = app.test_client()

    res = client.post(
        f"/api/research/trees/{tree_id}/nl-search",
        data=json.dumps({"query": "What are the most common surnames?"}),
        content_type="application/json",
        headers={"X-Research-Persist": "false"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body.get("intent") == intents.INTENT_TOP_SURNAMES
    assert isinstance((body.get("result") or {}).get("top_surnames"), list)
