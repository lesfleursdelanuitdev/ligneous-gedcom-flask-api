"""Genealogy-oriented NL intent registry (split by domain under subpackages).

* **Constants** — :mod:`app.analytics.intents.constants`
* **Shared helpers** — :mod:`app.analytics.intents.utils`
* **LLM catalog** — :mod:`app.analytics.intents.catalog`
* **Handler map** — :mod:`app.analytics.intents.registry`
* **Dispatch** — :mod:`app.analytics.intents.router`

The legacy import path ``app.services.intents`` re-exports this package unchanged.
"""
from __future__ import annotations

from app.analytics.intents.catalog import intent_catalog
from app.analytics.intents.constants import (
    INTENT_BORN_IN_DECADE,
    INTENT_BORN_IN_PLACE,
    INTENT_CAUSE_OF_DEATH,
    INTENT_DIED_IN_PLACE,
    INTENT_GIVEN_NAME_LOOKUP,
    INTENT_INDIVIDUAL_ANCESTORS,
    INTENT_INDIVIDUAL_COUSINS,
    INTENT_INDIVIDUAL_DESCENDANTS,
    INTENT_INDIVIDUAL_EVENTS_BY_PLACE,
    INTENT_INDIVIDUALS_AGE_AT_DEATH,
    INTENT_INDIVIDUALS_BY_LOCALITY,
    INTENT_INDIVIDUALS_LIFESPAN_YEARS,
    INTENT_LARGEST_FAMILIES,
    INTENT_LIFESPAN_STATS,
    INTENT_LONGEST_LIVED,
    INTENT_MARRIAGES_BY_PLACE,
    INTENT_MIGRATION_PLACES,
    INTENT_NAMES_BY_DECADE,
    INTENT_NAMES_BY_SEX,
    INTENT_OCCUPATION_STATS,
    INTENT_RELATIONSHIP_BETWEEN,
    INTENT_SEARCH_EVENTS,
    INTENT_SEARCH_FAMILIES,
    INTENT_SEARCH_INDIVIDUALS,
    INTENT_SEARCH_MEDIA,
    INTENT_SEARCH_NOTES,
    INTENT_SEARCH_SOURCES,
    INTENT_SURNAME_BY_PLACE,
    INTENT_SURNAME_LOOKUP,
    INTENT_SURNAME_SOUNDEX_GROUPS,
    INTENT_TOP_GIVEN_NAMES,
    INTENT_TOP_SURNAMES,
    INTENT_TREE_SUMMARY,
    INTENT_UNSUPPORTED,
    SEARCH_INTENT_NAMES,
)
from app.analytics.intents.registry import INTENT_HANDLERS
from app.analytics.intents.router import run_intent
from app.analytics.intents.types import IntentHandler
from app.analytics.intents.utils import _clamp, _string

__all__ = [
    "INTENT_BORN_IN_DECADE",
    "INTENT_BORN_IN_PLACE",
    "INTENT_CAUSE_OF_DEATH",
    "INTENT_DIED_IN_PLACE",
    "INTENT_GIVEN_NAME_LOOKUP",
    "INTENT_INDIVIDUAL_ANCESTORS",
    "INTENT_INDIVIDUAL_COUSINS",
    "INTENT_INDIVIDUAL_DESCENDANTS",
    "INTENT_INDIVIDUAL_EVENTS_BY_PLACE",
    "INTENT_INDIVIDUALS_AGE_AT_DEATH",
    "INTENT_INDIVIDUALS_BY_LOCALITY",
    "INTENT_INDIVIDUALS_LIFESPAN_YEARS",
    "INTENT_LARGEST_FAMILIES",
    "INTENT_LIFESPAN_STATS",
    "INTENT_LONGEST_LIVED",
    "INTENT_MARRIAGES_BY_PLACE",
    "INTENT_MIGRATION_PLACES",
    "INTENT_NAMES_BY_DECADE",
    "INTENT_NAMES_BY_SEX",
    "INTENT_OCCUPATION_STATS",
    "INTENT_RELATIONSHIP_BETWEEN",
    "INTENT_SEARCH_EVENTS",
    "INTENT_SEARCH_FAMILIES",
    "INTENT_SEARCH_INDIVIDUALS",
    "INTENT_SEARCH_MEDIA",
    "INTENT_SEARCH_NOTES",
    "INTENT_SEARCH_SOURCES",
    "INTENT_SURNAME_BY_PLACE",
    "INTENT_SURNAME_LOOKUP",
    "INTENT_SURNAME_SOUNDEX_GROUPS",
    "INTENT_TOP_GIVEN_NAMES",
    "INTENT_TOP_SURNAMES",
    "INTENT_TREE_SUMMARY",
    "INTENT_UNSUPPORTED",
    "INTENT_HANDLERS",
    "IntentHandler",
    "SEARCH_INTENT_NAMES",
    "_clamp",
    "_string",
    "intent_catalog",
    "run_intent",
]
