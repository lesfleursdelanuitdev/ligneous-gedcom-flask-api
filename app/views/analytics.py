"""Analytics endpoints — thin Flask routes over domain analytics services."""
from flask import Blueprint, jsonify, request

from app.services.analytics.dates import get_dates_statistics
from app.services.analytics.events import get_events_statistics
from app.services.analytics.families import get_families_statistics
from app.services.analytics.individuals import get_individuals_statistics
from app.services.analytics.media import get_media_statistics
from app.services.analytics.names import get_given_names_statistics, get_surnames_statistics
from app.services.analytics.notes import get_notes_statistics
from app.services.analytics.open_questions import get_open_questions_statistics
from app.services.analytics.places import get_places_statistics

bp = Blueprint("analytics", __name__, url_prefix="/api/research/trees")


@bp.route("/<tree_id>/analytics/given-names", methods=["GET"])
def given_names_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/given-names

    Returns statistics for given names: aggregates, top names, frequency distribution,
    optionally by decade and sex (for charts, force-directed graph data).
    """
    limit = min(int(request.args.get("limit", 50)), 200)
    payload = get_given_names_statistics(tree_id, limit)
    if payload is None:
        return jsonify({"error": "Tree not found"}), 404
    return jsonify(payload)


@bp.route("/<tree_id>/analytics/surnames", methods=["GET"])
def surnames_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/surnames

    Returns statistics for surnames: aggregates, top names, frequency distribution,
    optionally by decade (for charts, force-directed graph data).
    """
    limit = min(int(request.args.get("limit", 50)), 200)
    payload = get_surnames_statistics(tree_id, limit)
    if payload is None:
        return jsonify({"error": "Tree not found"}), 404
    return jsonify(payload)


@bp.route("/<tree_id>/analytics/individuals", methods=["GET"])
def individuals_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/individuals

    Aggregates from gedcom_individuals_v2: counts, sex, birth/decade histograms,
    age-at-death buckets, top birth countries.     family_roles uses
    gedcom_family_children_v2 (as child) and husband_id/wife_id on gedcom_families_v2
    (as spouse in a family). Lifespan uses age_at_death; ASSO count is
    gedcom_individual_associations_v2. Optional query param: top_n (default 10, max 50)
    for oldest_lived / youngest_died.
    """
    country_limit = min(int(request.args.get("country_limit", 20)), 100)
    top_n = min(int(request.args.get("top_n", 10)), 50)
    payload = get_individuals_statistics(tree_id, country_limit, top_n)
    if payload is None:
        return jsonify({"error": "Tree not found"}), 404
    return jsonify(payload)


@bp.route("/<tree_id>/analytics/families", methods=["GET"])
def families_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/families

    Aggregates from gedcom_families_v2 (partners, marriage year, children_count, divorce),
    junction counts, marriage place by country, child count min/max, non-biological
    parent–child links per family, families with a MARR event.
    """
    country_limit = min(int(request.args.get("country_limit", 15)), 50)
    payload = get_families_statistics(tree_id, country_limit)
    if payload is None:
        return jsonify({"error": "Tree not found"}), 404
    return jsonify(payload)


@bp.route("/<tree_id>/analytics/events", methods=["GET"])
def events_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/events

    Aggregates from gedcom_events_v2 + event_types / gedcom_event_event_types:
    friendly labels, standard vs custom instance breakdown, decade and country
    distributions, links to individuals/families and citations.

    Query params: type_limit, country_limit (optional caps).
    """
    type_limit = min(int(request.args.get("type_limit", 30)), 150)
    country_limit = min(int(request.args.get("country_limit", 15)), 50)
    payload = get_events_statistics(tree_id, type_limit, country_limit)
    if payload is None:
        return jsonify({"error": "Tree not found"}), 404
    return jsonify(payload)


@bp.route("/<tree_id>/analytics/places", methods=["GET"])
def places_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/places

    Aggregates from gedcom_places_v2 and references from individuals, families,
    events, and media-place links: coverage, usage by entity type, geographic
    distributions, and most-referenced places.

    Query params: top_limit, country_limit, state_limit (optional caps).
    """
    top_limit = min(int(request.args.get("top_limit", 25)), 150)
    country_limit = min(int(request.args.get("country_limit", 20)), 80)
    state_limit = min(int(request.args.get("state_limit", 20)), 80)
    payload = get_places_statistics(tree_id, top_limit, country_limit, state_limit)
    if payload is None:
        return jsonify({"error": "Tree not found"}), 404
    return jsonify(payload)


@bp.route("/<tree_id>/analytics/dates", methods=["GET"])
def dates_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/dates

    Aggregates from gedcom_dates_v2 and references from individuals, families,
    events, and media-date links: coverage, usage by entity type, qualifier
    (date_type) mix, calendar tag, year-by-decade, and most-referenced dates.

    Query params: top_limit, calendar_limit (optional caps).
    """
    top_limit = min(int(request.args.get("top_limit", 25)), 150)
    calendar_limit = min(int(request.args.get("calendar_limit", 15)), 50)
    payload = get_dates_statistics(tree_id, top_limit, calendar_limit)
    if payload is None:
        return jsonify({"error": "Tree not found"}), 404
    return jsonify(payload)


@bp.route("/<tree_id>/analytics/media", methods=["GET"])
def media_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/media

    GEDCOM media (gedcom_media_v2) for the tree: link counts, albums scoped to
    the tree, app tags on media, and ranked places, dates, individuals, families,
    and events by how many media links they have.

    Query param: top_n (default 10, max 40) for ranked lists and tag pie.
    """
    top_n = min(int(request.args.get("top_n", 10)), 40)
    payload = get_media_statistics(tree_id, top_n)
    if payload is None:
        return jsonify({"error": "Tree not found"}), 404
    return jsonify(payload)


@bp.route("/<tree_id>/analytics/open-questions", methods=["GET"])
def open_questions_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/open-questions

    Open questions for the GEDCOM file (open_questions.file_uuid): totals,
    resolved vs unresolved, and entities ranked by how many question links
    they have (individual, media, family, event).

    Query param: top_n (default 10, max 40).
    """
    top_n = min(int(request.args.get("top_n", 10)), 40)
    payload = get_open_questions_statistics(tree_id, top_n)
    if payload is None:
        return jsonify({"error": "Tree not found"}), 404
    return jsonify(payload)


@bp.route("/<tree_id>/analytics/notes", methods=["GET"])
def notes_statistics(tree_id: str):
    """
    GET /api/research/trees/<tree_id>/analytics/notes

    GEDCOM notes (gedcom_notes_v2): counts, link rows to individuals, families,
    events, and sources; top entities and notes by link volume.

    Query param: top_n (default 10, max 40).
    """
    top_n = min(int(request.args.get("top_n", 10)), 40)
    payload = get_notes_statistics(tree_id, top_n)
    if payload is None:
        return jsonify({"error": "Tree not found"}), 404
    return jsonify(payload)
