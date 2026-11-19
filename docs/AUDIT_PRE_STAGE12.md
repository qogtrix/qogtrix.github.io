# Pre-Stage 12 Audit — AI Engineering Laboratory

**Date:** 19 November 2026
**Scope:** Stages 1–11, as deployed at https://qogtrix.github.io/ (commit
`74b26b07`, after this audit's fixes) and as built in
`~/workspace/ai-engineering-lab/`.
**Rule:** nothing is hidden. Failed checks are listed with their cause and
fix. A test was only changed when the old expectation was itself wrong, and
each such change is explained where it happened.

## Verdict in one paragraph

The platform is in good engineering health: every solver I checked against
an independent hand-computed reference was right, the two-user isolation
holds at the API level, the database is sound, and all 637 automated tests
pass. I found and fixed **11 real bugs**, the worst being that the first
save of a fresh 3D model failed with a 400, and a concurrency race that
could silently lose an edit. The single biggest product gap is not a bug:
**there is no hosted backend**. The live site is a static frontend; a
visitor who opens qogtrix.github.io cannot sign in, save, simulate, or use
the assistant unless they run the backend on their own machine. Everything
else below is detail.

## How the audit was done

| Area | Method | Result |
|---|---|---|
| Regression | All 10 Python suites + JS math suites, re-run after every fix | 637/637 Python, 29/29 + 36/36 JS |
| Engineering accuracy | 35 independent spot-checks with fresh inputs vs hand-computed analytical references | 35/35 |
| Multi-user isolation + security | 53 live probes on a temp server (two users, Alice/Bob) | 53/53 |
| Database integrity | 15 checks: FKs, cascades, concurrency, recovery | 15/15 |
| Cross-stage integration | 6 end-to-end workflows through the real API | 21/21 |
| Performance + stability | Measured timings, 200 concurrent requests, large models | See §7 |
| Real browser | Cloud browser on the deployed site, signed-out visitor | See §8 |
| Deployment | Live files hashed vs source, HTTPS, secret scan | See §9 |

Audit scripts (kept out of the repo so they never deploy):
`~/workspace/audit_accuracy.py`, `audit_security.py`, `audit_db.py`,
`audit_integration.py`, `audit_perf.py`.

## 1. Bugs found and fixed

### 1.1 First save of a fresh model failed (400) — HIGH
`backend/app.py`, `backend/model.py`, `assets/js/model-math.js`,
`backend/test_stage5.py` (+1 test, now 60/60).

The frontend sends a fresh model with `version: 0` (the not-yet-saved
state). The PUT handler ran `validate_model` *before* stamping the
server-assigned version, so validation rejected it:
"model.version must be a positive integer". Reproduced live: a user who
built their first model and hit Save got a 400. The frontend's own
pre-save check had the same rule, so the save never even left the browser.

Fix: all four document PUT handlers (model, structure, aerospace, robot)
now stamp the server-assigned version *before* validating. The validators
in `model.py` and `model-math.js` now accept version 0 as "not yet saved"
and reject only negative/non-numeric versions. The workspace's empty
canvas no longer shows the "model.version must be a positive integer"
warning.

### 1.2 Mechanical "Load demo" threw a JavaScript error — HIGH
`assets/js/mechanical.js`, `assets/js/simulate.js`.

`evaluateModel` is async (it awaits CSG booleans), but `buildViewer` in
mechanical.js used its result synchronously: `res.errors` was undefined,
so loading any demo failed with
"Cannot read properties of undefined (reading 'length')". The same bug
existed in `simulate.js` (`buildSceneAndWorld` destructured the Promise).
Both viewers are now async and await the evaluator; call sites await them.
This was found by the real-browser test, not by reading code.

### 1.3 Concurrent edits could silently lose data — MEDIUM
`backend/app.py`, `backend/test_stage5.py` (+3 race tests).

The four document PUT handlers checked `base_version` in Python and then
saved with an unconditional UPDATE. Two concurrent PUTs with the same
base version both passed, and one edit was silently lost. Saves now use
an atomic conditional UPDATE (`... WHERE version = candidate_version − 1`);
losers get a clean 409. Verified live: 5 concurrent PUTs → exactly one
200, four 409s, winner intact.

### 1.4 Trajectory integrator overran the burn window by one step — MEDIUM
`backend/aerospace.py`, `backend/test_stage10.py` (+1 test).

Float accumulation (`0.1 × 10 = 0.9999999999999999 < 1.0`) fired an extra
thrust step: a 1 s burn at dt=0.1 gave apogee 2346.7 m instead of the
correct 1939.8 m (21% error; dt=0.01 was exact). Fixed with a 1e-9
tolerance on the exclusive burn-end boundary.

