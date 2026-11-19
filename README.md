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

## Stage 3 — Private and Public Project Visibility (19 Nov 2026)

- Every user has a **unique username** (3–30 chars, login by email
  or username). The gallery shows `@username`, never email.
- Every project is **private by default** — even if a client asks
  for public on creation. Owners publish explicitly (Publish button,
  or visibility control in the project editor).
- **Public Gallery** (`gallery.html`): recently published projects,
  category filter, search, read-only detail. Private projects never
  appear in the list, search, or detail — direct URLs return 404.
- Tests: `backend/test_stage3.py`, **34/34 passed** (A–G sequence
  with Alice/Bob + username + leak checks); Stage 2 suite still 34/34.
  See `docs/TEST_RESULTS_STAGE3.md`.
- Future sharing / downloads / version history / comments /
  collaboration are prepared in the architecture only, not built.

## Stage 4 — Universal Material Database (19 Nov 2026)

- **38 materials across 10 categories** — a working sample, not a
  complete universal database. Values are typical published values
  with sources; missing values are null and shown as "—".
- **Library** (`materials.html`): search, category chips, property
  filters, sort, favorites, 2–4 material comparison with
  best-value highlighting, and a requirements recommender with
  transparent scoring (50% strength-to-weight + 30% specific
  stiffness + 20% low cost).
- **Material pages** (`material.html?id=...`): grouped properties,
  data quality (source, standard, test conditions, temperature
  range, confidence), derived metrics, related materials, and
  select-for-project.
- **Backend:** normalized tables (`materials`,
  `material_properties`, `material_favorites`), seeded once from
  `data/materials.json`; API for search/filter/compare/recommend/
  favorites/project selection. See `docs/MATERIALS.md`.
- Tests: `backend/test_stage4.py`, **42/42 passed**; Stage 2 and
  Stage 3 suites still 34/34. See `docs/TEST_RESULTS_STAGE4.md`.
- Add a material by appending one entry to
  `data/materials.json` — no code change needed.

## Stage 5 — 3D Modelling Workspace (19 Nov 2026)

- **Real parametric modeller** (`workspace.html`): primitives,
  extrusions, revolves, 11 library components, real CSG booleans
  (three-bvh-csg), holes, rounded/chamfered boxes, assemblies
  with parent-child hierarchy, section + exploded views,
  perspective/orthographic cameras, gizmos, selection.
- **Materials:** Stage 4 material per component, mesh volume and
  mass in the inspector.
- **Saving:** into the user's project with version-aware updates
  (409 on a stale base_version), autosave, duplicate, reopen.
- **Import/export:** STL, OBJ, GLB, JSON (real). STEP/3MF/FCStd
  are not supported by the mesh kernel — stated in the UI and
  docs. See `docs/MODELLING.md` for the exact limits.
- **AI tools:** `GET /api/v1/model/schema` + project model API
  (create/modify/assign/assemble/inspect/save/export).
- Tests: `backend/test_stage5.py` **56/56**,
  `backend/test_stage5_math.js` **29/29**,
  `backend/test_stage5_kernel.mjs` **28/28** (headless, real
  geometry + real CSG volumes). See `docs/TEST_RESULTS_STAGE5.md`.

## Stage 6 — Physics and Simulation Foundation (19 Nov 2026)

- **Rigid-body dynamics** (`simulate.html`): real Rapier
  0.14.0 engine in the browser — dynamic/static/kinematic
  bodies from your model, gravity, friction, restitution,
  forces (impulse/continuous), Rapier spring joints,
  fixed/revolute joints, live state, height + energy charts,
  results saved to a backend job. Validated headlessly 9/9
  against analytical references.
- **Analytical solvers** (backend, SI units): cantilever and
  simply-supported beams, axial bar, torsion, 1-D conduction,
  lumped thermal, drag/lift, free fall — all labelled
  ANALYTICAL with their assumptions; missing material
  properties are named errors, never substitutions.
- **Job system:** `GET /api/v1/solvers` + the simulations
  API (create/run/list/get/delete/post-results), owner-scoped.
- **Honest limits:** no FEA (CalculiX/Code_Aster) and no CFD
  (OpenFOAM) are installed — those jobs are recorded as
  `not_implemented`, never faked. See `docs/SOLVERS.md` and
  `docs/VALIDATION_STAGE6.md`.
- Tests: `backend/test_stage6.py` **29/29**,
  `backend/test_stage6_rapier.mjs` **9/9**.
  See `docs/TEST_RESULTS_STAGE6.md`.
