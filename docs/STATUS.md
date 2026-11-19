# Stage 1 — Completed vs Incomplete

**Date:** 19 Nov 2026
**Rule applied throughout:** nothing is marked complete unless it was
actually built and checked. Anything labelled "Stage 2" is not done.

## Completed in Stage 1

- [x] Environment inspected (Node 24.22.1, Python 3.12.3, Git 2.43.0,
      GitHub connected as `qogtrix`, GitHub Pages live at
      `qogtrix.github.io`, `qogtrix.is-a.dev` not yet live — PR #61755 open)
- [x] Technical architecture designed and documented (`docs/ARCHITECTURE.md`)
- [x] Modular project structure created (see `README.md` file map)
- [x] Premium dark-themed dashboard (`index.html`) — responsive
- [x] Navigation (sidebar desktop / hamburger mobile) across all pages
- [x] Six laboratory pages, each dedicated:
      Mechanical, Electrical, Structural, Aerospace, Robotics,
      Materials Science (`labs/*.html`)
- [x] 3D workspace with Three.js 0.160.0 (`workspace.html` + per-lab
      presets) — orbit/zoom/pan, wireframe, grid, auto-rotate, reset,
      preset switch, real geometry stats, screenshot export
- [x] Materials database (12 materials, typical published values,
      searchable / filterable / sortable table, detail view)
- [x] Component library (12 components, filterable by laboratory)
- [x] Projects: create / list / delete / export as JSON, stored in
      the browser (`localStorage`) — real, no server
- [x] System status panel on the dashboard — real runtime checks
      (WebGL, Three.js loaded, data files loaded, localStorage)
- [x] Backend architecture prepared: FastAPI skeleton (`backend/app.py`,
      only `/health` works), API spec (`backend/api-spec.md`)
- [x] Database architecture prepared: `db/schema.sql`
      (materials, components, projects, simulations, agent_runs)
- [x] AI-agent foundation prepared as a written contract
      (`docs/AI_AGENT.md`) — no agent runtime yet
- [x] Dependency list (`docs/DEPENDENCIES.md`)
- [x] Run / deploy instructions (`docs/RUN_DEPLOY.md`)
- [x] Error handling: WebGL fallback, CDN failure message, data-load
      failure state with retry, global error banner
- [x] Responsive desktop + mobile layouts
- [x] Deployed to GitHub Pages (`qogtrix.github.io`)

## Incomplete / explicitly NOT in Stage 1

- [ ] `qogtrix.is-a.dev` live — blocked on is-a.dev maintainer merge
      of PR #61755 (and #61759 for `leadloop.is-a.dev`). After merge:
      set Custom Domain in the repo Pages settings + Enforce HTTPS.
- [ ] Any engineering simulator (stress/FEA, thermal, CFD, circuit,
      dynamics, kinematics). Simulation sections are shown as
      "Stage 2 — Not yet implemented" with disabled controls.
- [ ] Backend server running anywhere (skeleton only; simulation
      endpoints return 501 Not Implemented by design).
- [ ] Server database (schema only; Stage 1 data lives in JSON files
      + browser `localStorage`).
- [ ] AI engineering agent runtime (contract only).
- [ ] User accounts / login.
- [ ] Real solver integration (open-source solver evaluation is Stage 2).

## Known limitations

- Three.js loads from jsDelivr CDN — the 3D workspace needs internet.
  If the CDN is unreachable, the page shows an error instead of a
  frozen canvas.
- Material values are *typical published values*, not certified
  datasheet values. They are labelled as such on every materials page.
  Verify against a datasheet before any design use.
- 3D presets are conceptual geometry previews, not engineering models
  and not simulation results.
