# Statistics Backend (Python Layer) — Refactoring Plan

**Date:** 2026-06-03
**Scope:** `ligneous-python-api` — the analytics/statistics Python layer
**Type:** Behavior-preserving refactor (with a few intentional consistency changes, called out explicitly)

---

## 1. Context

The statistics backend is **two layers that share concerns**:

- **Domain services** — `app/services/analytics/*` (~2,260 LOC, 10 modules). Power the **statistics dashboard** via Flask routes `GET /<tree_id>/analytics/{given-names, surnames, individuals, families, events, places, dates, media, notes, open-questions}` (`app/views/analytics.py`, ~192 LOC). Consumed by the frontend `StatisticsAnalyticsEnginePreview`.
- **NL intent handlers** — `app/analytics/intents/**` (~1,490 LOC, 31 handlers across `names/ places/ demographics/ relationships/ search/`). Power the AI/NL search via `registry.py` → `router.py`, documented by `catalog.py`. Consumed by the frontend NL search.

Both layers hit the same tables with the same `get_connection()` context manager and the same `%s`-parameterized SQL, and both return untyped `dict[str, Any]`.

### What is already good (do NOT refactor)
- **DB connection** (`app/db.py`) — clean context manager, commit/rollback/close, `RealDictCursor`. Keep.
- **Parameter escaping** (`intents/utils.py` `_ilike_pattern`) — correct LIKE-metachar escaping. Keep, standardize *on* it.
- **Intent registry/routing/catalog** — clean name→handler dispatch with a documented param contract. Keep the shape; tidy contents.
- **Anchor resolution** (`intents/utils.py` `_resolve_anchor_individual_id`) — xref-first then fuzzy name, with ambiguity detection. Keep.
- **Domain-service module split** (one entry point per genealogy domain). Keep the split; reduce its internal duplication.

---

## 2. Goals & principles

1. **Behavior-preserving by default.** The dashboard and NL responses must not change shape unless a change is explicitly listed and frontend-coordinated.
2. **Incremental, independently shippable phases.** Each phase compiles, passes tests, and can merge alone.
3. **Test-guarded.** Establish characterization tests *before* touching logic.
4. **Don't re-introduce Python-side display formatting.** Display formatting now lives on the frontend (`lib/analytics-format.ts`, `nlSearchIntentSummary.ts`). The backend should emit **raw values** (+ optional stable `*_label` where the frontend can't infer them). Refactors must not add cosmetic string-shaping back into Python.
5. **Preserve the recently-tuned limits.** The completeness/pagination work set match/search/list intents to `default=max_rows` and kept top-N/aggregates small (`NL_MAX_ROWS=2000`). The limits-centralization phase must reproduce these exact values.

---

## 3. Refactoring smell inventory (evidence-backed)

