"""SQL-backed research analytics for trees, organized by genealogy domain."""

from app.services.analytics.dates import get_dates_statistics
from app.services.analytics.events import get_events_statistics
from app.services.analytics.families import get_families_statistics
from app.services.analytics.individuals import get_individuals_statistics
from app.services.analytics.media import get_media_statistics
from app.services.analytics.names import get_given_names_statistics, get_surnames_statistics
from app.services.analytics.notes import get_notes_statistics
from app.services.analytics.open_questions import get_open_questions_statistics
from app.services.analytics.places import get_places_statistics
from app.services.analytics.utils import (
    GEDCOM_EVENT_TAG_LABELS,
    friendly_event_label,
    get_file_uuid_for_tree,
)

__all__ = [
    "GEDCOM_EVENT_TAG_LABELS",
    "friendly_event_label",
    "get_file_uuid_for_tree",
    "get_dates_statistics",
    "get_events_statistics",
    "get_families_statistics",
    "get_given_names_statistics",
    "get_individuals_statistics",
    "get_media_statistics",
    "get_notes_statistics",
    "get_open_questions_statistics",
    "get_places_statistics",
    "get_surnames_statistics",
]
