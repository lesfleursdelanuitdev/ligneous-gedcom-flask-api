"""Lineage endpoints."""
from flask import Blueprint, jsonify, request

from app.services.lineage_detection import detect_lineages

bp = Blueprint("lineages", __name__, url_prefix="/api/lineages")


@bp.route("/compute", methods=["POST"])
def compute():
    """Trigger lineage detection for a GEDCOM file."""
    body = request.get_json(silent=True) or {}
    file_uuid = body.get("file_uuid") or request.args.get("file_uuid")
    if not file_uuid:
        return jsonify({"error": "file_uuid is required"}), 400

    triggered_by = body.get("triggered_by", "manual")
    try:
        summary = detect_lineages(file_uuid, triggered_by=triggered_by)
        return jsonify({"status": "ok", **summary})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
