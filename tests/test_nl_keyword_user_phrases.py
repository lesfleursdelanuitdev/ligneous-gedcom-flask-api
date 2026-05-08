"""Keyword fallback coverage for genealogist-style phrasing (Groq-off tests).

Baseline today: geography, age-at-death, and marriage-place questions map to
``unsupported`` until dedicated intents exist. ``surname_lookup`` phrases are
pinned so refactoring the regex does not regress.
"""
from __future__ import annotations

import pytest

from app.services import nl_search
from app.services.intents import INTENT_SURNAME_LOOKUP, INTENT_UNSUPPORTED


@pytest.mark.parametrize(
    ("query", "intent", "name_substring"),
    [
        ("Who was born in Guyana?", INTENT_UNSUPPORTED, None),
        ("List people named Gonsalves who were born in Guyana", INTENT_UNSUPPORTED, None),
        ("Which couples were married in Toronto, Canada?", INTENT_UNSUPPORTED, None),
        ("Who died before age 70?", INTENT_UNSUPPORTED, None),
        ("Find everyone with surname Gonsalves", INTENT_SURNAME_LOOKUP, "gonsalves"),
        ("Find everyone with the surname Gonsalves", INTENT_SURNAME_LOOKUP, "gonsalves"),
        ("Everyone with surname Gonsalves", INTENT_SURNAME_LOOKUP, "gonsalves"),
        ("people with surname Gonsalves", INTENT_SURNAME_LOOKUP, "gonsalves"),
    ],
)
def test_keyword_fallback_user_phrases(query, intent, name_substring):
    out = nl_search._keyword_fallback(query)
    assert out["intent"] == intent
    assert out["source"] == "keyword"
    if name_substring:
        got = str((out.get("params") or {}).get("name", "")).lower()
        assert got.startswith(name_substring)
