"""LLM-facing intent documentation (params and examples)."""
from __future__ import annotations

from typing import Any

from app.analytics.intents.constants import *  # noqa: F403

def intent_catalog() -> dict[str, dict[str, Any]]:
    """Documented intent contract used to build the LLM system prompt and UI hints."""
    return {
        INTENT_TOP_GIVEN_NAMES: {
            "description": "Most common given (first) names in the tree.",
            "params": {"limit": "int (1-200, default 10)"},
            "examples": ["What are the most common first names?", "top 20 given names"],
        },
        INTENT_TOP_SURNAMES: {
            "description": "Most common surnames in the tree.",
            "params": {"limit": "int (1-200, default 10)"},
            "examples": ["Most popular surnames", "top 25 last names"],
        },
        INTENT_GIVEN_NAME_LOOKUP: {
            "description": "Find given names matching a substring (e.g. 'Maria').",
            "params": {"name": "string (required)", "limit": "int (1-200, default 20)"},
            "examples": ["how many people are named Maria", "given names containing Jose"],
        },
        INTENT_SURNAME_LOOKUP: {
            "description": "Find surnames matching a substring (e.g. 'Gonsalves').",
            "params": {"name": "string (required)", "limit": "int (1-200, default 20)"},
            "examples": ["surnames like Gonsalves", "search for last name Silva"],
        },
        INTENT_NAMES_BY_DECADE: {
            "description": "Top given-name popularity grouped by birth decade.",
            "params": {"top_names": "int (1-20, default 10)"},
            "examples": ["how have first names changed over time?", "names by decade"],
        },
        INTENT_NAMES_BY_SEX: {
            "description": "Top given names restricted to one sex (M or F).",
            "params": {"sex": "'M' or 'F' (default 'M')", "limit": "int (1-200, default 10)"},
            "examples": ["most common male first names", "popular female names"],
        },
        INTENT_SURNAME_SOUNDEX_GROUPS: {
            "description": "Phonetic surname clusters via Soundex (spelling variants).",
            "params": {"limit": "int (1-50, default 15)"},
            "examples": ["surname spelling variants", "phonetically similar last names"],
        },
        INTENT_TREE_SUMMARY: {
            "description": "High-level counts: individuals, unique given names, unique surnames.",
            "params": {},
            "examples": ["how big is the tree?", "tree overview"],
        },
        INTENT_INDIVIDUALS_BY_LOCALITY: {
            "description": "Individuals whose birth/death locality text matches (country, county, "
            "city string on individual rows); facet 'burial' scans BUR-type events.",
            "params": {
                "locality": "string (substring, required)",
                "facet": "birth | death | both | burial (default birth)",
                "primary_surname_substring": "optional filter on primary_surname_lower",
                "limit": "int (1-200)",
            },
            "examples": ["Who was born in Guyana?", "Who died in London?", "Buried in Toronto cemetery"],
        },
        INTENT_MARRIAGES_BY_PLACE: {
            "description": "Families whose marriage_place_display matches a locality substring.",
            "params": {"locality": "string (required)", "limit": "int"},
            "examples": ["Marriages in Toronto, Canada"],
        },
        INTENT_INDIVIDUAL_EVENTS_BY_PLACE: {
            "description": "Individual events tied to gedcom_events_v2 rows whose gedcom Places match.",
            "params": {
                "locality": "string (required)",
                "event_type_substring": "optional filter on event_type/custom_type",
                "limit": "int",
            },
            "examples": ["Baptisms in Lisbon", "Any event recorded in São Paulo"],
        },
        INTENT_INDIVIDUALS_AGE_AT_DEATH: {
            "description": "Individuals with known age_at_death compared to threshold.",
            "params": {
                "op": "lt | lte | gt | gte | eq",
                "age": "integer years (0–130)",
                "limit": "int",
            },
            "examples": ["Who died before age 70?"],
        },
        INTENT_INDIVIDUALS_LIFESPAN_YEARS: {
            "description": "Individuals whose inferred lifespan-years fall in a numeric band "
            "(prefers birth_year−death_year, else falls back to age_at_death).",
            "params": {"min_years": "int", "max_years": "int", "limit": "int"},
            "examples": ["People who lived between 80 and 90 years"],
        },
        INTENT_INDIVIDUAL_ANCESTORS: {
            "description": "Recursive ancestors via gedcom_parent_child_v2.",
            "params": {
                "xref": "GEDCOM xref (preferred)",
                "name": "full_name substring fallback (single fuzzy match)",
                "max_generations": "cap",
                "limit": "max rows returned",
            },
            "examples": ["Ancestors of @I123@"],
        },
        INTENT_INDIVIDUAL_DESCENDANTS: {
            "description": "Recursive descendants down parent→child edges.",
            "params": {
                "xref": "GEDCOM xref (preferred)",
                "name": "full_name substring fallback",
                "max_generations": "cap",
                "limit": "max rows returned",
            },
            "examples": ["All descendants of John Smith Sr."],
        },
        INTENT_INDIVIDUAL_COUSINS: {
            "description": "First cousins: children of parents' siblings of the anchor (pedigree graph).",
            "params": {
                "xref": "GEDCOM xref (preferred)",
                "name": "full_name substring fallback",
                "limit": "max rows returned",
            },
            "examples": ["First cousins of Mary Jones"],
        },
        INTENT_RELATIONSHIP_BETWEEN: {
            "description": "NetworkX shortest-path relationship between two people using gedcom_parent_child_v2 "
            "(ancestor/descendant, collateral via lowest common ancestor, or unrelated subgraphs).",
            "params": {
                "source_xref": "optional if source_name set",
                "source_name": "full_name substring (single fuzzy match)",
                "target_xref": "optional if target_name set",
                "target_name": "full_name substring (single fuzzy match)",
            },
            "examples": [
                "Relationship between @I1@ and @I2@",
                "How are Anne Smith and John Brown related?",
            ],
        },
        INTENT_BORN_IN_PLACE: {
            "description": "Individuals whose birth_place_display matches a place substring.",
            "params": {"place": "string (required, ILIKE %place%)", "limit": "int (default 20, max 200)"},
            "examples": ["Who was born in Guyana?", "people born in Trinidad"],
        },
        INTENT_DIED_IN_PLACE: {
            "description": "Individuals whose death_place_display matches a place substring.",
            "params": {"place": "string (required)", "limit": "int (default 20, max 200)"},
            "examples": ["Who died in Canada?", "deaths in Georgetown"],
        },
        INTENT_BORN_IN_DECADE: {
            "description": "Individuals with birth_year inside [decade, decade+10).",
            "params": {"decade": "int (required, e.g. 1880)", "limit": "int (default 20, max 200)"},
            "examples": ["people born in the 1880s"],
        },
        INTENT_LIFESPAN_STATS: {
            "description": "Aggregate avg/min/max/count of age_at_death (0–120) on gedcom_individuals_v2.",
            "params": {},
            "examples": ["average lifespan", "life expectancy at death"],
        },
        INTENT_LONGEST_LIVED: {
            "description": "Individuals ordered by age_at_death descending (non-null, 0–120).",
            "params": {"limit": "int default 10, max 50"},
            "examples": ["who lived the longest", "oldest people in the tree"],
        },
        INTENT_LARGEST_FAMILIES: {
            "description": "Families with children_count > 0, ordered by children_count descending (xrefs only).",
            "params": {"limit": "int default 10, max 50"},
            "examples": ["biggest families", "most children"],
        },
        INTENT_CAUSE_OF_DEATH: {
            "description": "Top causes from gedcom_events_v2 rows with event_type = DEAT and non-empty cause.",
            "params": {"limit": "int default 15, max 50"},
            "examples": ["common causes of death", "what did people die of"],
        },
        INTENT_MIGRATION_PLACES: {
            "description": "Top birth_country values on individuals (non-empty).",
            "params": {"limit": "int default 15, max 50"},
            "examples": ["where did people come from", "migration origins"],
        },
        INTENT_SURNAME_BY_PLACE: {
            "description": "Top surnames for individuals whose birth place or birth country matches a needle.",
            "params": {"place": "string (required)", "limit": "int default 10, max 50"},
            "examples": ["surnames common in Guyana"],
        },
        INTENT_OCCUPATION_STATS: {
            "description": "Top occupation strings on gedcom_individuals_v2 (non-empty).",
            "params": {"limit": "int default 15, max 50"},
            "examples": ["occupations in the tree", "common jobs"],
        },
        INTENT_SEARCH_INDIVIDUALS: {
            "description": "Filter individuals via allow-listed columns only (ILIKE substrings where noted).",
            "params": {
                "given_name": "substring → full_name_lower",
                "surname": "substring → primary_surname_lower",
                "birth_place": "birth_place_display",
                "death_place": "death_place_display",
                "birth_decade": "int",
                "death_decade": "int",
                "sex": "M|F|U|X",
                "is_living": "bool",
                "occupation": "substring",
                "nationality": "substring",
                "limit": "int default 20 max 200",
            },
            "examples": ["Find males named Silva born in the 1890s"],
        },
        INTENT_SEARCH_FAMILIES: {
            "description": "Filter gedcom_families_v2 via allow-listed fields and partner surname subquery.",
            "params": {
                "partner_surname": "gedcom_family_surnames_v2 + surnames",
                "marriage_place": "marriage_place_display",
                "marriage_decade": "int → marriage_year window",
                "min_children": "int",
                "is_divorced": "bool",
                "limit": "int",
            },
            "examples": ["Families with surname Pereira tied to the union"],
        },
        INTENT_SEARCH_EVENTS: {
            "description": "Filter gedcom_events_v2 with optional gedcom_dates_v2 / gedcom_places_v2 joins.",
            "params": {
                "event_type": "substring (e.g. DEAT, BIRT, MARR)",
                "place": "places.original",
                "decade": "int → event date year window",
                "cause": "substring",
                "limit": "int",
            },
            "examples": ["IMMIG events in the 1920s"],
        },
        INTENT_SEARCH_NOTES: {
            "description": "Search gedcom_notes_v2 note text.",
            "params": {"text": "string (required)", "is_top_level": "bool", "limit": "int"},
            "examples": ["Notes mentioning Georgetown"],
        },
        INTENT_SEARCH_SOURCES: {
            "description": "Search gedcom_sources_v2.",
            "params": {"title": "substring", "author": "substring", "text": "substring (text column)", "limit": "int"},
            "examples": ["Sources by author …"],
        },
        INTENT_SEARCH_MEDIA: {
            "description": "Search gedcom_media_v2.",
            "params": {"title": "substring", "description": "substring", "form": "substring (jpg/pdf/…)", "limit": "int"},
            "examples": ["Find photos"],
        },
        INTENT_UNSUPPORTED: {
            "description": "Fallback when the user's question cannot be answered.",
            "params": {"reason": "string (optional explanation)"},
            "examples": [],
        },
    }
