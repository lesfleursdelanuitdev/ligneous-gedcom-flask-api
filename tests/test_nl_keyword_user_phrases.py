"""Keyword fallback coverage for genealogist-style phrasing (Groq-off tests).

Pins intents for birthplace, marriages, lifespan, surname lookup, etc.
"""
from __future__ import annotations

import pytest

from app.services import nl_search
from app.services.intents import (
    INTENT_BORN_IN_PLACE,
    INTENT_INDIVIDUALS_AGE_AT_DEATH,
    INTENT_MARRIAGES_BY_PLACE,
    INTENT_INDIVIDUAL_ANCESTORS,
    INTENT_SEARCH_INDIVIDUALS,
    INTENT_SURNAME_LOOKUP,
    INTENT_UNSUPPORTED,
)


@pytest.mark.parametrize(
    ("query", "intent", "params_checks"),
    [
        (
            "Who was born in Guyana?",
            INTENT_BORN_IN_PLACE,
            {"place": "guyana", "limit": 20},
        ),
        (
            "List people named Gonsalves who were born in Guyana",
            INTENT_SEARCH_INDIVIDUALS,
            {
                "birth_place": "guyana",
                "limit": 20,
                "surname": "gonsalves",
            },
        ),
        (
            "Which couples were married in Toronto, Canada?",
            INTENT_MARRIAGES_BY_PLACE,
            {"locality": "toronto, canada"},
        ),
        (
            "Who died before age 70?",
            INTENT_INDIVIDUALS_AGE_AT_DEATH,
            {"operator": "lt", "age": 70},
        ),
        (
            "Find everyone with surname Gonsalves",
            INTENT_SURNAME_LOOKUP,
            {"name": "gonsalves"},
        ),
        (
            "Find everyone with the surname Gonsalves",
            INTENT_SURNAME_LOOKUP,
            {"name": "gonsalves"},
        ),
        (
            "Everyone with surname Gonsalves",
            INTENT_SURNAME_LOOKUP,
            {"name": "gonsalves"},
        ),
        ("people with surname Gonsalves", INTENT_SURNAME_LOOKUP, {"name": "gonsalves"}),
    ],
)
def test_keyword_fallback_user_phrases(query, intent, params_checks):
    out = nl_search._keyword_fallback(query)
    assert out["intent"] == intent
    assert out["source"] == "keyword"
    params = out.get("params") or {}
    for key, expected in params_checks.items():
        assert params.get(key) == expected


def test_keyword_vague_ancestors_phrase_stays_off_lineage_router():
    out = nl_search._keyword_fallback("Who are all my ancestors named John?")
    assert out["intent"] != INTENT_INDIVIDUAL_ANCESTORS
    assert out["intent"] == INTENT_UNSUPPORTED


def test_keyword_complex_cousins_query_unmapped():
    out = nl_search._keyword_fallback(
        "Recursively find all second cousins and their spouses related to Martha"
    )
    assert out["intent"] == INTENT_UNSUPPORTED


@pytest.mark.parametrize(
    "query",
    [
        # Phrased without ``cousins of`` / ``descendants of`` so pedigree keyword rules do not apply.
        "Find extended cousin-cluster relationships near Maria Gonsalves",
        "Show inter-generational descendant spread without naming an anchor individual",
        "Show me the oldest photograph",
    ],
)
def test_keyword_fallback_explicit_unsupported_pins(query):
    out = nl_search._keyword_fallback(query)
    assert out["intent"] == INTENT_UNSUPPORTED
