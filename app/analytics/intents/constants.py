"""Intent name constants for NL search registry."""
from __future__ import annotations

INTENT_TOP_GIVEN_NAMES = "top_given_names"
INTENT_TOP_SURNAMES = "top_surnames"
INTENT_GIVEN_NAME_LOOKUP = "given_name_lookup"
INTENT_SURNAME_LOOKUP = "surname_lookup"
INTENT_NAMES_BY_DECADE = "names_by_decade"
INTENT_NAMES_BY_SEX = "names_by_sex"
INTENT_SURNAME_SOUNDEX_GROUPS = "surname_soundex_groups"
INTENT_TREE_SUMMARY = "tree_summary"
INTENT_UNSUPPORTED = "unsupported"
# Geography, vitals, events, lineage
INTENT_INDIVIDUALS_BY_LOCALITY = "individuals_by_locality"
INTENT_MARRIAGES_BY_PLACE = "marriages_by_place"
INTENT_INDIVIDUAL_EVENTS_BY_PLACE = "individual_events_by_place"
INTENT_INDIVIDUALS_AGE_AT_DEATH = "individuals_age_at_death"
INTENT_INDIVIDUALS_LIFESPAN_YEARS = "individuals_lifespan_years"
INTENT_INDIVIDUAL_ANCESTORS = "individual_ancestors"
INTENT_INDIVIDUAL_DESCENDANTS = "individual_descendants"
INTENT_INDIVIDUAL_COUSINS = "individual_cousins"
INTENT_RELATIONSHIP_BETWEEN = "relationship_between"
# Analytics (GEDCOM aggregates & place-linked rows)
INTENT_BORN_IN_PLACE = "born_in_place"
INTENT_DIED_IN_PLACE = "died_in_place"
INTENT_BORN_IN_DECADE = "born_in_decade"
INTENT_LIFESPAN_STATS = "lifespan_stats"
INTENT_LONGEST_LIVED = "longest_lived"
INTENT_LARGEST_FAMILIES = "largest_families"
INTENT_CAUSE_OF_DEATH = "cause_of_death"
INTENT_MIGRATION_PLACES = "migration_places"
INTENT_SURNAME_BY_PLACE = "surname_by_place"
INTENT_OCCUPATION_STATS = "occupation_stats"
INTENT_SEARCH_INDIVIDUALS = "search_individuals"
INTENT_SEARCH_FAMILIES = "search_families"
INTENT_SEARCH_EVENTS = "search_events"
INTENT_SEARCH_NOTES = "search_notes"
INTENT_SEARCH_SOURCES = "search_sources"
INTENT_SEARCH_MEDIA = "search_media"

SEARCH_INTENT_NAMES = frozenset(
    {
        INTENT_SEARCH_INDIVIDUALS,
        INTENT_SEARCH_FAMILIES,
        INTENT_SEARCH_EVENTS,
        INTENT_SEARCH_NOTES,
        INTENT_SEARCH_SOURCES,
        INTENT_SEARCH_MEDIA,
    }
)