| # | Smell | Severity | Evidence |
|---|---|---|---|
| S1 | **7 intent handlers duplicated** across `demographics/handlers.py` and `places/handlers.py`; one copy of each is **dead code** | Critical | `registry.py:37–43` registers 5 from `demo_handlers` (`born_in_decade, lifespan_stats, longest_lived, largest_families, cause_of_death`) and 2 from `place_handlers` (`migration_places, surname_by_place`). The non-registered copies (5 in `places/`, 2 in `demographics/`) are unreachable. |
| S2 | `_sex_code_from_param` defined twice, identically | Medium | `intents/utils.py:118` and `intents/search/handlers.py:82` |
| S3 | **Scattered limits/defaults** — no single source | High | Routes use `min(request.args..., N)` (`views/analytics.py`); handlers use `_clamp(..., default=…)` with per-intent values (`names/handlers.py:11,50`, `demographics/handlers.py:108`, `search/handlers.py:11`) |
| S4 | **Row→dict boilerplate** `[dict(r) for r in cur.fetchall()]` ~52× | Medium | Every SQL module |
| S5 | **Decade-bucket SQL** copy-pasted ~8× | Medium | `FLOOR(col/10)*10` in `individuals.py`, `names.py`, `families.py`, `events.py`, `places.py`, `dates.py` |
| S6 | **Inconsistent result envelopes** — `matches` vs `top_given_names` vs `countries` vs `surnames`; `note` sometimes present/`None`/absent | High | `names/handlers.py:25,43`, `search/handlers.py:79`, `places/handlers.py:203,394,432` |
| S7 | **Inconsistent error/empty signaling** — `note` vs `ambiguous_anchor` vs empty list; "no data" indistinguishable from failure | Medium | `relationships/handlers.py:18–26`, `places/handlers.py:14`, `demographics/handlers.py:94` |
| S8 | **No result schemas** — everything `dict[str, Any]`; `services/analytics/types.py` is a 1-line stub | High | `services/analytics/types.py`, all handlers |
| S9 | **Mixed concerns per handler** — param validation + SQL string-building + connection + row-mapping + envelope all inline | High | e.g. `places/handlers.py:10–112` |
| S10 | **Inconsistent matching** — one handler uses `LIKE`/inline `%…%` instead of `ILIKE … ESCAPE` via `_ilike_pattern` | Medium | `search/handlers.py:149–151` vs the standard helper |
| S11 | **Thin tests** — only `tests/test_intents.py` (~35 LOC) validates catalog/registry + helpers; no handler/SQL coverage, no fixtures | High | `tests/` |

---

## 4. Target architecture

Introduce a small **shared kernel** under `app/analytics/_core/` (new) used by both layers; keep the domain modules and registry where they are.

```
app/analytics/_core/
  db.py            # re-export get_connection (or thin helpers)
  fetch.py         # fetch_dicts(cur, sql, args) -> list[dict]; fetch_one_dict(...)
  sql.py           # decade_bucket(col), where_builder / clause helpers, ILIKE pattern (re-export)
  params.py        # _clamp, _string, _ilike_pattern, _sex_code_from_param  (single home — S2)
  limits.py        # INTENT_LIMITS registry: per-intent {default, lo, hi}     (S3)
  envelope.py      # result/error envelope builders + TypedDicts             (S6, S7, S8)
```

- **`params.py`** absorbs the duplicated helpers (S2) and becomes the only import site.
- **`limits.py`** is the single source for every default/cap, reproducing today's tuned values (top-N small; match/search `default=max_rows`; `NL_MAX_ROWS` cap). Routes and handlers read from it.
- **`fetch.py` / `sql.py`** remove S4/S5 boilerplate behind tiny, well-tested helpers.
- **`envelope.py`** defines a consistent shape (additive — see Phase 5) and `TypedDict`s so result keys are documented.

This is deliberately **lightweight** — helper modules, not a heavy ORM/repository framework. A full repository/DAO layer is explicitly deferred (Phase 7, optional).

---

## 5. Phased plan

Ordered by risk-adjusted value. Each phase is independently shippable.

### Phase 0 — Safety net (do first)
- **Objective:** characterization tests so later phases are provably behavior-preserving.
- **Changes:** add `tests/` coverage that runs every intent handler and every analytics service against a small **seeded fixture tree** (or a recorded-DB fixture), snapshotting result dicts (golden files). Also a registry/catalog drift test extension that asserts every registered handler is importable and every catalog param is consumed.
- **Files:** `tests/` (new fixtures + golden snapshots), CI wiring.
- **Risk:** none (additive). **Size:** M.
- **Acceptance:** `pytest` green; golden snapshots captured for all 31 intents + 10 services.

