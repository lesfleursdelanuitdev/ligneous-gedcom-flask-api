"""Backward-compatible import path for the NL intent registry.

Implementation lives in :mod:`app.analytics.intents` (domain-split package).
"""
from __future__ import annotations

from app.analytics.intents import *  # noqa: F403
