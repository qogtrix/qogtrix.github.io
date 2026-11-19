-- AI Engineering Laboratory — Database schema, Stages 2–4
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

-- Stage 4 — normalized material database (replaces the flat Stage 1
-- materials table). Core facts live in `materials`; every measured
-- property is a row in `material_properties` (one row per property,
-- with its unit and confidence), so a new property never needs a
-- schema change. `material_favorites` is per-user and private.
-- The authoritative content is data/materials.json; the backend
-- seeds these tables from it on first run (see backend/db.py).
-- A NULL property value means "not available" — never zero, never
-- invented. Confidence is one of: verified / typical / estimated.
CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    grade TEXT,
    category TEXT NOT NULL,
    standard TEXT,
    source TEXT,
    confidence TEXT NOT NULL DEFAULT 'typical'
        CHECK (confidence IN ('verified','typical','estimated')),
    test_conditions TEXT,
    temp_min_c REAL,
    temp_max_c REAL,
    cost_index INTEGER CHECK (cost_index BETWEEN 1 AND 5),
    cost_note TEXT,
    corrosion_resistance INTEGER CHECK (corrosion_resistance BETWEEN 1 AND 5),
    corrosion_note TEXT,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_materials_category ON materials(category);
CREATE INDEX IF NOT EXISTS idx_materials_name ON materials(name);

CREATE TABLE IF NOT EXISTS material_properties (
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    property_key TEXT NOT NULL,
    value_num REAL,
    value_text TEXT,
    unit TEXT,
    confidence TEXT NOT NULL DEFAULT 'typical'
        CHECK (confidence IN ('verified','typical','estimated')),
    PRIMARY KEY (material_id, property_key)
);
CREATE INDEX IF NOT EXISTS idx_matprops_key ON material_properties(property_key);

CREATE TABLE IF NOT EXISTS material_favorites (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, material_id)
);
CREATE INDEX IF NOT EXISTS idx_matfav_user ON material_favorites(user_id);

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
--   -- Stage 4: materials are public reference data (read for all);
--   -- material_favorites are owner-scoped like projects.
--   CREATE POLICY matfav_owner_isolation ON material_favorites
--     USING (user_id = current_setting('app.current_user_id', true))
--     WITH CHECK (user_id = current_setting('app.current_user_id', true));
-- The backend sets app.current_user_id per connection (SET LOCAL)
-- from the verified session. Backend checks remain the primary
-- enforcement; RLS is defence-in-depth so even a buggy query or a
-- direct database connection cannot read another user's rows.
