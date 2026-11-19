# Muse Integration — Stage 2 preparation

**Status:** contract + API-key mechanism implemented and tested.
No Muse agent runtime is connected yet. Nothing here gives any
other user access to Karan's Muse session, credentials, browser
session, or private projects.

## How it will work

1. Karan (and only Karan, in his own account) creates an API key in
   Account Settings → Muse agent access. The key looks like
   `aielab_<48 hex chars>`, is shown **once**, and only its SHA-256
   hash is stored.
2. The Muse agent calls the same backend endpoints a human uses,
   with `Authorization: Bearer aielab_…`:
   - `GET /api/v1/projects` — list Karan's projects
   - `POST /api/v1/projects` — create a project / experiment
   - `GET / PATCH /api/v1/projects/{id}` — continue / save a design
   - `POST /api/v1/projects/{id}/duplicate` — branch an experiment
3. The key is bound to one `user_id`. Every project query still
   filters `owner_id = that user`, so the key can never reach
   another user's projects (tested: API key + another user's
   project id → 404).
4. Keys are revocable instantly in Account Settings. Revoking a key
   does not affect the user's password sessions.
5. Every agent action is logged in `agent_runs` (user_id,
   project_id, tools used) — see `db/schema.sql`.

## Rules carried forward from Stage 1 (docs/AI_AGENT.md)

- The agent may read materials/components/projects and propose
  geometry/parameters, but may never write a simulation result.
- Results may only appear when a real solver writes them.
- No other user's session, credentials, or projects are accessible
  through the agent's key, the API, or the database.
- A key must never be pasted into chat, committed to git, or shared.
  If one leaks, revoke it and create a new one.

---

## Materials (Stage 4) — structured retrieval for Muse

The materials API is the retrieval system the agent uses to search,
compare, recommend and select materials. It is read-only except for
favorites and project selection, which are owner-scoped like all
project writes (agent tokens work the same as session tokens).

- **Search:** `GET /api/v1/materials?q=aluminium&category=metals&min_tensile=500&max_density=3000&sort=strength_to_weight`
- **Detail:** `GET /api/v1/materials/{id}` — full properties, source,
  standard, confidence, `missing_properties` (never treat a missing
  value as zero), `derived` (strength-to-weight, specific stiffness).
- **Compare:** `GET /api/v1/materials/compare?ids=a,b,c` — 19 rows
  with a computed `best` index per row.
- **Recommend:** `POST /api/v1/materials/recommend` with hard
  requirements; returns ranked candidates with `score`, `reasons`
  and `trade_offs` computed from stored data, plus the scoring
  formula and the count of excluded materials. Explain trade-offs
  from those fields — do not invent new ones.
- **Select:** `POST /api/v1/projects/{id}/materials` with
  `{material_id}` — only for the agent owner's own projects.
- **Favorites:** `GET/POST/DELETE /api/v1/materials/favorites`.

Rules: cite the `source` and `confidence` of any value you quote;
say "not on record" for missing properties; never present the
38-material sample as a complete database; cost is a relative
1–5 index, not a price.
