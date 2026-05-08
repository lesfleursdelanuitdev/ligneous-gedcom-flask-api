"""Extended keyword-fallback phrases: synonyms, ordering, and known limitations.

These complement ``test_nl_search`` (core rules) and ``test_nl_keyword_user_phrases``
(genealogist-style lines). Pinning behavior here prevents silent regressions when
``_KEYWORD_RULES`` or the surname/given regexes change.
"""
from __future__ import annotations

import pytest

from app.services import nl_search
from app.services.intents import (
    INTENT_GIVEN_NAME_LOOKUP,
    INTENT_INDIVIDUAL_ANCESTORS,
    INTENT_INDIVIDUAL_COUSINS,
    INTENT_INDIVIDUAL_EVENTS_BY_PLACE,
    INTENT_NAMES_BY_DECADE,
    INTENT_NAMES_BY_SEX,
    INTENT_SURNAME_LOOKUP,
    INTENT_SURNAME_SOUNDEX_GROUPS,
    INTENT_TOP_GIVEN_NAMES,
    INTENT_TOP_SURNAMES,
    INTENT_TREE_SUMMARY,
    INTENT_UNSUPPORTED,
)


@pytest.mark.parametrize(
    ("query", "intent", "params_subset"),
    [
        ("Show me the tree summary", INTENT_TREE_SUMMARY, {}),
        ("How many people are in this tree?", INTENT_TREE_SUMMARY, {}),
        ("Most common surnames", INTENT_TOP_SURNAMES, {"limit": 10}),
        ("What are the top first names?", INTENT_TOP_GIVEN_NAMES, {"limit": 10}),
        ("First names over time", INTENT_NAMES_BY_DECADE, {"top_names": 10}),
        ("Trend for given names", INTENT_NAMES_BY_DECADE, {"top_names": 10}),
        ("Popular boy names", INTENT_NAMES_BY_SEX, {"sex": "M", "limit": 10}),
        ("Girls names in the tree", INTENT_NAMES_BY_SEX, {"sex": "F", "limit": 10}),
        ("Surnames matching Pereira", INTENT_SURNAME_LOOKUP, {"name": "pereira", "limit": 20}),
        ("Given names like Maria", INTENT_GIVEN_NAME_LOOKUP, {"name": "maria", "limit": 20}),
        ("show soundex for surnames", INTENT_SURNAME_SOUNDEX_GROUPS, {"limit": 15}),
        # First rule wins: "how many" matches before any surname-specific rule.
        ("How many common surnames are there?", INTENT_TREE_SUMMARY, {}),
        # Multi-token surnames: regex stops at the first space (documented limitation).
        ("Search for surname Da Costa", INTENT_SURNAME_LOOKUP, {"name": "da", "limit": 20}),
        ("popular last names", INTENT_TOP_SURNAMES, {"limit": 10}),
        ("Everyone with last name Smith", INTENT_SURNAME_LOOKUP, {"name": "smith", "limit": 50}),
        (
            "Phonetically similar last names",
            INTENT_SURNAME_SOUNDEX_GROUPS,
            {"limit": 15},
        ),
        ("Events recorded in Halifax", INTENT_INDIVIDUAL_EVENTS_BY_PLACE, {"locality": "halifax"}),
        ("Ancestors of @I999@", INTENT_INDIVIDUAL_ANCESTORS, {"xref": "@I999@"}),
        ("Cousins of Jane Doe", INTENT_INDIVIDUAL_COUSINS, {}),
    ],
)
def test_keyword_fallback_extended_routing(query, intent, params_subset):
    out = nl_search._keyword_fallback(query)
    assert out["intent"] == intent
    assert out["source"] == "keyword"
    params = out.get("params") or {}
    for key, value in params_subset.items():
        assert params.get(key) == value


@pytest.mark.parametrize(
    "query",
    [
        "Who are all my ancestors named John?",
        "Show the full family tree as a list",
    ],
)
def test_keyword_fallback_extended_unsupported(query):
    out = nl_search._keyword_fallback(query)
    assert out["intent"] == INTENT_UNSUPPORTED
    assert out["source"] == "keyword"


def test_keyword_fallback_given_name_ascii_regex_strips_extended_chars():
    """Pattern only allows ASCII letters in the captured name slice (accent stops the run)."""
    out = nl_search._keyword_fallback("Given names like José")
    assert out["intent"] == INTENT_GIVEN_NAME_LOOKUP
    assert out["params"]["name"] == "jos"
