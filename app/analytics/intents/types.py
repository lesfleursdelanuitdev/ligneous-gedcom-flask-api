"""Shared types for NL intent handlers."""
from __future__ import annotations

from typing import Any, Callable

IntentHandler = Callable[[str, dict[str, Any], int], dict[str, Any]]