### 1.5 Diff-drive treated m/s as rad/s — MEDIUM
`backend/robotics.py`, `workspace/test-robots/wheeled_robot.json`,
`assets/js/robotics.js`, `docs/AEROSPACE_ROBOTICS.md`,
`backend/test_stage10.py` (4 checks corrected).

`diff_drive_fk` multiplied the wheel speeds by the wheel radius, so
0.5 m/s in came out as 0.05 m/s with a 0.05 m wheel; `diff_drive_ik`
divided by the radius and returned rad/s under an m/s name. Both now use
true linear m/s semantics (`v = (vl+vr)/2`, `ω = (vr−vl)/L`).
Demo values, frontend defaults and docs updated to match. The test
changes are a technically justified correction of the same unit error,
not a loosened expectation.

### 1.6 Solver silently ignored typo'd inputs — MEDIUM
`backend/solvers.py`, `backend/test_stage6.py` (+1 test).

`run_solver` ignored unknown input keys, so a misspelt parameter computed
with a default and returned a wrong-but-plausible number. Unknown keys
now raise ValueError naming them (allowed extras: `material_id` and
`_`-prefixed keys). Also fixed: the `drag` solver read `length_m` for its
Reynolds number but never declared it in the registry.

### 1.7 CORS was `Access-Control-Allow-Origin: *` — MEDIUM
`backend/app.py`.

Any website could make credentialed requests to a locally running lab
backend. The origin is now reflected only for an allowlist
(`https://qogtrix.github.io`, `null`, `http://127.0.0.1` and
`http://localhost`, with or without a port). A lookalike
`http://127.0.0.1.evil.com` is refused — a bare-prefix check would have
been a bypass, caught during implementation.

### 1.8 Server header leaked the Python version — LOW
`backend/app.py`. `Handler.version_string()` now returns `AIELab`.

### 1.9 Circuit simulate stored invalid circuits as "failed" jobs — LOW
`backend/app.py`, `backend/test_stage8.py` (+1 test, now 72/72).

`POST /api/v1/circuits/simulate` ran the solver on any circuit and stored
a "failed" job for structurally invalid ones (e.g. an unsupported
`dc_motor` component). It now runs `validate_circuit` first and returns a
clear 400. The old test expected the failed-job behaviour for a no-ground
circuit; it was updated to the new behaviour, and a new check covers the
case that must still be a failed job: a circuit that validates but fails
numerically (two conflicting voltage sources in parallel → singular
matrix).

### 1.10 Assistant side panels hung on "Loading…" for guests — LOW
`assets/js/assistant.js`.

For a signed-out visitor the init returned before `loadStatus()` ran, so
"Assistant status", "Your usage" and "What it can do" stayed on
"Loading…" forever with no error. They now show "Sign in to see…"
messages. Found by the real-browser test.

### 1.11 Silent no-ops for guests in Electrical / Mechanical — LOW
`assets/js/electrical.js`, `mechanical.html`.

Electrical "Run simulation" and "Calculate" told a guest to sign in when
the real problem was that the backend is unreachable (sign-in is
impossible without it). Both now check a `backendDown` flag set when the
solver list fails to load, and say the backend is not reachable first.
The mechanical gear-train placeholder text was identical to the no-gear
message, so clicking Calculate visibly changed nothing; the placeholder
now says no result has been computed yet.

## 2. Engineering accuracy — 35/35 independent checks

Fresh inputs, hand-computed references, no reuse of the code's own
expected values. Covered: cantilever and simply-supported beam
deflections (FL³/48EI, FL³/3EI), gear ratio/torque, shaft von Mises
identity, spring rate, belt length, DC motor, RLC/RC time constants,
battery, NACA Cl, Tsiolkovsky delta-v, IK/FK round trip, Euler column
buckling, direct-stiffness cantilever reactions and equilibrium, section
properties, IS 875 wind pressure, multirotor momentum theory, material
null-refusal, 7 invalid-input rejections.

Non-bugs confirmed during the audit: PID steady-state error converges to
R·T/(Kt·Kp) (my first 8 s check was too short — the plant time constant
is ~6 s; at 40 s the error is 0.631 vs the reference 0.625). The wind
solver's k1–k3 subset is documented behaviour (k4 is not modelled).

## 3. Multi-user isolation + security — 53/53

Live temp server, two users (Alice/Bob). Verified: duplicate
email/username rejected; bad email, short username, short password
rejected; SQL injection blocked everywhere (parameterised queries — an
injection payload in materials search returns 0 rows as a literal
string); XSS payload in a project name stored as inert data; Bob gets 404
on every Alice resource (project read/PATCH/DELETE, model, structure,
aerospace, robot, simulations, assistant conversations/messages); public
projects are readable anonymously but hide the owner's email and show
only `@username`; Bob cannot edit or read the model of a public project;
assistant conversations and usage are fully separated; unauthenticated
requests get 401; tampered tokens get 401; wrong passwords get 401; login
rate limit trips with 429 after 5 failures; API keys list only their
owner's projects; 404s carry no stack traces; `/health` reports Stage 11.

