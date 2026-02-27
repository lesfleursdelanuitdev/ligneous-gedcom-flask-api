"""Research endpoints — smoke test and future research routes."""
from flask import Blueprint, jsonify, request
from app.db import get_connection

bp = Blueprint("research", __name__, url_prefix="/api/research")


@bp.route("/ping", methods=["GET"])
def ping():
    """Smoke test: verify the research proxy chain works end-to-end."""
    return jsonify({"status": "ok", "service": "ligneous-python-api", "schema": "research"})


@bp.route("/schema-check", methods=["GET"])
def schema_check():
    """Verify the research schema exists and list its tables."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'research' ORDER BY table_name"
                )
                tables = [row["table_name"] for row in cur.fetchall()]
        return jsonify({"status": "ok", "tables": tables, "count": len(tables)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
