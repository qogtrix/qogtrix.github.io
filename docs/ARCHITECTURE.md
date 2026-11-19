# AI Engineering Laboratory — Architecture (Stage 1: Foundation)

**Version:** Stage 1 — 19 Nov 2026
**Status:** Foundation only. No simulation solver is implemented in Stage 1.
**Hosting:** Static site on GitHub Pages (`qogtrix.github.io`, custom domain
`qogtrix.is-a.dev` pending is-a.dev PR #61755 merge). No server is required
to run Stage 1.

## 1. Environment inspected (19 Nov 2026)

| Item | Found |
|---|---|
| OS | Linux (VM) |
| Node.js | v24.22.1, npm 10.9.4 |
| Python | 3.12.3, pip 24.0 |
| Git | 2.43.0 |
| GitHub | Connected as `qogtrix`; repo `qogtrix/qogtrix.github.io` exists, contained only `README.md` + placeholder `index.html` before Stage 1 |
| GitHub Pages | Live at `https://qogtrix.github.io/` (200 OK) |
| `qogtrix.is-a.dev` | **Not live yet** — redirects to `is-a.dev/available?d=qogtrix`. PR #61755 still open, awaiting maintainer merge (2 hours–3 days). Same for `leadloop.is-a.dev` (PR #61759). |
| Build step | None required in Stage 1 (pure static HTML/CSS/JS) |

## 2. Design principles

1. **Hybrid approach, as specified:** own platform + own workflows, own
   material/component data, own future AI agent, open-source libraries
   where practical, no paid APIs in Stage 1.
2. **No fake functionality.** A control that does nothing is either absent,
   disabled with a clear "Stage 2" label, or labelled as a preview.
   No hardcoded "simulation result" is ever presented as a real result.
3. **Modular:** each laboratory is an independent page + an entry in
   `data/labs.json` + a 3D preset. Adding a lab = one JSON entry + one page.
4. **Static first:** Stage 1 runs entirely in the browser so it can be
   hosted free on GitHub Pages. Backend and database are *prepared*
   (schemas, API spec, skeleton) but not required to run the site.
5. **Maintainable:** one shared stylesheet, one shared app script, one
   shared 3D module, data in JSON files — no duplicated logic per page.

## 3. System diagram

```
Browser (GitHub Pages, static)
├── index.html                  Dashboard
├── labs/*.html (x6)            One page per laboratory
├── workspace.html              Dedicated 3D workspace
├── assets/css/style.css        Single dark theme
├── assets/js/app.js            Nav, status checks, projects (localStorage)
├── assets/js/workspace3d.js    Three.js scene, presets, controls
├── assets/js/materials.js      Materials / components table, search, sort
└── data/*.json                 labs, materials, components (real data)

Future (Stage 2+, not running in Stage 1)
├── backend/app.py              FastAPI skeleton — /health only works;
│                               simulation endpoints return 501
├── backend/api-spec.md         Endpoint contracts for Stage 2
└── db/schema.sql               PostgreSQL/SQLite schema for materials,
                                components, projects, simulations
        │
        ▼ (Stage 2)
AI agent  →  backend  →  solvers (open-source)  →  database
```

## 4. Frontend

- **No framework, no build step.** Plain HTML/CSS/JS. Reason: zero build
  fragility on GitHub Pages, easy for a single developer to maintain,
  fast to extend.
- **Three.js 0.160.0** via CDN import map (jsDelivr) + `OrbitControls`.
  Used only for *geometry visualisation* in Stage 1 — rendering a beam,
  shaft, frame, wing, robot arm or lattice, reporting real geometry
  statistics (vertices / triangles) from the Three.js objects themselves.
  It is **not** a simulation.
- **Data:** `data/materials.json` (12 materials, typical published
  values — see file header: verify against a datasheet before design use),
  `data/components.json` (12 standard components), `data/labs.json`
  (6 labs). All counts shown on the dashboard are computed from these
  files at runtime, not hardcoded.
- **Projects:** created/listed/deleted/exported in the browser with
  `localStorage` (`aielab.projects.v1`). No account, no server.
  Export downloads a real JSON file of what the user entered.
- **Responsive:** sidebar collapses to a top bar + hamburger below
  900 px; tables scroll horizontally on mobile; 3D canvas resizes.
- **Error handling:** `window.onerror` banner; WebGL-unavailable
  fallback; `fetch()` failure shows an error state with a retry button
  instead of a blank table; Three.js CDN failure shows a clear message
  instead of a frozen canvas.

## 5. Backend architecture (prepared, not live)

See `backend/README.md` and `backend/api-spec.md`.

- Stack chosen for Stage 2: **Python 3.12 + FastAPI + Uvicorn**,
  **SQLite for local dev / PostgreSQL for production**, SQLAlchemy-style
  models mirroring `db/schema.sql`.
- `backend/app.py` in Stage 1 exposes only `GET /health` (real) and
  defines simulation routes that explicitly return **501 Not Implemented**
  with `{"status":"not_implemented","stage":2}`. This is deliberate:
  a stub that pretends to simulate would violate the project rules.
- Future solvers (Stage 2+, to be evaluated, not yet chosen):
  beam/FEA — e.g. `scipy` + an open FEA library; electrical — SPICE-type
  open solver; CFD/aero — OpenFOAM (heavy, likely as a separate service).
  No solver is bundled in Stage 1.

## 6. Database architecture (prepared, not live)

See `db/schema.sql` and `db/README.md`. Four core tables:

- `materials` — id, name, category, density, Young's modulus, yield,
  tensile strength, Poisson ratio, thermal conductivity, melting point,
  source note.
- `components` — id, name, category, lab, standard, dimensions, material.
- `projects` — id, name, lab, description, created_at, updated_at,
  payload JSON (geometry / parameters as entered by the user).
- `simulations` — id, project_id, solver, solver_version, status
  (`queued|running|completed|failed|not_implemented`), inputs JSON,
  results JSON (NULL until a real solver writes it), created_at.
  **Rule:** `results` must stay NULL / absent until a real solver
  produces them. Never seed fake results.

## 7. AI-agent foundation (prepared, not live)

See `docs/AI_AGENT.md` (in `docs/`). In Stage 1 this is only a contract:

- Agent tools will be the same HTTP endpoints as `backend/api-spec.md`.
- The agent may **read** materials/components/projects and **propose**
  geometry/parameters, but may not write a simulation result.
- Every agent action must be logged in an `agent_runs` table
  (defined in `db/schema.sql`) with model, prompt hash, tools used.
- No agent code, API key, or model call exists in Stage 1.

## 8. File map

```
index.html  workspace.html
labs/mechanical.html  labs/electrical.html  labs/structural.html
labs/aerospace.html   labs/robotics.html    labs/materials.html
assets/css/style.css
assets/js/app.js  assets/js/workspace3d.js  assets/js/materials.js
data/labs.json  data/materials.json  data/components.json
backend/app.py  backend/requirements.txt  backend/api-spec.md  backend/README.md
db/schema.sql  db/README.md
docs/ARCHITECTURE.md  docs/DEPENDENCIES.md  docs/STATUS.md
docs/AI_AGENT.md  docs/RUN_DEPLOY.md
README.md  .nojekyll
```

## 9. What Stage 1 deliberately does NOT do

- No stress / thermal / CFD / circuit / dynamics solver.
- No user accounts, no server database, no paid API.
- No "Run simulation" button that returns numbers.
- No AI agent runtime.

---

# Stage 2 — User Accounts and Personal Workspaces (19 Nov 2026)

## 10. What changed, and why the stack changed

Stage 1 planned FastAPI. Stage 2 implements the backend in **Python
3.12 standard library only** (`http.server`, `sqlite3`, `hashlib`,
`hmac`) — no pip install needed. Reason: this machine has no
FastAPI/uvicorn/PyJWT installed, and a zero-dependency backend runs
anywhere with just `python3`. The API contract (`backend/api-spec.md`)
is framework-neutral, so a FastAPI port later would not change the
frontend. The hosted Stage 2 app (Muse fullstack artifact) uses its
own built-in server + database and the same contract.

**Important hosting fact:** GitHub Pages is static-only, so it
cannot run this backend. The static site (`qogtrix.github.io`)
therefore ships the Stage 2 *frontend* (Sign in, My Projects,
Account Settings) with a clear "backend must be running" state when
no backend is reachable, and the working authenticated app is the
hosted fullstack version. The backend source in this repo is what
you self-host (`cd backend && python3 app.py`).

## 11. Authentication

- Register / login / logout / profile (`/me`), change password.
- Passwords: PBKDF2-HMAC-SHA256, 200,000 iterations, per-user salt.
  Only hashes are stored.
- Sessions: HMAC-signed tokens, 7-day expiry, session row in the
  database. Logout deletes the row, so the token stops working
  immediately. Sessions are checked on every request.
- Login rate limit: 5 failed attempts per email per 15 min → 429.
- Frontend stores only the token (localStorage) — never a password.

## 12. Ownership and isolation

- `projects.owner_id NOT NULL REFERENCES users(id)` (plus
  `simulations.owner_id`, `agent_runs.user_id`).
- Every project query filters `owner_id = current user`. Single
  project access first fetches with that filter; a project owned
  by someone else returns **404**, not 403, so user IDs cannot be
  enumerated through the API.
- Database level: foreign keys enforced on every SQLite connection;
  Postgres RLS policies are defined in `db/schema.sql` (production
  defence-in-depth, using `app.current_user_id`). Backend checks
  remain the primary enforcement.
- Tests prove isolation (see `docs/TEST_RESULTS_STAGE2.md`):
  34/34 passed with two accounts (Alice / Bob).

## 13. Personal workspaces

- One workspace per user, reached from the sidebar: Dashboard,
  My Projects, Engineering Laboratories, Recent Work, Account Settings.
- My Projects: create (name, description, lab), search, lab filter,
  open + edit + save progress (`payload` JSON), rename, duplicate,
  delete (with confirmation). Recent Work shows the 5 most recently
  updated projects.
- Stage 1's browser-local projects (dashboard, localStorage) are
  unchanged and separate — they are "this browser only", while
  Stage 2 projects live on the server under an account.

## 14. Muse integration (prepared)

- Scoped API keys (`aielab_…`, hash stored, shown once, revocable)
  bound to one user. The future agent uses the same project
  endpoints with that key. See `docs/MUSE_INTEGRATION.md`.
- No other user gets access to Karan's Muse session, credentials,
  browser session, or projects through this mechanism.

## 15. Stage 2 file map (additions)

```
auth.html  projects.html  settings.html
assets/js/config.js  assets/js/auth.js  assets/js/projects.js
backend/auth.py  backend/db.py  backend/app.py (real, was skeleton)
backend/test_stage2.py  backend/.gitignore
db/schema.sql (v2: users, sessions, api_keys, owner_id, RLS)
docs/MUSE_INTEGRATION.md  docs/TEST_RESULTS_STAGE2.md
```

---

# Stage 3 — Private and Public Project Visibility (19 Nov 2026)

## 16. Visibility model

- `projects.visibility` is `'private'` or `'public'`, default `'private'`.
- **Creation always forces private.** The backend ignores any
  `visibility` value sent with `POST /api/v1/projects`. Publishing
  is a separate, explicit owner action: `POST /projects/{id}/publish`,
  `POST /projects/{id}/unpublish`, or `PATCH` with `visibility`.
- **Copies are always private**, even when the source is public.
- Public endpoints (`GET /api/v1/public/projects`, `GET /.../{id}`)
  need no auth and query only `visibility='public'`. They return a
  restricted view: id, name, description, lab, owner *username*,
  published payload, timestamps. Never `owner_id` or email.
- Private projects are invisible everywhere else: public list,
  public search, public detail (404), owner-scoped API (404 for
  non-owners), and the gallery page (which only calls the public API).
- There are no file attachments in Stage 3. The rule for them is
  fixed now so Stage 4 cannot get it wrong: any future attachment
  download must go through the same owner-or-public check as the
  project detail endpoint — never a direct static URL.

## 17. Unique usernames

- `users.username`: 3–30 chars, `[a-z0-9_]`, lowercased, UNIQUE
  (case-insensitive — `Alice` and `alice` collide by design).
- Required at registration; login accepts email *or* username;
  changeable in Account Settings if the new name is free.
- The username is the only owner identifier shown publicly.
  Existing Stage 2 accounts are backfilled from their email local
  part by the migration in `backend/db.py`.

## 18. Future preparation (not implemented)

- Public sharing (links), downloadable designs, version history,
  public comments, collaboration — documented here only.
  Planned tables: `project_versions`, `comments`, `shares`.
  None are created in Stage 3, and no comment/share UI exists.

## 19. Stage 3 file map (additions)

```
gallery.html  assets/js/gallery.js
backend/test_stage3.py
docs/TEST_RESULTS_STAGE3.md
(changed: backend/app.py, backend/db.py, db/schema.sql,
 assets/js/auth.js, assets/js/projects.js, auth.html,
 projects.html, settings.html, all navs)
```

---

# Stage 4 — Universal Material Database (19 Nov 2026)

## 20. What changed

- **Data:** `data/materials.json` v2 — 38 materials, 10 categories,
  16 properties each, nested `properties` with null = not available,
  per-material grade / standard / source / confidence /
  test conditions / temperature range / cost index / corrosion
  rating. `data/material_categories.json` holds the 10 categories.
  See `docs/MATERIALS.md` for the data-quality rules.
- **Normalized storage:** `materials` + `material_properties` +
  `material_favorites` in `db/schema.sql`; backend seeds them from
  `materials.json` on first run (idempotent). A new property never
  needs a schema change — it is a new row.
- **API:** materials list (search + filters + sort), detail,
  categories with counts, compare (2–4, best-value per row),
  recommend (transparent scoring), favorites (auth, per-user),
  project material selection (owner-only, id stored in
  `payload.materials`). Full contract in `backend/api-spec.md`.
- **Frontend:** `materials.html` (library: chips, filters, cards,
  favorites, compare tray, recommender) and `material.html`
  (detail page: grouped properties, data quality, select-for-
  project, related materials). Both work from static JSON on
  GitHub Pages and sync favorites to the backend when it runs.
  `labs/materials.html` links to the full library; `projects.html`
  editor shows selected materials with add/remove.
- **AI prep:** the materials API is the structured retrieval
  system — search / compare / recommend / select, all with
  reasons and trade-offs computed from stored data. Documented
  in `docs/MUSE_INTEGRATION.md`.

## 21. Stage 4 file map (additions)

```
materials.html  material.html
assets/js/materials-library.js  assets/js/material-detail.js
data/material_categories.json
backend/test_stage4.py
docs/MATERIALS.md  docs/TEST_RESULTS_STAGE4.md
(changed: data/materials.json, assets/js/materials.js,
 assets/js/projects.js, assets/css/style.css, backend/app.py,
 backend/db.py, db/schema.sql, docs/ARCHITECTURE.md,
 docs/STATUS.md, docs/MUSE_INTEGRATION.md, backend/api-spec.md,
 README.md, index.html, projects.html, labs/materials.html,
 all navs)
```

---

# Stage 5 — 3D Modelling Workspace (19 Nov 2026)

## 22. What changed

- **Kernel:** `assets/js/model-kernel.js` — mesh-based CSG
  (three-bvh-csg 0.0.16). Parametric primitives, extrusions,
  revolves, 11 library components, real booleans, holes,
  rounded/chamfered boxes, mesh volumes, STL/OBJ/GLB export,
  STL/OBJ/GLB import. `assets/js/model-math.js` is the pure-JS
  companion: units, analytic volumes, shared validation.
- **Modeller UI:** `workspace.html` + `assets/js/modeller.js` —
  viewport (orbit/pan/zoom, gizmos, selection, grid/axes,
  perspective/ortho, 6 views, section, exploded, wireframe),
  add-primitive/component panels, boolean/hole tools, inspector
  (dimensions in the selected unit, position/rotation, material,
  tolerance, parent, visibility, duplicate/delete), assembly
  tree, project select, save/autosave, import/export. The old
  Stage 1 conceptual presets are replaced by five real example
  models (`workspace/test-models/`).
- **Backend:** `backend/model.py` mirrors the JS validation and
  analytic volumes; `backend/app.py` gains the model API
  (`/api/v1/model/schema`, project model CRUD, component
  add/patch/delete, validate, JSON export) with version-aware
  saves (409 on a stale base_version) and the same owner-only
  404 rules as projects. `do_PUT` was added to the HTTP handler
  (it was missing — PUT previously returned 501).
- **Tests:** `backend/test_stage5.py` (56/56), `backend/test_stage5_math.js`
  (29/29), `backend/test_stage5_kernel.mjs` (28/28 headless,
  real geometry + real CSG + real volumes; GLB skipped in Node,
  needs the browser's FileReader).
- **Limits, stated in the UI and in docs/MODELLING.md:** mesh
  kernel, not B-rep; fillets/chamfers on boxes only; simplified
  gear teeth; partial revolves built as full revolves; no
  STEP/3MF/FCStd; no React Three Fiber (no build step).

---

# Stage 6 — Physics and Simulation Foundation (19 Nov 2026)

## 23. What changed

- **Analytical solvers:** `backend/solvers.py` — pure-stdlib
  closed-form solvers (cantilever, simply supported beam,
  axial bar, torsion, 1-D conduction, lumped thermal,
  drag/lift, free fall) with a `SOLVER_REGISTRY` (label,
  method, engine, status, inputs, outputs, required material
  properties, assumptions). Missing material properties are
  errors, never substitutions. FEA/CFD are registry entries
  with status `not_implemented` and no implementation.
- **Job system:** the Stage 1 `simulations` table is now
  used for real. `backend/app.py` gains `GET /api/v1/solvers`
  and the simulation job API (create/run, list, get, delete,
  post browser results), all owner-scoped. Analytical jobs
  run synchronously and store method + assumptions + values;
  rigid-body jobs queue for the browser; FEA/CFD jobs are
  recorded `not_implemented` with no results.
- **Rigid-body engine:** Rapier 0.14.0 (MIT/Apache) via
  jsDelivr CDN, validated headlessly 9/9 against analytical
  references (`backend/test_stage6_rapier.mjs`).
- **Simulation workspace:** `simulate.html` +
  `assets/js/simulate.js` — three tabs: Rigid-body (Rapier)
  with project/model loading, per-body type, gravity,
  restitution, friction, impulse/continuous forces, Rapier
  spring joints, fixed/revolute joints, live state table,
  height + energy charts, results saving to a job;
  Analytical solvers with a per-solver input form (section
  builder in mm, material select from Stage 4) and results
  with units, method badge, assumptions and a safety-factor
  verdict; Simulation jobs list with view/delete.
- **Docs:** `docs/SOLVERS.md` (architecture + FEA/CFD
  investigation), `docs/VALIDATION_STAGE6.md` (benchmarks
  with measured errors), `docs/TEST_RESULTS_STAGE6.md`.
- **Tests:** `backend/test_stage6.py` 29/29;
  `backend/test_stage6_rapier.mjs` 9/9. Stages 2–5 suites
  still green (their health assertions accept stage 6).
- **Limits, stated in the UI and docs:** no FEA/CFD
  installed (checked 19 Nov 2026); analytical results are
  labelled analytical, never FEA; collision shapes are
  bounding boxes (ball for spheres); KE chart is
  translational only; electrical simulation is still the
  Stage 1 stub.
