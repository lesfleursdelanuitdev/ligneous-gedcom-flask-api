"""Health and readiness endpoints."""
from flask import Blueprint, jsonify
from app.db import check_read_only

bp = Blueprint("health", __name__, url_prefix="/api")


@bp.route("/health", methods=["GET"])
def health():
    """Liveness: API is up."""
    return jsonify({"status": "ok", "service": "ligneous-python-api"})


@bp.route("/ready", methods=["GET"])
def ready():
    """Readiness: API can reach the database (read check)."""
    ok, message = check_read_only()
    if ok:
        return jsonify({"status": "ok", "database": "connected"})
    return jsonify({"status": "error", "database": message}), 503