### Phase 1 — Delete dead duplicate handlers (S1, S2)
- **Objective:** remove the 7 unreachable handler copies and the duplicate `_sex_code_from_param`.
- **Changes:** delete the **non-registered** copies — the `places/` copies of `born_in_decade, lifespan_stats, longest_lived, largest_families, cause_of_death`, and the `demographics/` copies of `migration_places, surname_by_place`. Re-point `search/handlers.py` to import `_sex_code_from_param` from `params.py`.
- **Files:** `places/handlers.py`, `demographics/handlers.py`, `search/handlers.py`, `_core/params.py`.
- **Risk:** low — guarded by Phase 0 snapshots; registry already names the surviving copy. Verify no cross-imports of the deleted symbols first.
- **Size:** S. **Win:** ~270 LOC removed, eliminates drift between live/dead copies.
- **Acceptance:** snapshots unchanged; `grep` shows no references to deleted functions.

### Phase 2 — Centralize limits/defaults (S3)
- **Objective:** one `INTENT_LIMITS` (and route-limits) registry; reproduce current values exactly.
- **Changes:** add `_core/limits.py`; replace per-handler `_clamp(params.get("limit"), default=…, lo=…, hi=…)` and per-route `min(args, N)` with lookups. **Must preserve:** top-N defaults (10/15/20), match/search `default=max_rows`, the `min(50/200, max_rows)` caps, and `NL_MAX_ROWS`.
- **Files:** `_core/limits.py`, all `*/handlers.py`, `views/analytics.py`, `config.py`.
- **Risk:** low/medium — behavior-preserving but touches many call sites; snapshots catch regressions.
- **Size:** M. **Acceptance:** snapshots unchanged; a single file now tunes every limit.

### Phase 3 — Extract query/row helpers (S4, S5, S10)
- **Objective:** kill the repeated `dict(r)` mapping, the decade-bucket SQL, and the `LIKE` outlier.
- **Changes:** `fetch_dicts`/`fetch_one_dict` in `_core/fetch.py`; `decade_bucket(col)` and a small clause helper in `_core/sql.py`; convert the inline `LIKE`/`%…%` in `search/handlers.py:149` to the standard `ILIKE … ESCAPE` + `_ilike_pattern`.
- **Files:** `_core/fetch.py`, `_core/sql.py`, all SQL modules (mechanical), `search/handlers.py`.
- **Risk:** low — pure extraction; the `LIKE→ILIKE` change is a deliberate consistency fix (case-insensitive) — call it out and snapshot-diff it.
- **Size:** M. **Acceptance:** snapshots unchanged except the documented `LIKE→ILIKE` case-sensitivity normalization.

### Phase 4 — Split SQL from shaping per handler (S9)
- **Objective:** within each handler, separate (a) param parsing/validation, (b) SQL+args construction, (c) execution via `fetch_*`, (d) envelope. Not a new layer — just consistent internal structure.
- **Changes:** refactor handlers to a common skeleton (parse → build → fetch → shape). Start with the worst offenders (`places/handlers.py:10–112` locality; `search/handlers.py`).
- **Files:** all `*/handlers.py` (incremental, handler-by-handler).
- **Risk:** low/medium — most error-prone; do per-handler with snapshot guard.
- **Size:** L. **Acceptance:** snapshots unchanged; handlers read uniformly.

### Phase 5 — Result + error envelope & schemas (S6, S7, S8) — *frontend-coordinated*
- **Objective:** consistent, documented result/error shapes + `TypedDict`s.
- **Approach (non-breaking):** keep existing per-intent keys (`matches`, `top_surnames`, …) but (1) standardize the **error/empty** signal into one envelope field (e.g. always `status`/`note`), (2) add `TypedDict`s in `_core/envelope.py` + `services/analytics/types.py` documenting each shape, (3) optionally wrap responses in a thin envelope **additively** behind a version flag so the frontend can migrate.
- **Files:** `_core/envelope.py`, `services/analytics/types.py`, handlers/services, **and** frontend consumers (`NlSearchResult.tsx`, `StatisticsAnalyticsEnginePreview.tsx`) for any consumed change.
- **Risk:** **medium/high** — the only cross-layer phase. Gate behind tests on both sides; ship backend-additive first, migrate frontend, then remove old shape.
- **Size:** L. **Acceptance:** both layers green; result shapes documented by types; error signaling uniform.

