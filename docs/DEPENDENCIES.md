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
