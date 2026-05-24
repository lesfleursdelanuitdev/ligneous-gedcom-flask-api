"""Fallback intent when the model or router cannot select a supported handler."""
from __future__ import annotations

from typing import Any

from app.analytics.intents.utils import _string


def _handle_unsupported(file_uuid: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    from app.analytics.intents.catalog import intent_catalog

    return {
        "supported_intents": list(intent_catalog().keys()),
        "note": _string(
            params.get("reason"),
            default="Query was not recognized; try rephrasing or pick a supported intent.",
        ),
    }
