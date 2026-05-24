"""Central registry mapping intent names to handler callables.

Domain handlers live under ``places``, ``demographics``, ``relationships``,
``names``, and ``search``. NL keyword routing stays in ``app.services.nl_search``.
"""
from __future__ import annotations

from app.analytics.intents.types import IntentHandler
from app.analytics.intents.constants import *  # noqa: F403
from app.analytics.intents.names import handlers as name_handlers
from app.analytics.intents.places import handlers as place_handlers
from app.analytics.intents.demographics import handlers as demo_handlers
from app.analytics.intents.relationships import handlers as rel_handlers
from app.analytics.intents.search import handlers as search_handlers
from app.analytics.intents.fallback import _handle_unsupported

INTENT_HANDLERS: dict[str, IntentHandler] = {
    INTENT_TOP_GIVEN_NAMES: name_handlers._handle_top_given_names,
    INTENT_TOP_SURNAMES: name_handlers._handle_top_surnames,
    INTENT_GIVEN_NAME_LOOKUP: name_handlers._handle_given_name_lookup,
    INTENT_SURNAME_LOOKUP: name_handlers._handle_surname_lookup,
    INTENT_NAMES_BY_DECADE: name_handlers._handle_names_by_decade,
    INTENT_NAMES_BY_SEX: name_handlers._handle_names_by_sex,
    INTENT_SURNAME_SOUNDEX_GROUPS: name_handlers._handle_surname_soundex_groups,
    INTENT_TREE_SUMMARY: demo_handlers._handle_tree_summary,
    INTENT_INDIVIDUALS_BY_LOCALITY: place_handlers._handle_individuals_by_locality,
    INTENT_MARRIAGES_BY_PLACE: place_handlers._handle_marriages_by_place,
    INTENT_INDIVIDUAL_EVENTS_BY_PLACE: place_handlers._handle_individual_events_by_place,
    INTENT_INDIVIDUALS_AGE_AT_DEATH: demo_handlers._handle_individuals_age_at_death,
    INTENT_INDIVIDUALS_LIFESPAN_YEARS: demo_handlers._handle_individuals_lifespan_years,
    INTENT_INDIVIDUAL_ANCESTORS: rel_handlers._handle_individual_ancestors,
    INTENT_INDIVIDUAL_DESCENDANTS: rel_handlers._handle_individual_descendants,
    INTENT_INDIVIDUAL_COUSINS: rel_handlers._handle_individual_cousins,
    INTENT_RELATIONSHIP_BETWEEN: rel_handlers._handle_relationship_between,
    INTENT_BORN_IN_PLACE: place_handlers._handle_born_in_place,
    INTENT_DIED_IN_PLACE: place_handlers._handle_died_in_place,
    INTENT_BORN_IN_DECADE: demo_handlers._handle_born_in_decade,
    INTENT_LIFESPAN_STATS: demo_handlers._handle_lifespan_stats,
    INTENT_LONGEST_LIVED: demo_handlers._handle_longest_lived,
    INTENT_LARGEST_FAMILIES: demo_handlers._handle_largest_families,
    INTENT_CAUSE_OF_DEATH: demo_handlers._handle_cause_of_death,
    INTENT_MIGRATION_PLACES: place_handlers._handle_migration_places,
    INTENT_SURNAME_BY_PLACE: place_handlers._handle_surname_by_place,
    INTENT_OCCUPATION_STATS: demo_handlers._handle_occupation_stats,
    INTENT_SEARCH_INDIVIDUALS: search_handlers._handle_search_individuals,
    INTENT_SEARCH_FAMILIES: search_handlers._handle_search_families,
    INTENT_SEARCH_EVENTS: search_handlers._handle_search_events,
    INTENT_SEARCH_NOTES: search_handlers._handle_search_notes,
    INTENT_SEARCH_SOURCES: search_handlers._handle_search_sources,
    INTENT_SEARCH_MEDIA: search_handlers._handle_search_media,
    INTENT_UNSUPPORTED: _handle_unsupported,
}
