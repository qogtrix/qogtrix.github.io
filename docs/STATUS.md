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

---

# Stage 2 — User Accounts and Personal Workspaces (19 Nov 2026)

## Completed in Stage 2

- [x] Registration + login + logout + profile + change password, with
      proper error handling (400/401/409/429) and loading/empty/error states
- [x] Persistent sessions (7-day HMAC-signed tokens, revocable on logout)
- [x] Secure password handling: PBKDF2-HMAC-SHA256, 200k iterations,
      per-user salt; only hashes stored
- [x] Personal workspaces: Dashboard, My Projects, Recent Work (5 latest),
      Laboratories, Account Settings — one workspace per user
- [x] Project management: create (name/description/lab), search, lab
      filter, open + continue, rename, duplicate, delete with confirmation,
      save progress (payload JSON) — all server-side, owner-scoped
- [x] Ownership isolation: owner_id on every project, backend checks on
      every endpoint, other users' projects return 404; Postgres RLS
      policies defined in db/schema.sql
- [x] Muse integration prep: scoped API keys (aielab_…), shown once,
      hash stored, revocable, owner-bound — see docs/MUSE_INTEGRATION.md
- [x] Frontend: auth.html, projects.html, settings.html + auth.js /
      projects.js / config.js, in the existing dark theme, responsive
- [x] Backend implemented for real (stdlib only, SQLite): backend/app.py,
      auth.py, db.py — no pip install needed
- [x] Tests: 34/34 passed with two accounts (Alice/Bob) — see
      docs/TEST_RESULTS_STAGE2.md; plus a live curl check as Karan
- [x] Docs updated: ARCHITECTURE.md (Stage 2), api-spec.md, STATUS.md,
      MUSE_INTEGRATION.md, TEST_RESULTS_STAGE2.md, RUN_DEPLOY.md

## Incomplete / explicitly NOT in Stage 2

- [ ] Simulation solvers (still Stage 3)
- [ ] AI agent runtime connected via API key (contract + keys only)
- [ ] Email verification / password reset by email
- [ ] Live Postgres deployment with RLS executed (policies defined,
      SQLite tested; backend checks are the tested layer)
- [ ] GitHub Pages cannot run the backend — the static site shows the
      Stage 2 frontend with a "backend must be running" state; the
      working authenticated app is the hosted fullstack version
