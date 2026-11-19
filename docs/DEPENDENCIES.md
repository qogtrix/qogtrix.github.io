# Dependencies — Stage 1

All Stage 1 runtime dependencies are open-source. No paid API is used.
No dependency is installed locally for the static site — the only
runtime CDN dependency is Three.js. Everything else is plain browser code.

## Runtime (loaded in the browser)

| Dependency | Version | Licence | Used for | How loaded |
|---|---|---|---|---|
| Three.js | 0.160.0 | MIT | 3D workspace rendering | CDN import map: `https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js` |
| OrbitControls (Three.js examples) | 0.160.0 | MIT | Orbit / zoom / pan in the 3D workspace | CDN: `https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js` |
| System fonts | — | — | UI text (`system-ui, Segoe UI, Roboto, sans-serif`; monospace for data) | No download |

No CSS framework, no JS framework, no chart library, no analytics
in Stage 1. Keeping this list at one library is deliberate: fewer
moving parts, faster load on GitHub Pages, easier audit.

## Development / verification (already on this machine)

| Tool | Version found 19 Nov 2026 | Used for |
|---|---|---|
| Node.js / npm | v24.22.1 / 10.9.4 | Optional local check; no build step in Stage 1 |
| Python 3 | 3.12.3 | `python3 -m http.server` for local preview; backend skeleton (Stage 2) |
| Git | 2.43.0 | Version control / deployment |
| GitHub Pages | — | Free static hosting for `qogtrix.github.io` |

## Backend skeleton (prepared, NOT running in Stage 1)

Listed in `backend/requirements.txt`. Installed only when Stage 2
backend work starts:

- `fastapi` — API framework
- `uvicorn[standard]` — ASGI server
- `pydantic` — request/response validation (comes with FastAPI)
- `sqlalchemy` — ORM matching `db/schema.sql`

No solver library is listed yet — solver choice is a Stage 2 decision
(see `docs/ARCHITECTURE.md` §5).

## How to audit

- Open any page → View Source → the only external scripts are the
  two Three.js CDN URLs above.
- `data/*.json` are plain data files; no hidden network calls are made
  by `assets/js/*.js` except fetching those local JSON files and the
  Three.js CDN.

## Stage 5 additions

- **three-bvh-csg 0.0.16 (MIT)** — real CSG booleans on triangle
  meshes (union / subtract / intersect) and mesh volume
  (`computeMeshVolume`). Peer dependency: three-mesh-bvh.
  Loaded from jsDelivr CDN in `workspace.html`'s import map.
- **three-mesh-bvh 0.7.0 (MIT)** — BVH acceleration for
  three-bvh-csg. Also from jsDelivr CDN.
- No other new dependencies. No paid APIs, no build step.

## Stage 6 additions

- **@dimforge/rapier3d-compat 0.14.0 (MIT/Apache)** — real
  rigid-body physics engine (WASM), loaded from jsDelivr CDN
  in `simulate.html`'s import map. Validated headlessly in
  `backend/test_stage6_rapier.mjs` (9/9).
- No other new dependencies. Analytical solvers are pure
  Python stdlib (`backend/solvers.py`). No FEA/CFD solver is
  installed (checked 19 Nov 2026).
