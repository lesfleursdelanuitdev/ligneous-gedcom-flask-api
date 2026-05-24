"""Cross-cutting helpers for research analytics: tree→file UUID and GEDCOM event labels.

Used by domain modules under `app.services.analytics` so routes stay free of SQL
and label-mapping noise.
"""

from app.db import get_connection

# Display names when the DB stores the raw tag as `label` (unlinked rows / legacy).
GEDCOM_EVENT_TAG_LABELS: dict[str, str] = {
    "ADOP": "Adoption",
    "ANUL": "Annulment",
    "BAPM": "Baptism (LDS)",
    "BARM": "Bar mitzvah",
    "BASM": "Bas mitzvah",
    "BIRT": "Birth",
    "BLES": "Blessing",
    "BURI": "Burial",
    "CENS": "Census",
    "CHR": "Christening",
    "CHRA": "Adult christening",
    "CONF": "Confirmation",
    "CREM": "Cremation",
    "DEAT": "Death",
    "DIV": "Divorce",
    "DIVF": "Divorce filed",
    "EMIG": "Emigration",
    "ENGA": "Engagement",
    "EVEN": "Event",
    "FCOM": "First communion",
    "GRAD": "Graduation",
    "IMMI": "Immigration",
    "MARR": "Marriage",
    "MARB": "Marriage bann",
    "MARC": "Marriage contract",
    "MARL": "Marriage license",
    "MARS": "Marriage settlement",
    "NATU": "Naturalization",
    "ORDN": "Ordination",
    "PROB": "Probate",
    "PROP": "Property",
    "RELI": "Religion",
    "RESI": "Residence",
    "RETI": "Retirement",
    "WILL": "Will",
    "CUST": "Custom",
}


def friendly_event_label(tag: str | None, catalog_label: str | None) -> str:
    """Prefer catalog label; otherwise map common GEDCOM tags to plain language."""
    t = (tag or "").strip().upper()
    raw = (catalog_label or "").strip()
    if raw and raw.upper() != t:
        return raw
    return GEDCOM_EVENT_TAG_LABELS.get(t, raw or tag or "Unknown")


def get_file_uuid_for_tree(tree_id: str) -> str | None:
    """Resolve tree_id to gedcom file_uuid. Returns None if tree not found."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT gf.id AS file_uuid
                FROM trees t
                JOIN gedcom_files gf ON gf.file_id = t.file_id
                WHERE t.id = %s
                """,
                (tree_id,),
            )
            row = cur.fetchone()
            return row["file_uuid"] if row else None
