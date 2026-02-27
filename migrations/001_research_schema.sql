-- Research schema and tables for ligneous-python-api.
-- Run this with a DB user that can create schema and tables.
-- Python API user: grant USAGE on schema research; grant SELECT on app tables; grant full on research.*.

CREATE SCHEMA IF NOT EXISTS research;

-- 1. Saved queries
CREATE TABLE IF NOT EXISTS research.saved_queries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tree_id UUID NOT NULL,
    user_id UUID,
    name TEXT NOT NULL,
    description TEXT,
    entity_type TEXT NOT NULL,
    definition JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saved_queries_tree_id ON research.saved_queries(tree_id);
CREATE INDEX IF NOT EXISTS idx_saved_queries_user_id ON research.saved_queries(user_id);

-- 2. Query runs
CREATE TABLE IF NOT EXISTS research.query_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    saved_query_id UUID REFERENCES research.saved_queries(id) ON DELETE SET NULL,
    tree_id UUID NOT NULL,
    run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL,
    result_count INT,
    error_message TEXT,
    parameters_snapshot JSONB
);

CREATE INDEX IF NOT EXISTS idx_query_runs_saved_query_id ON research.query_runs(saved_query_id);
CREATE INDEX IF NOT EXISTS idx_query_runs_tree_id ON research.query_runs(tree_id);
CREATE INDEX IF NOT EXISTS idx_query_runs_run_at ON research.query_runs(run_at);

-- 3. Result sets
CREATE TABLE IF NOT EXISTS research.result_sets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_run_id UUID NOT NULL REFERENCES research.query_runs(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    tree_id UUID NOT NULL,
    storage_type TEXT NOT NULL,
    payload JSONB,
    file_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_result_sets_query_run_id ON research.result_sets(query_run_id);
CREATE INDEX IF NOT EXISTS idx_result_sets_tree_id ON research.result_sets(tree_id);

-- 4. Statistics snapshots
CREATE TABLE IF NOT EXISTS research.statistics_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tree_id UUID NOT NULL,
    stats_type TEXT NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    result JSONB NOT NULL,
    parameters JSONB
);

CREATE INDEX IF NOT EXISTS idx_statistics_snapshots_tree_type ON research.statistics_snapshots(tree_id, stats_type);
CREATE INDEX IF NOT EXISTS idx_statistics_snapshots_computed_at ON research.statistics_snapshots(computed_at);

-- 5. Analysis runs
CREATE TABLE IF NOT EXISTS research.analysis_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tree_id UUID NOT NULL,
    analysis_type TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    parameters JSONB,
    result_summary JSONB,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_tree_id ON research.analysis_runs(tree_id);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_status ON research.analysis_runs(status);

-- 6. Analysis results
CREATE TABLE IF NOT EXISTS research.analysis_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_run_id UUID NOT NULL REFERENCES research.analysis_runs(id) ON DELETE CASCADE,
    result_type TEXT NOT NULL,
    entity_id_1 UUID,
    entity_id_2 UUID,
    score DECIMAL(10, 6),
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analysis_results_run_id ON research.analysis_results(analysis_run_id);

-- 7. Exports
CREATE TABLE IF NOT EXISTS research.exports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tree_id UUID NOT NULL,
    user_id UUID,
    export_type TEXT NOT NULL,
    parameters JSONB,
    file_path_or_key TEXT NOT NULL,
    file_size_bytes BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exports_tree_id ON research.exports(tree_id);
CREATE INDEX IF NOT EXISTS idx_exports_created_at ON research.exports(created_at);

-- 8. Reports (references statistics_snapshots and exports)
CREATE TABLE IF NOT EXISTS research.reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tree_id UUID NOT NULL,
    user_id UUID,
    report_type TEXT NOT NULL,
    title TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    statistics_snapshot_id UUID REFERENCES research.statistics_snapshots(id) ON DELETE SET NULL,
    export_id UUID REFERENCES research.exports(id) ON DELETE SET NULL,
    parameters JSONB
);

CREATE INDEX IF NOT EXISTS idx_reports_tree_id ON research.reports(tree_id);
CREATE INDEX IF NOT EXISTS idx_reports_generated_at ON research.reports(generated_at);
