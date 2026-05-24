"""Lineage detection: directed pedigree traversal from surname-grouped founders."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

import networkx as nx
from psycopg2.extras import execute_values

from app.db import get_connection
from app.services.pedigree_graph import get_or_load_graph


# ── Helpers ────────────────────────────────────────────────────────────────────

def _lineage_hash(founder_ids: list[str]) -> str:
    raw = ",".join(sorted(founder_ids))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _top_n(items: list[str], n: int = 3) -> list[str]:
    freq: dict[str, int] = {}
    for item in items:
        freq[item] = freq.get(item, 0) + 1
    return [k for k, _ in sorted(freq.items(), key=lambda x: -x[1])[:n]]


# ── Public entry point ─────────────────────────────────────────────────────────

def detect_lineages(file_uuid: str, triggered_by: str = "manual") -> dict[str, Any]:
    """Compute lineages for *file_uuid* and persist results. Returns a summary dict."""
    run_id = _create_run(file_uuid, triggered_by)
    try:
        summary = _compute(file_uuid)
        _complete_run(run_id, summary)
        return summary
    except Exception as exc:
        _fail_run(run_id, str(exc))
        raise


# ── Run log helpers ────────────────────────────────────────────────────────────

def _create_run(file_uuid: str, triggered_by: str) -> str:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO lineage_runs (file_uuid, triggered_by)
                VALUES (%s, %s)
                RETURNING id::text
                """,
                (file_uuid, triggered_by),
            )
            return cur.fetchone()["id"]