Frontend XSS review: clean — every page defines `esc()`; the assistant's
`renderMd` escapes before formatting; `projects.js` escapes names and
descriptions. No file-upload endpoint exists. Logout revokes sessions.
Password minimum is 8 characters. `.secret` is mode 0600. The backend has
zero pip dependencies. Frontend CDN dependencies are version-pinned
(three 0.160.0, rapier 0.14.0, three-bvh-csg 0.0.16, three-mesh-bvh 0.7.0)
but have **no SRI hashes** — a supply-chain note, not a failure.

## 4. Database integrity — 15/15

Foreign keys enforced (a project with a nonexistent owner fails);
`init_db` is idempotent and preserves data; 10 concurrent project creates
all land with distinct ids; a failed transaction rolls back fully;
deleting a project cascades to its simulations and SET NULLs its
conversations' `project_id` (the conversation row survives); deleting a
user cascades to projects and conversations; the materials table has
exactly 38 rows with no duplicate ids; re-seeding does not duplicate.

## 5. Cross-stage integration — 21/21

Six workflows through the real API, all passing: W1 mechanical assembly
+ steel-1045 material + gear-train simulation (ratio 2, 750 rpm,
15.2 N·m; model volumes use material density); W2 driver circuit (12 V
source, 1.5 Ω + 1.5 Ω → motor terminal exactly 6 V) feeding the separate
dc_motor solver (no-load 1145.9 rpm at 6 V); W3 structural model + point
load + DSM analysis (reactions sum to exactly 60000 N); W4 robot arm
saved, FK + motor_check + link_check; W5 aircraft design saved,
performance (stall ≈10.69 m/s, L/D ≈11.12), spar check present (Stage 9
link), CG ≈0.59 m from components; W6 assistant runs the real cantilever
solver and its numbers match a direct solver call (3.375e-04 m).

Two W5 failures during the audit were my script's fault, not the code's:
the design used a nested `wing` object while the real schema is flat,
and the CG check read `centre_of_gravity_m` instead of `cg_x_m`. Both
were corrected in the audit script.

## 6. Regression — 637/637

| Suite | Tests |
|---|---|
| Stage 2 | 34/34 |
| Stage 3 | 34/34 |
| Stage 4 | 42/42 |
| Stage 5 | 60/60 (was 56: +3 race, +1 fresh-model save) |
| Stage 6 | 30/30 (was 29: +1 unknown-key rejection) |
| Stage 7 | 99/99 |
| Stage 8 | 72/72 (was 71: +1 circuit validation) |
| Stage 9 | 80/80 |
| Stage 10 | 141/141 (was 140: +1 trajectory boundary) |
| Stage 11 | 45/45 |
| JS math (Stage 5) | 29/29 |
| JS math (Stage 7) | 36/36 |
| **Total Python** | **637/637** (baseline before the audit: 630) |

Every test that was changed is explained in §1 (diff-drive unit
correction, circuit validation behaviour, downstream version numbers in
Stage 5 after the extra save). No expected value was changed to make a
test pass.

## 7. Performance + stability (measured on this machine)

- `/health` p50 2.0 ms, p95 3.8 ms.
- Materials list p50 11.2 ms. Gear solver p50 4.2 ms. Assistant message
  p50 5.6 ms.
- Large model PUT (200 components): 16.7 ms; GET 11.0 ms.
- Large DSM (99 nodes, 147 truss elements): 382.6 ms, completed.
- Concurrent load: 10 threads × 20 solver calls = 200 requests in 1.13 s
  (177 req/s), p50 29.4 ms, p95 158.3 ms, **0 errors**.
- 35 rapid assistant messages: 10 ok, 25 rate-limited — the 30/min limit
  working as designed (the earlier benchmark had already used 20 in the
  same window).
- Server RSS 26.0 → 34.9 MB over the whole run (+8.9 MB including the
  200-component model and the 147-element DSM) — no leak evident.

No claim is made about supported user counts: these are single-machine
measurements, not a production load test. There is no production backend
to load-test against (see §9).

## 8. Real-browser testing of the deployed site

Cloud browser, signed-out visitor, 19 Nov 2026 ~10:48–10:51 UTC.

- **Home page loads fully**: hero, 6 lab cards, system status, 5
  in-browser checks all "OK" (WebGL, storage, lab/material/component
  data). No 404s on any link followed; docs pages load.
- **Every lab page loads and renders**: workspace (3D grid, axes, library),
  mechanical, electrical, structural, aerospace, robotics (client-side FK
  result renders: end effector x 0.85, y 0.00, z 0.53 m), materials (38
  materials, 10 categories, search/filters work), assistant, simulate,
  gallery.
