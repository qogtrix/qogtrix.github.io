-- AI Engineering Laboratory — Database schema, Stage 2
-- Target: PostgreSQL in production, SQLite for local dev.
-- Portable tables first (both engines). Postgres-only Row Level
-- Security policies are in the section after the marker below.
--
-- OWNERSHIP RULE (the core of Stage 2):
--   * every project has owner_id NOT NULL REFERENCES users(id)
--   * every API query for projects MUST filter owner_id = current user
--   * a project belonging to another user must behave as if it does
--     not exist (404, not 403) so user IDs cannot be enumerated
--   * simulations.agent_runs also carry owner/user references
-- RULE: simulations.results stays NULL until a real solver writes it.

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    username TEXT UNIQUE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);
-- Username rules (enforced in backend/app.py, Stage 3):
-- 3–30 chars, lowercase letters / numbers / _ only, unique
-- case-insensitively (stored lowercased). Shown publicly in the
-- gallery; email is NEVER shown publicly.

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    last_used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    scopes TEXT NOT NULL DEFAULT 'projects:read projects:write',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);

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
    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    lab TEXT NOT NULL DEFAULT 'general'
        CHECK (lab IN ('general','mechanical','electrical','structural',
                       'aerospace','robotics','materials')),
    visibility TEXT NOT NULL DEFAULT 'private'
        CHECK (visibility IN ('private','public')),
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id);
CREATE INDEX IF NOT EXISTS idx_projects_owner_lab ON projects(owner_id, lab);
CREATE INDEX IF NOT EXISTS idx_projects_public ON projects(visibility, updated_at);
-- Visibility rules (Stage 3): new projects are ALWAYS private.
-- Publishing is an explicit owner action only. Public listings
-- must query visibility='public' — never rely on the UI to hide
-- private projects. Future tables (NOT created in Stage 3):
-- project_versions, comments, shares, collaborations.

CREATE TABLE IF NOT EXISTS simulations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    solver TEXT NOT NULL,
    solver_version TEXT,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','completed','failed','not_implemented')),
    inputs TEXT NOT NULL DEFAULT '{}',
    results TEXT,  -- NULL until a real solver produces output
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_simulations_owner ON simulations(owner_id);

CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    model TEXT,
    prompt_hash TEXT,
    tools_used TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_user ON agent_runs(user_id);

-- === POSTGRES RLS (production only — do not run on SQLite) ===
-- Enable on PostgreSQL after creating the tables above:
--   ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
--   ALTER TABLE simulations ENABLE ROW LEVEL SECURITY;
--   ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
--   ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
--   CREATE POLICY projects_owner_isolation ON projects
--     USING (owner_id = current_setting('app.current_user_id', true))
--     WITH CHECK (owner_id = current_setting('app.current_user_id', true));
--   -- Stage 3, public read: anonymous visitors may SELECT public rows only.
--   CREATE POLICY projects_public_read ON projects FOR SELECT
--     USING (visibility = 'public');
--   -- Note: the two policies combine with OR for SELECT, so an owner
--   -- sees their own (private + public) projects and anyone sees
--   -- public ones. INSERT/UPDATE/DELETE stay owner-only via the
--   -- owner-isolation policy above.
--   CREATE POLICY simulations_owner_isolation ON simulations
--     USING (owner_id = current_setting('app.current_user_id', true))
--     WITH CHECK (owner_id = current_setting('app.current_user_id', true));
-- The backend sets app.current_user_id per connection (SET LOCAL)
-- from the verified session. Backend checks remain the primary
-- enforcement; RLS is defence-in-depth so even a buggy query or a
-- direct database connection cannot read another user's rows.