### Phase 6 — Test expansion (S11)
- **Objective:** raise handler/service coverage beyond catalog validation; add param-edge and empty-data cases on top of Phase 0 goldens.
- **Files:** `tests/`.
- **Risk:** none. **Size:** M.

### Phase 7 — (Optional) repository/query layer
- **Objective:** if churn justifies it, extract a thin per-domain query module so handlers call `repo.individuals_by_locality(...)` instead of embedding SQL.
- **Risk/size:** L — **deferred**; only if Phases 1–5 reveal enough repeated query shapes to warrant it. Do not start speculatively.

---

## 6. Sequencing & priority

| Order | Phase | Value | Risk | Size |
|---|---|---|---|---|
| 1 | P0 Safety net | Enables everything | none | M |
| 2 | P1 Delete dead code | High (−270 LOC, kills drift) | low | S |
| 3 | P2 Limits registry | High (tunability) | low | M |
| 4 | P3 Query/row helpers | Medium (−boilerplate) | low | M |
| 5 | P4 Handler skeleton | Medium (readability/testability) | low/med | L |
| 6 | P5 Envelope + schemas | High (contract clarity) | med/high (cross-layer) | L |
| 7 | P6 Tests | High (durability) | none | M |
| 8 | P7 Repository | Optional | — | L |

**Recommended first slice:** P0 → P1 → P2. Highest value, lowest risk, no frontend coordination, and it removes the most code.

---

## 7. Risks & mitigations

- **Hidden behavior change during dedup/extraction** → Phase 0 golden snapshots over all intents+services; diff every phase.
- **Limit regressions** → Phase 2 must reproduce the exact post-completeness-work values; assert them in tests.
- **Cross-layer break in Phase 5** → make backend changes additive/versioned; migrate frontend before removing old shape; both-sides tests.
- **No live test DB in CI** → invest in a seeded fixture tree (or recorded fixtures) in Phase 0; this is a prerequisite, not optional.
- **Re-adding Python formatting** → explicitly out of scope (principle #4); reviewers reject cosmetic string-shaping.

---

## 8. Out of scope
- New analytics intents or new filter params (tracked separately in `the-gonsalves-family/docs/NL_SEARCH_VS_ADVANCED_SEARCH_AUDIT.md`).
- Display formatting (lives on the frontend now).
- DB schema / denormalization changes.
- Switching DB driver, adding connection pooling, or async.

---

## 9. Appendix — evidence

**Dead duplicate handlers to delete (Phase 1):**
- In `places/handlers.py`: `_handle_born_in_decade`, `_handle_lifespan_stats`, `_handle_longest_lived`, `_handle_largest_families`, `_handle_cause_of_death` (registry uses the `demographics/` copies — `registry.py:37–41`).
- In `demographics/handlers.py`: `_handle_migration_places`, `_handle_surname_by_place` (registry uses the `places/` copies — `registry.py:42–43`).

**Duplicate helper:** `_sex_code_from_param` — `intents/utils.py:118` and `intents/search/handlers.py:82`.

**Module map (LOC approx):**
- Services: `individuals.py` 344, `names.py` 330, `media.py` 282, `notes.py` 257, `events.py` 225, `dates.py` 200, `families.py` 192, `places.py` 177, `open_questions.py` 145, `utils.py` 73.
- Intents: `places/handlers.py` 432, `demographics/handlers.py` 311, `search/handlers.py` 277, `relationships/handlers.py` 229, `names/handlers.py` 174; `catalog.py` 245, `utils.py` 126, `registry.py` 53, `constants.py` 52, `router.py` 25.
- Routes: `views/analytics.py` 192. Config: `config.py` (`NL_MAX_ROWS`). DB: `db.py`.

**Routes powering the dashboard:** `GET /<tree_id>/analytics/{given-names, surnames, individuals, families, events, places, dates, media, open-questions, notes}` (`app/views/analytics.py:17–178`).