- **Registration attempt** (one authorised test account): no account was
  created; the page showed a clear red banner — "Cannot reach the backend
  at http://127.0.0.1:8001. Start it with: cd backend && python3 app.py —
  Failed to fetch". Good, explicit failure, not a silent one.
- **Guest client-side features that work**: electrical demo load
  ("Voltage divider — 4 components, 4 wires"), circuit Validate
  ("✓ Circuit looks valid"), materials search, robotics FK, tab switching.
- **Defects found by the browser** (all fixed in §1): mechanical demo
  load threw a JS error (§1.2); assistant panels hung on "Loading…"
  (§1.10); electrical run/calculate were silent or misleading no-ops
  (§1.11); horizontal overflow at ~500 px on lab pages (tab bars cut
  off — fixed with scrollable tab bars and a wrapping topbar).
- **Outdated copy found**: the home page still said "NO SIMULATOR YET"
  and "Stage 1 is the foundation… Simulators are Stage 2". Updated to
  "STAGES 1–11 LIVE" with an honest statement that the backend runs
  locally. `docs/STATUS.md` is actually current (it has Stage 11
  sections); the browser's note about it was a misreading of the Stage 1
  header, not a defect.
- **Limitations of this browser test**: no DevTools console or network
  panel was available, so no exact console messages or HTTP statuses
  could be quoted; the narrow-width check was at ~500 px, not exactly
  390 px — re-check 390 px with a real viewport. `projects.html` and
  `settings.html` redirect guests to `auth.html` (by design).

## 9. Deployment verification

- HTTPS live with HSTS (`max-age=31556952`), served by GitHub Pages.
- All 8 files changed by this audit were hashed live vs local after the
  deploy — **all match**; the new home copy ("STAGES 1–11 LIVE") is live.
  Deploy commit `74b26b07`, 132 files.
- **Backend source is publicly served** (`backend/app.py`, `auth.py`,
  `db.py`, `db/schema.sql` all return 200). No secrets in it — the only
  matches for "password"/"secret" are code references. The repo itself is
  public on GitHub, so this is transparency, not a leak — but the files
  serve no purpose on a static host. `.secret` and `aielab.db` correctly
  return 404 (excluded from the deploy manifest).
- **The deployed site is frontend-only.** `assets/js/config.js` defaults
  the API base to `http://127.0.0.1:8001`. A normal visitor cannot
  register, sign in, save, simulate, or use the assistant. The frontend
  is honest about this (banners and error messages say to start the
  backend), but it means the live site is a demo of the frontend, not a
  working product. There is no production backend to deploy to — the
  backend is SQLite + stdlib `http.server`, designed to run locally.

## 10. Feature classification

| Feature | Status |
|---|---|
| Materials database (38 materials, nulls never invented) | Verified working |
| 3D modelling workspace (CSG, assemblies, export) | Verified working (demo-load bug fixed) |
| Mechanical solvers (11) | Verified working |
| Electrical MNA solver (DC/transient/AC) | Verified working |
| Structural DSM solver + IS 875/1893 calculators | Verified working |
| Aerospace + robotics solvers | Verified working |
| AI Assistant (local engine, 27 tools, provenance) | Verified working |
| Accounts, per-user isolation, public gallery | Verified working |
| Versioned saves, optimistic concurrency | Verified working (race fixed) |
| First save of a fresh model | Verified working (was failing — fixed) |
| Real-browser guest experience | Partially verified (500 px, no console access; 390 px untested) |
| Mobile layout at 390 px | Not verified |
| FEA / CFD | Not implemented (by design — recorded, never faked) |
| Code compliance (IS 800 / IS 456 / AISC / Eurocodes) | Not implemented |
| Hosted production backend / live sign-in | Not implemented — the one deployment gap |
| SRI hashes on CDN dependencies | Not implemented (note) |

## 11. Remaining bugs / incomplete capabilities

1. Mobile layout at exactly 390 px is unverified (only ~500 px checked).
2. No SRI hashes on the pinned CDN scripts.
3. No hosted backend — the largest gap; needs a hosting decision (a
   small VPS or a serverless rewrite) before the live site can offer
   accounts at all.
4. `trajectory_2d` has no initial-velocity input (API gap, pre-existing).
5. Wind solver models k1–k3 only (documented subset, not a bug).
6. No plate/shell/solid FEA, no CFD, no code compliance — all documented
   as not implemented, never faked.

## 12. Recommended priorities before Stage 12

1. **Decide the backend hosting story.** Until there is one, the live
   site cannot be used by anyone but a developer running it locally.
   This is the single decision that changes the product's status.
2. Verify the 390 px layout with a real viewport.
3. Add SRI hashes to the four pinned CDN scripts.
4. Then Stage 12, with Karan's explicit approval.
