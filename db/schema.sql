-- AI Engineering Laboratory — Database schema (Stage 1, prepared only)
-- Target: PostgreSQL in production, SQLite for local dev.
-- No database is running in Stage 1; Stage 1 data lives in data/*.json
-- and in browser localStorage. This schema is the contract Stage 2
-- implements. RULE: simulations.results stays NULL until a real solver
-- writes it. Never seed fake results.

CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    density_kg_m3 REAL,
    youngs_modulus_gpa REAL,
    yield_strength_mpa REAL,
    tensile_strength_mpa REAL,
    poisson_ratio REAL,
    thermal_conductivity_w_mk REAL,
    melting_point_c REAL,
    source_note TEXT
);

CREATE TABLE IF NOT EXISTS components (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    lab TEXT NOT NULL,
    standard TEXT,
    material TEXT,
    dimensions TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    lab TEXT NOT NULL,
    description TEXT DEFAULT '',
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS simulations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    solver TEXT NOT NULL,
    solver_version TEXT,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','completed','failed','not_implemented')),
    inputs JSONB NOT NULL DEFAULT '{}'::jsonb,
    results JSONB,  -- NULL until a real solver produces output
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    model TEXT,
    prompt_hash TEXT,
    tools_used JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_components_lab ON components(lab);
CREATE INDEX IF NOT EXISTS idx_simulations_project ON simulations(project_id);
CREATE INDEX IF NOT EXISTS idx_projects_lab ON projects(lab);
