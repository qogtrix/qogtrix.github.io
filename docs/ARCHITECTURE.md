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
