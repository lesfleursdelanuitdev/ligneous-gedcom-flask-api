"""Unit tests for the NL search service (LLM-free paths)."""
from unittest.mock import patch

from app.services import nl_search
from app.services import intents
from app.services.intents import (
    INTENT_BORN_IN_DECADE,
    INTENT_BORN_IN_PLACE,
    INTENT_CAUSE_OF_DEATH,
    INTENT_DIED_IN_PLACE,
    INTENT_GIVEN_NAME_LOOKUP,
    INTENT_LARGEST_FAMILIES,
    INTENT_LIFESPAN_STATS,
    INTENT_LONGEST_LIVED,
    INTENT_MIGRATION_PLACES,
    INTENT_NAMES_BY_DECADE,
    INTENT_NAMES_BY_SEX,
    INTENT_OCCUPATION_STATS,
    INTENT_RELATIONSHIP_BETWEEN,
    INTENT_SEARCH_MEDIA,
    INTENT_SEARCH_NOTES,
    INTENT_SEARCH_SOURCES,
    INTENT_SEARCH_INDIVIDUALS,
    INTENT_SURNAME_BY_PLACE,
    INTENT_SURNAME_LOOKUP,
    INTENT_SURNAME_SOUNDEX_GROUPS,
    INTENT_TOP_GIVEN_NAMES,
    INTENT_TOP_SURNAMES,
    INTENT_TREE_SUMMARY,
    INTENT_UNSUPPORTED,
    intent_catalog,
)


def test_keyword_fallback_routes_summary():
    out = nl_search._keyword_fallback("how big is the tree?")
    assert out["intent"] == INTENT_TREE_SUMMARY
    assert out["source"] == "keyword"


def test_keyword_fallback_routes_top_surnames():
    out = nl_search._keyword_fallback("most popular last names")
    assert out["intent"] == INTENT_TOP_SURNAMES
    assert out["params"]["limit"] == 10


def test_keyword_fallback_routes_top_given_names():
    out = nl_search._keyword_fallback("top 25 first names")
    assert out["intent"] == INTENT_TOP_GIVEN_NAMES


def test_keyword_fallback_routes_decade_trend():
    out = nl_search._keyword_fallback("how have first names changed by decade?")
    assert out["intent"] == INTENT_NAMES_BY_DECADE


def test_keyword_fallback_routes_male_names():
    out = nl_search._keyword_fallback("most common male names")
    assert out["intent"] == INTENT_NAMES_BY_SEX
    assert out["params"]["sex"] == "M"


def test_keyword_fallback_routes_female_names():
    out = nl_search._keyword_fallback("popular female names")
    assert out["intent"] == INTENT_NAMES_BY_SEX
    assert out["params"]["sex"] == "F"


def test_keyword_analytics_born_in_place():
    out = nl_search._keyword_fallback("people born in Trinidad")
    assert out["intent"] == INTENT_BORN_IN_PLACE
    assert out["params"]["place"] == "trinidad"


def test_keyword_analytics_birth_place_phrase():
    out = nl_search._keyword_fallback("birthplace in Barbados")
    assert out["intent"] == INTENT_BORN_IN_PLACE
    assert out["params"]["place"] == "barbados"


def test_keyword_analytics_died_in_place():
    out = nl_search._keyword_fallback("who died in Canada?")
    assert out["intent"] == INTENT_DIED_IN_PLACE
    assert out["params"]["place"] == "canada"


def test_keyword_analytics_deaths_in_place_alias():
    out = nl_search._keyword_fallback("deaths in Georgetown")
    assert out["intent"] == INTENT_DIED_IN_PLACE


def test_keyword_analytics_born_in_decade():
    out = nl_search._keyword_fallback("people born in the 1880s")
    assert out["intent"] == INTENT_BORN_IN_DECADE
    assert out["params"]["decade"] == 1880


def test_keyword_analytics_static_lifespan_stats():
    out = nl_search._keyword_fallback("average lifespan in our tree")
    assert out["intent"] == INTENT_LIFESPAN_STATS


def test_keyword_analytics_static_longest_lived():
    out = nl_search._keyword_fallback("who lived the longest")
    assert out["intent"] == INTENT_LONGEST_LIVED
    assert out["params"]["limit"] == 10


def test_keyword_analytics_static_largest_families():
    out = nl_search._keyword_fallback("biggest families in the genealogy")
    assert out["intent"] == INTENT_LARGEST_FAMILIES


def test_keyword_analytics_static_cause_of_death():
    out = nl_search._keyword_fallback("what did people die of")
    assert out["intent"] == INTENT_CAUSE_OF_DEATH


def test_keyword_analytics_static_migration_places():
    out = nl_search._keyword_fallback("migration origins")
    assert out["intent"] == INTENT_MIGRATION_PLACES


def test_keyword_analytics_surname_by_place():
    out = nl_search._keyword_fallback("what surnames are common in Guyana")
    assert out["intent"] == INTENT_SURNAME_BY_PLACE
    assert out["params"]["place"] == "guyana"


def test_keyword_spec_born_guyana_who():
    out = nl_search._keyword_fallback("Who was born in Guyana?")
    assert out["intent"] == INTENT_BORN_IN_PLACE
    assert out["params"]["place"] == "guyana"


def test_keyword_spec_died_canada():
    out = nl_search._keyword_fallback("Who died in Canada?")
    assert out["intent"] == INTENT_DIED_IN_PLACE
    assert out["params"]["place"] == "canada"


def test_keyword_spec_average_lifespan_phrase():
    out = nl_search._keyword_fallback("What was the average lifespan?")
    assert out["intent"] == INTENT_LIFESPAN_STATS