def _complete_run(run_id: str, s: dict) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE lineage_runs
                SET completed_at     = NOW(),
                    total_lineages   = %s,
                    new_lineages     = %s,
                    merged_lineages  = %s,
                    updated_lineages = %s,
                    bridge_children  = %s
                WHERE id = %s
                """,
                (
                    s["totalLineages"], s["newLineages"], s["mergedLineages"],
                    s["updatedLineages"], s["bridgeChildren"], run_id,
                ),
            )


def _fail_run(run_id: str, message: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE lineage_runs SET completed_at = NOW(), error_message = %s WHERE id = %s",
                (message, run_id),
            )


# ── Core computation ───────────────────────────────────────────────────────────

def _compute(file_uuid: str) -> dict[str, Any]:
    # 1. Load founders (has_parents = false, known surname) + all individuals for stats
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id::text, primary_surname_lower, full_name, birth_year, death_year
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s
                  AND has_parents = false
                  AND primary_surname_lower IS NOT NULL
                  AND primary_surname_lower <> ''
                """,
                (file_uuid,),
            )
            founder_rows = cur.fetchall()

            cur.execute(
                """
                SELECT id::text, primary_surname_lower, birth_year, death_year
                FROM gedcom_individuals_v2
                WHERE file_uuid = %s
                """,
                (file_uuid,),
            )
            all_individuals = {row["id"]: row for row in cur.fetchall()}

    if not founder_rows:
        return {
            "totalLineages": 0, "newLineages": 0, "mergedLineages": 0,
            "updatedLineages": 0, "bridgeChildren": 0,
        }

    # 2. Group founders by surname
    founders_by_surname: dict[str, list] = defaultdict(list)
    for row in founder_rows:
        founders_by_surname[row["primary_surname_lower"]].append(row)

    # 3. Directed pedigree graph (parent → child)
    G = get_or_load_graph(file_uuid)

    # 4. Compute member set for each surname group via nx.descendants()
    member_sets: dict[str, set[str]] = {}
    for surname, founders in founders_by_surname.items():
        members: set[str] = set()
        for f in founders:
            fid = f["id"]
            members.add(fid)
            if fid in G:
                members.update(nx.descendants(G, fid))
        if len(members) >= 2:
            member_sets[surname] = members

    if not member_sets:
        return {
            "totalLineages": 0, "newLineages": 0, "mergedLineages": 0,
            "updatedLineages": 0, "bridgeChildren": 0,
        }

    # 5. Bridge children: individuals claimed by 2+ lineages
    individual_count: dict[str, int] = defaultdict(int)
    for members in member_sets.values():
        for mid in members:
            individual_count[mid] += 1
    bridge_child_ids = {mid for mid, cnt in individual_count.items() if cnt > 1}

    # 6. Load existing lineages for change detection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id::text, lineage_hash, size FROM lineages WHERE file_uuid = %s",
                (file_uuid,),
            )
            existing = {row["lineage_hash"]: row for row in cur.fetchall()}

    # 7. Prepare per-lineage data
    seen_hashes: set[str] = set()
    new_lineages = 0
    updated_lineages = 0
    lineage_payloads = []

    for surname, members in member_sets.items():
        founders = founders_by_surname[surname]
        founder_ids = [f["id"] for f in founders]
        lhash = _lineage_hash(founder_ids)
        seen_hashes.add(lhash)

        size = len(members)
        member_data = [all_individuals[mid] for mid in members if mid in all_individuals]

        all_surnames_list = [
            r["primary_surname_lower"] for r in member_data if r["primary_surname_lower"]
        ]
        top_surnames = _top_n(all_surnames_list, 3)

        years = [
            y for r in member_data
            for y in [r["birth_year"], r["death_year"]]
            if y is not None
        ]
        earliest_year = min(years) if years else None
        latest_year = max(years) if years else None

        prev = existing.get(lhash)
        if prev is None:
            new_lineages += 1
        elif prev["size"] != size:
            updated_lineages += 1

        lineage_payloads.append({
            "surname": surname,
            "members": members,
            "founder_ids": founder_ids,
            "hash": lhash,
            "size": size,
            "name": f"{surname.title()} lineage",
            "top_surnames": top_surnames,
            "earliest_year": earliest_year,
            "latest_year": latest_year,
        })

    # 8. Write: upsert lineages, replace individual_lineages, drop stale lineages
    merged_lineages = 0
    total_lineages = 0
    member_rows: list[tuple] = []

    with get_connection() as conn:
        with conn.cursor() as cur:
            for ld in lineage_payloads:
                cur.execute(
                    """
                    INSERT INTO lineages
                        (file_uuid, lineage_hash, name, surname, size,
                         founder_ids, top_surnames, earliest_year, latest_year, computed_at)
                    VALUES (%s, %s, %s, %s, %s, %s::uuid[], %s::text[], %s, %s, NOW())
                    ON CONFLICT (file_uuid, lineage_hash) DO UPDATE SET
                        name          = EXCLUDED.name,
                        surname       = EXCLUDED.surname,
                        size          = EXCLUDED.size,
                        founder_ids   = EXCLUDED.founder_ids,
                        top_surnames  = EXCLUDED.top_surnames,
                        earliest_year = EXCLUDED.earliest_year,
                        latest_year   = EXCLUDED.latest_year,
                        computed_at   = EXCLUDED.computed_at
                    RETURNING id::text
                    """,
                    (
                        file_uuid, ld["hash"], ld["name"], ld["surname"], ld["size"],
                        ld["founder_ids"], ld["top_surnames"],
                        ld["earliest_year"], ld["latest_year"],
                    ),
                )
                lineage_id = cur.fetchone()["id"]
                for mid in ld["members"]:
                    member_rows.append((file_uuid, mid, lineage_id, mid in bridge_child_ids))

            cur.execute(
                "DELETE FROM individual_lineages WHERE file_uuid = %s",
                (file_uuid,),
            )
            if member_rows:
                execute_values(
                    cur,
                    """
                    INSERT INTO individual_lineages
                        (file_uuid, individual_id, lineage_id, is_bridge_child)
                    VALUES %s
                    """,
                    member_rows,
                    template="(%s::uuid, %s::uuid, %s::uuid, %s)",
                )

            stale = [h for h in existing if h not in seen_hashes]
            merged_lineages = len(stale)
            if stale:
                cur.execute(
                    "DELETE FROM lineages WHERE file_uuid = %s AND lineage_hash = ANY(%s)",
                    (file_uuid, stale),
                )

            cur.execute(
                "SELECT COUNT(*) AS n FROM lineages WHERE file_uuid = %s",
                (file_uuid,),
            )
            total_lineages = cur.fetchone()["n"]

    return {
        "totalLineages": total_lineages,
        "newLineages": new_lineages,
        "mergedLineages": merged_lineages,
        "updatedLineages": updated_lineages,
        "bridgeChildren": len(bridge_child_ids),
    }
