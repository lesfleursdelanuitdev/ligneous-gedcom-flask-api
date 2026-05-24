# ligneous-python-api

Python research/analytics API for the Ligneous genealogy stack. Built with Flask. Reads from the same Postgres database as ligneous-frontend (read-only on app tables) and owns the `research` schema for saved queries, statistics snapshots, analysis runs, exports, and reports.

## Setup

1. **Python 3.10+** recommended.

2. **Create a virtual environment and install dependencies:**

   ```bash
   cd ligneous-python-api
   python3 -m venv .venv
   source .venv/bin/activate   # or .venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

3. **Environment:** Copy `.env.example` to `.env` and configure:
   - `DATABASE_URL` to the same Postgres instance used by ligneous-frontend (e.g. `postgresql://user:password@localhost:5432/ligneous`).
   - `GROQ_API_KEY` for natural-language search (Groq LLM). Optional overrides: `GROQ_MODEL`, `GROQ_TIMEOUT_SECONDS`, `NL_MAX_ROWS`, `NL_MAX_PROMPT_CHARS`.
   - `NL_PERSIST_QUERY_RUNS` — set to `false` to disable writes to `research.query_runs` / `research.result_sets` globally (e.g. deployment with no research write grants). Per-request: upstream can send `X-Research-Persist: false` to skip persistence when env default is `true` (used by the read-only public frontend).
   - **Important:** never commit real secrets. Put real values only in `.env` (gitignored), not in `.env.example`.

4. **Research schema:** Run the migration to create the `research` schema and tables:

   ```bash
   psql "$DATABASE_URL" -f migrations/001_research_schema.sql
   ```

   Ensure the DB user used by this API has:
   - `USAGE` on schema `research` and full privileges on `research.*`
   - `SELECT` on app tables/schemas it needs to read (e.g. for statistics and queries)

## Run

With the virtual environment activated:

```bash
python run.py
```

Or with Gunicorn (also used in production):

```bash
gunicorn app.application:app --bind 0.0.0.0:5001
```

For a public hostname (e.g. `analytics.gonsalvesfamily.com`), bind **loopback** and put nginx in front. See **[deploy/README.md](./deploy/README.md)** for systemd + nginx on the same host as Postgres and the Next apps.

Local dev listens on `http://0.0.0.0:5001` by default (`HOST` / `PORT` in `.env`).

## Endpoints

- **GET /api/health** — Liveness (API is up).
- **GET /api/ready** — Readiness (database connection check). Returns 503 if the DB is unreachable.
- **GET /api/research/ping** — Research smoke test.
- **GET /api/research/schema-check** — Verify research schema exists.
- **GET /api/research/trees/<tree_id>/analytics/given-names** — Given names statistics (summary, top names, frequency distribution, by sex, by decade). Query param: `limit` (default 50, max 200).
- **GET /api/research/trees/<tree_id>/analytics/surnames** — Surname statistics (summary, top surnames, frequency distribution, Soundex groups). Query param: `limit` (default 50, max 200).
- **POST /api/research/trees/<tree_id>/nl-search** — Natural-language search backed by Groq. Body: `{ "query": "<free text>", "context": { ...optional... } }`. Returns `{ query, intent, confidence, result, meta: { run_id, ... } }`. Maps NL prompts to a fixed set of safe analytics intents (top given names, top surnames, names by decade, names by sex, surname Soundex groups, name lookups). Persists each call to `research.query_runs` and `research.result_sets`.
- **GET /api/research/trees/<tree_id>/nl-search/suggestions** — Returns starter prompts to seed the UI.

Further routes (saved queries, statistics, analysis runs, exports, reports) can be added under `/api` as needed.