def test_keyword_spec_largest_families_wording():
    out = nl_search._keyword_fallback("Which families had the most children?")
    assert out["intent"] == INTENT_LARGEST_FAMILIES


def test_keyword_spec_migration_where_from():
    out = nl_search._keyword_fallback("Where did people come from?")
    assert out["intent"] == INTENT_MIGRATION_PLACES


def test_keyword_spec_occupation_stats():
    out = nl_search._keyword_fallback("What occupations are in the tree?")
    assert out["intent"] == INTENT_OCCUPATION_STATS


def test_keyword_spec_search_individuals_named():
    out = nl_search._keyword_fallback("Find people named Gonsalves")
    assert out["intent"] == INTENT_SEARCH_INDIVIDUALS
    assert out["params"]["surname"] == "gonsalves"


def test_keyword_spec_search_notes_containing():
    out = nl_search._keyword_fallback("Find notes containing Georgetown")
    assert out["intent"] == INTENT_SEARCH_NOTES
    assert "georgetown" in out["params"]["text"].lower()


def test_keyword_spec_search_sources_by_author():
    out = nl_search._keyword_fallback("Search sources by author National Archives")
    assert out["intent"] == INTENT_SEARCH_SOURCES
    assert "national archives" in out["params"]["author"].lower()


def test_keyword_spec_search_media_photos():
    out = nl_search._keyword_fallback("Find photos")
    assert out["intent"] == INTENT_SEARCH_MEDIA


def test_keyword_relationship_between():
    out = nl_search._keyword_fallback("Relationship between Anne Smith and John Brown?")
    assert out["intent"] == INTENT_RELATIONSHIP_BETWEEN
    assert "anne smith" in (out["params"].get("source_name") or "").lower()
    assert "john brown" in (out["params"].get("target_name") or "").lower()


def test_keyword_how_are_related():
    out = nl_search._keyword_fallback("How are Carlos and Maria related")
    assert out["intent"] == INTENT_RELATIONSHIP_BETWEEN


def test_keyword_fallback_routes_soundex():
    out = nl_search._keyword_fallback("show phonetic spelling variants")
    assert out["intent"] == INTENT_SURNAME_SOUNDEX_GROUPS


def test_keyword_fallback_routes_surname_lookup():
    out = nl_search._keyword_fallback("surnames like Gonsalves")
    assert out["intent"] == INTENT_SURNAME_LOOKUP
    assert out["params"]["name"].lower().startswith("gonsalves")


def test_keyword_fallback_routes_given_lookup():
    out = nl_search._keyword_fallback("first names like Maria")
    assert out["intent"] == INTENT_GIVEN_NAME_LOOKUP
    assert out["params"]["name"].lower().startswith("maria")


def test_keyword_fallback_unsupported_for_unrelated():
    out = nl_search._keyword_fallback("what is the weather today?")
    assert out["intent"] == INTENT_UNSUPPORTED


def test_normalize_intent_rejects_unknown_intent():
    routed = {"intent": "make_up_query", "params": {}, "confidence": 0.9}
    out = nl_search._normalize_intent(routed)
    assert out["intent"] == INTENT_UNSUPPORTED
    assert "unknown intent" in out["params"]["reason"].lower()


def test_normalize_intent_passes_through_known_intent():
    routed = {"intent": INTENT_TOP_SURNAMES, "params": {"limit": 5}, "confidence": 0.7}
    out = nl_search._normalize_intent(routed)
    assert out["intent"] == INTENT_TOP_SURNAMES
    assert out["params"] == {"limit": 5}
    assert out["confidence"] == 0.7


def test_normalize_intent_handles_non_dict_params():
    routed = {"intent": INTENT_TREE_SUMMARY, "params": "oops", "confidence": 0.3}
    out = nl_search._normalize_intent(routed)
    assert out["params"] == {}


def test_result_count_lists_take_length():
    assert nl_search._result_count(INTENT_TOP_SURNAMES, {"top_surnames": [1, 2, 3]}) == 3
    assert nl_search._result_count(INTENT_NAMES_BY_DECADE, {"by_decade": []}) == 0


def test_result_count_summary_counts_one():
    assert nl_search._result_count(INTENT_TREE_SUMMARY, {"summary": {"a": 1}}) == 1


def test_result_count_returns_none_when_unknown_shape():
    assert nl_search._result_count("anything", {"foo": "bar"}) is None


def test_system_prompt_lists_all_intents():
    prompt = nl_search._build_system_prompt()
    for intent in intent_catalog().keys():
        assert intent in prompt
    assert set(intent_catalog().keys()) == set(intents.INTENT_HANDLERS.keys())
    assert "Output ONLY a JSON object" in prompt


def test_run_nl_search_skip_persistence_when_requested():
    """Read-only callers should omit research.* INSERTs."""

    routed = {"intent": INTENT_TREE_SUMMARY, "params": {}, "confidence": 1.0, "source": "test"}

    with (
        patch.object(nl_search, "_resolve_file_uuid", return_value="file-uuid"),
        patch.object(nl_search, "_call_groq", return_value=routed),
        patch.object(nl_search, "run_intent") as mock_run_intent,
        patch.object(nl_search, "record_run") as mock_record_run,
        patch.object(nl_search, "record_result") as mock_record_result,
    ):
        mock_run_intent.return_value = {"ok": True, "result": {"summary": {"individuals": 1}}}
        out = nl_search.run_nl_search(tree_id="t1", query="overview", persist_runs=False)
        mock_record_run.assert_not_called()
        mock_record_result.assert_not_called()
        assert out["meta"]["persisted"] is False
        assert out["meta"]["run_id"] is None
