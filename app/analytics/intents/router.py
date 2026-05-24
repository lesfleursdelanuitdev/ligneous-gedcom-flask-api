"""Dispatch layer: map intent name to registered handler and return shaped result."""
from __future__ import annotations

from typing import Any

from app.analytics.intents.registry import INTENT_HANDLERS
from app.analytics.intents.fallback import _handle_unsupported

def run_intent(
    intent: str, file_uuid: str, params: dict[str, Any] | None, max_rows: int
) -> dict[str, Any]:
    """Execute the named intent. Returns ``{ ok, result|error }``-shaped payload."""
    handler = INTENT_HANDLERS.get(intent)
    if handler is None:
        return {
            "ok": False,
            "error": f"Unknown intent: {intent}",
            "result": _handle_unsupported(file_uuid, {"reason": f"Unknown intent: {intent}"}, max_rows),
        }
    try:
        result = handler(file_uuid, params or {}, max_rows)
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "result": None}
