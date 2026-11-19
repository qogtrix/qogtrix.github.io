# AI Engineering Laboratory — Stage 1: Foundation

Advanced AI-powered engineering laboratory. Long-term objective: a
platform where an AI agent can independently design, model, simulate,
analyse, test and improve engineering systems.

Hybrid approach: own platform + workflows, own material database and
component library, own AI agent, reliable open-source libraries and
solvers where appropriate, no unnecessary dependence on paid APIs.

**Live site:** https://qogtrix.github.io/
**Custom domain (pending):** https://qogtrix.is-a.dev/ — goes live
after is-a.dev PR #61755 is merged, then set as Custom Domain in
the repo Pages settings (see `docs/RUN_DEPLOY.md`).

## Stage 1 — what is built

- Premium dark-themed dashboard (`index.html`)
- Six laboratories, each with a dedicated page:
  Mechanical, Electrical, Structural, Aerospace, Robotics,
  Materials Science (`labs/*.html`)
- 3D workspace with Three.js 0.160.0 (`workspace.html` + per-lab
  presets) — orbit/zoom/pan, wireframe, grid, auto-rotate, reset,
  PNG export, real geometry statistics
- Materials database — 12 materials, searchable / filterable /
  sortable, with typical published values
  (verify against datasheets before design use)
- Component library — 12 standard components, filterable by lab
- Projects — create / list / delete / export JSON, stored in the
  browser (`localStorage`)
- System status panel — real runtime checks
- Responsive desktop + mobile, error handling throughout

## Stage 1 — what is deliberately NOT built

No simulator, no running backend, no server database, no AI agent
runtime. Simulation controls are disabled and labelled Stage 2.
No hardcoded result is ever presented as a simulation.
See `docs/STATUS.md` for the full completed / incomplete list.

## Run locally

```bash
python3 -m http.server 8000
# open http://localhost:8000/
```

Full instructions: `docs/RUN_DEPLOY.md`

## Docs

- `docs/ARCHITECTURE.md` — technical architecture
- `docs/DEPENDENCIES.md` — dependency list (Three.js only, MIT)
- `docs/STATUS.md` — completed vs incomplete
- `docs/AI_AGENT.md` — AI-agent foundation contract
- `docs/RUN_DEPLOY.md` — run & deploy instructions
- `backend/api-spec.md` — API contract for Stage 2
- `db/schema.sql` — database schema for Stage 2

## File map

```
index.html  workspace.html
labs/*.html (x6)
assets/css/style.css
assets/js/app.js  assets/js/workspace3d.js  assets/js/materials.js
data/labs.json  data/materials.json  data/components.json
backend/app.py  backend/requirements.txt  backend/api-spec.md
db/schema.sql
docs/*.md
```

## Stage 2 — User Accounts and Personal Workspaces (19 Nov 2026)

- Register / sign in / sign out, profile + password change.
  Passwords hashed with PBKDF2; sessions are HMAC-signed tokens
  (7 days, revocable).
- One independent workspace per user: My Projects, Recent Work,
  Account Settings. Create, search, open, rename, duplicate,
  delete (with confirmation), save progress.
- Ownership enforced on every API call — another user's project
  returns 404. Tested with two accounts: **34/34 tests passed**
  (`backend/test_stage2.py`, see `docs/TEST_RESULTS_STAGE2.md`).
- Muse integration prep: scoped API keys (`aielab_…`) in Account
  Settings — see `docs/MUSE_INTEGRATION.md`.
- Run the backend: `cd backend && python3 app.py` (stdlib only,
  no install). GitHub Pages cannot run a backend, so the static
  site shows the Stage 2 frontend with a clear "backend must be
  running" state; the working authenticated app is the hosted
  fullstack version.
