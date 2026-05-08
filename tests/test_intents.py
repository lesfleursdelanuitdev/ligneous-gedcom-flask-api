"""Unit tests for the intent registry."""
from app.services import intents


def test_intent_catalog_matches_handlers():
    """Every catalog entry must have a registered handler (and vice versa)."""
    catalog = set(intents.intent_catalog().keys())
    handlers = set(intents.INTENT_HANDLERS.keys())
    assert catalog == handlers, (
        f"Catalog/handler mismatch. Only in catalog: {catalog - handlers}; "
        f"only in handlers: {handlers - catalog}"
    )


def test_run_intent_unknown_returns_unsupported_payload():
    """Unknown intents fail closed instead of crashing."""
    out = intents.run_intent("does_not_exist", "fake-uuid", {}, max_rows=10)
    assert out["ok"] is False
    assert "Unknown intent" in out["error"]
    assert "supported_intents" in (out["result"] or {})


def test_clamp_helper_bounds():
    assert intents._clamp("99", default=10, lo=1, hi=50) == 50
    assert intents._clamp(-5, default=10, lo=1, hi=50) == 1
    assert intents._clamp(None, default=7, lo=1, hi=50) == 7
    assert intents._clamp("abc", default=7, lo=1, hi=50) == 7
    assert intents._clamp("3", default=7, lo=1, hi=50) == 3


def test_string_helper_strips_and_defaults():
    assert intents._string("  hello  ") == "hello"
    assert intents._string("") == ""
    assert intents._string(None, default="x") == "x"
    assert intents._string("   ", default="x") == "x"
