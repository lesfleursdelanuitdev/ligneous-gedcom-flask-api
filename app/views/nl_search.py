"""HTTP routes for natural-language search."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.config import NL_PERSIST_QUERY_RUNS
from app.services.intents import intent_catalog
from app.services.nl_search import (
    NLSearchError,
    run_nl_search,
    suggestion_prompts,
)


bp = Blueprint("nl_search", __name__, url_prefix="/api/research/trees")


def _should_persist_runs() -> bool:
    """Downstreams (e.g. public read-only frontends) send X-Research-Persist: false.

    When NL_PERSIST_QUERY_RUNS is false in the environment, persistence is always off.
    """
    if not NL_PERSIST_QUERY_RUNS:
        return False
    raw = (request.headers.get("X-Research-Persist") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    return True


@bp.route("/<tree_id>/nl-search", methods=["POST"])
def nl_search(tree_id: str):
    """POST a natural-language genealogy question for the tree."""
    payload = request.get_json(silent=True) or {}
    query = payload.get("query") or payload.get("q") or ""
    context = payload.get("context") if isinstance(payload.get("context"), dict) else None

    try:
        result = run_nl_search(
            tree_id=tree_id,
            query=str(query),
            context=context,
            persist_runs=_should_persist_runs(),
        )
    except NLSearchError as err:
        return jsonify({"error": err.message}), err.status

    return jsonify(result)


@bp.route("/<tree_id>/nl-search/suggestions", methods=["GET"])
def nl_search_suggestions(tree_id: str):
    """Return starter prompts and the supported intent catalog for UI hints."""
    return jsonify(
        {
            "tree_id": tree_id,
            "suggestions": suggestion_prompts(),
            "intents": intent_catalog(),
        }
    )
