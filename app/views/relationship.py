"""Relationship calculator endpoint."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services.relationship_label import compute_relationships
from app.services.pedigree_graph import invalidate_graph_cache

bp = Blueprint("relationship", __name__, url_prefix="/api/relationship")


def _bad(msg: str, status: int = 400):
    return jsonify({"error": msg}), status


@bp.route("/between", methods=["POST"])
def relationship_between():
    """Compute the relationship between two individuals in a tree.

    Request body (JSON):
      file_uuid  – UUID of the GEDCOM file / tree
      source_id  – UUID of the source individual
      target_id  – UUID of the target individual
    """
    body = request.get_json(silent=True) or {}

    file_uuid = (body.get("file_uuid") or "").strip()
    source_id = (body.get("source_id") or "").strip()
    target_id = (body.get("target_id") or "").strip()

    if not file_uuid:
        return _bad("file_uuid is required")
    if not source_id:
        return _bad("source_id is required")
    if not target_id:
        return _bad("target_id is required")

    try:
        result = compute_relationships(file_uuid, source_id, target_id)
        return jsonify(result)
    except Exception as exc:
        return _bad(str(exc), 500)


@bp.route("/cache/invalidate", methods=["POST"])
def invalidate_cache():
    """Evict the cached pedigree graph for a tree (or all trees).

    Request body (JSON):
      file_uuid  – UUID to evict; omit to clear all caches.
    """
    body = request.get_json(silent=True) or {}
    file_uuid = (body.get("file_uuid") or "").strip() or None
    invalidate_graph_cache(file_uuid)
    return jsonify({"ok": True, "invalidated": file_uuid or "all"})
