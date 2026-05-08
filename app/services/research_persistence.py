"""Persistence helpers for natural-language search runs.

Records each NL request to ``research.query_runs`` and an optional snapshot
to ``research.result_sets``. Failures are swallowed and logged so persistence
never blocks the user-facing response.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.db import get_connection


logger = logging.getLogger(__name__)


# Keep stored payloads bounded to avoid bloating the research schema.
_PAYLOAD_MAX_BYTES = 64 * 1024


def _truncate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, default=str)
    if len(encoded) <= _PAYLOAD_MAX_BYTES:
        return payload
    return {
        "_truncated": True,
        "_original_size_bytes": len(encoded),
        "summary_keys": list(payload.keys()),
    }


def record_run(
    *,
    tree_id: str,
    parameters: dict[str, Any],
    status: str,
    result_count: int | None,
    error_message: str | None = None,
) -> str | None:
    """Insert a row in research.query_runs. Returns the new run id or None on failure."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO research.query_runs
                        (tree_id, status, result_count, error_message, parameters_snapshot)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (
                        tree_id,
                        status,
                        result_count,
                        error_message,
                        json.dumps(parameters, default=str),
                    ),
                )
                row = cur.fetchone()
                return str(row["id"]) if row else None
    except Exception as exc:
        logger.warning("Failed to record query_run: %s", exc)
        return None


def record_result(
    *,
    query_run_id: str,
    tree_id: str,
    entity_type: str,
    payload: dict[str, Any],
) -> str | None:
    """Insert a row in research.result_sets with a size-capped payload snapshot."""
    try:
        snapshot = _truncate_payload(payload)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO research.result_sets
                        (query_run_id, entity_type, tree_id, storage_type, payload)
                    VALUES (%s, %s, %s, 'jsonb', %s::jsonb)
                    RETURNING id
                    """,
                    (
                        query_run_id,
                        entity_type,
                        tree_id,
                        json.dumps(snapshot, default=str),
                    ),
                )
                row = cur.fetchone()
                return str(row["id"]) if row else None
    except Exception as exc:
        logger.warning("Failed to record result_set: %s", exc)
        return None
