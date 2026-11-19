# API Spec — Stage 2 (implemented, tested)

Base: `/api/v1`. Backend: `backend/app.py` (stdlib, SQLite).
Auth: `Authorization: Bearer <session token>` or
`Authorization: Bearer aielab_<api key>`.

## Health (public)

`GET /health` → `{"status":"ok","stage":2,"solver_available":false}`

## Auth

| Method & path | Body | Success | Errors |
|---|---|---|---|
| `POST /api/v1/auth/register` | `{email, password>=8, name}` | 201 `{user, token}` | 400 validation, 409 email exists |
| `POST /api/v1/auth/login` | `{email, password}` | 200 `{user, token}` | 401 wrong credentials, 429 too many failures |
| `POST /api/v1/auth/logout` | — (auth) | 200 `{ok:true}` — session revoked | 401 |
| `GET /api/v1/auth/me` | — (auth) | 200 `{user}` | 401 |
| `PATCH /api/v1/auth/me` | `{name}` | 200 `{user}` | 400, 401 |
| `POST /api/v1/auth/change-password` | `{current_password, new_password>=8}` | 200 — other sessions revoked | 400, 401 |
| `POST /api/v1/auth/api-keys` | `{name}` | 201 `{id, name, key_prefix, key}` — key shown **once** | 401 |
| `GET /api/v1/auth/api-keys` | — (auth) | 200 `{api_keys:[...]}` (hashes never returned) | 401 |
| `DELETE /api/v1/auth/api-keys/{id}` | — (auth) | 200 — key revoked | 401, 404 |

## Projects (auth required, always owner-scoped)

| Method & path | Notes |
|---|---|
| `GET /api/v1/projects?q=&lab=` | Only the caller's projects, newest first. `lab` must be a known lab. |
| `POST /api/v1/projects` | `{name 2–120, description, lab, payload{}}` → 201 |
| `GET /api/v1/projects/{id}` | 404 if the project is not the caller's (no existence leak) |
| `PATCH /api/v1/projects/{id}` | Rename / edit description / lab / save `payload` progress |
| `POST /api/v1/projects/{id}/duplicate` | Copy with ` (copy)` suffix, new id, same owner |
| `DELETE /api/v1/projects/{id}` | Deletes only the caller's project |

All project errors: 401 unauthenticated, 404 not yours / not found,
400 validation.

## Unique usernames (Stage 3)

- Register now requires `username` (3–30 chars, `[a-z0-9_]`, unique
  case-insensitively) → 409 if taken.
- Login accepts `email` **or** `username` as the identifier.
- `PATCH /api/v1/auth/me` accepts `username` (409 if taken).
- Public responses show `owner_username` only — never email.

## Visibility (Stage 3)

- `POST /api/v1/projects` — new projects are **always private**;
  a `visibility` value in the request is ignored.
- `POST /api/v1/projects/{id}/publish` — owner only → `public`.
- `POST /api/v1/projects/{id}/unpublish` — owner only → `private`.
- `PATCH /api/v1/projects/{id}` — owner may set `visibility`
  to `private` or `public`.
- Duplicates are always created private.
- `GET /api/v1/projects?visibility=private|public` — owner's own
  projects, filterable by visibility.

## Public gallery (Stage 3, no auth required)

- `GET /api/v1/public/projects?q=&lab=` — public projects only,
  newest first. Response contains no `email` or `owner_id`.
- `GET /api/v1/public/projects/{id}` — public project detail
  (read-only); 404 for private or nonexistent projects.

## Material database (Stage 4)

All material endpoints are public except favorites (auth) and
project material selection (owner). Material data is reference
data — typical published values, never certified datasheet values.
Missing properties are `null` and listed in `missing_properties`.

- `GET /api/v1/material-categories` — 10 categories with counts.
- `GET /api/v1/materials?q=&category=&min_tensile=&max_density=&min_melting=&max_cost=&min_corrosion=&sort=`
  — list with filters; sort ∈ name | strength_to_weight | density |
  tensile | cost. Response: `{materials, count, total, notice}`.
  Each material carries `properties` (16 keys, null when unknown),
  `derived` (strength_to_weight_kn_m_kg, specific_stiffness),
  `missing_properties`, plus convenience top-level fields
  (density, tensile_strength, yield_strength, youngs_modulus,
  melting_point, thermal_conductivity, poisson).
- `GET /api/v1/materials/{id}` — full detail incl. source,
  standard, confidence, test_conditions, temperature_range_c,
  cost_index, corrosion_resistance + notes.
- `GET /api/v1/materials/compare?ids=a,b,c` — 2–4 materials;
  19 comparison rows (properties + derived + cost + corrosion)
  with `best` = index of the best value, or null when missing /
  not comparable. 400 for <2 or >4 ids, 404 for unknown id.
- `POST /api/v1/materials/recommend` — body: min_tensile_mpa,
  max_density_kg_m3, min_melting_point_c, max_cost_index,
  min_corrosion, category, limit (default 5, max 10). Hard filters
  first, then score = 50% strength-to-weight + 30% specific
  stiffness + 20% low cost (each normalized to the best candidate
  in the result set). Returns `{candidates: [{material, score,
  reasons, trade_offs}], excluded, total_considered, scoring}`.
  Impossible requirements return an empty list, never fake data.
- `GET|POST /api/v1/materials/favorites` (auth) — per-user
  favorites; `DELETE /api/v1/materials/favorites/{id}`.
- `POST /api/v1/projects/{id}/materials` (owner) — body
  `{material_id}`; appends to `payload.materials`.
  `DELETE /api/v1/projects/{id}/materials/{material_id}` (owner).

## 3D models (Stage 5)

Models live in a project's payload (`payload.model`).
All model endpoints are owner-only (session or agent token);
another user's project returns 404, unauthenticated returns 401.
Saves are version-aware: send `base_version`; a stale base
returns 409.

- `GET /api/v1/model/schema` (public) — the model format:
  units, component types, primitive/component kinds, boolean
  ops, component fields, notes.
- `GET /api/v1/projects/{id}/model` — the stored model
  `{version, units, components}` plus per-component analytic
  volumes and masses (`volumes: [{id, volume_mm3, exact, note,
  mass_kg}]`).
- `PUT /api/v1/projects/{id}/model` — body `{model, base_version?}`;
  validates the whole model (same rules as
  `assets/js/model-math.js`), bumps the version, returns the
  saved model + volumes. 400 on invalid, 409 on stale base.
- `POST /api/v1/projects/{id}/model/validate` — body `{model}`;
  returns `{valid, errors, volumes}` without saving.
- `POST /api/v1/projects/{id}/model/components` — body
  `{component}`; validates, appends, bumps the version. 201.
- `PATCH /api/v1/projects/{id}/model/components/{cid}` — merge
  fields (name, kind, type, params, position, rotation, scale,
  material_id, color, visible, parent_id, tolerance_mm,
  constraints); revalidates the whole model; bumps the version.
- `DELETE /api/v1/projects/{id}/model/components/{cid}` — 400 if
  another component still references it (parent or boolean
  operand).
- `GET /api/v1/projects/{id}/model/export?format=json` — model +
  volumes. Other formats return 400: STL/OBJ/GLB export runs in
  the browser workspace (three.js exporters); STEP/3MF/FCStd are
  not supported by the mesh kernel.

Analytic volumes are exact for box/cylinder/sphere/cone/torus/
extrude/revolve/shaft/pipe/beam/bolt/nut/spring/motor/enclosure,
estimates for rounded_box/gear/bearing/piston, and null for
booleans/imported meshes (measured from the mesh in the browser).

## Simulation jobs (Stage 6)

- `GET /api/v1/solvers` (public) — the solver registry: label,
  method, engine, status (available / browser /
  not_implemented), inputs, outputs, required material
  properties, assumptions.
- `POST /api/v1/simulations` (auth) — body `{project_id,
  solver, inputs}`. The project must belong to the caller
  (404 otherwise). Analytical solvers run synchronously and
  the job is stored `completed` with `{method, engine,
  assumptions, values}` — or `failed` with `{"error": ...}`
  when an input or a required material property is missing.
  `rigid_body` jobs are stored `queued` for the browser.
  `fea` / `cfd` jobs are stored `not_implemented` with no
  results and an explanatory note. Unknown solver → 400.
- `GET /api/v1/simulations?project_id=` (auth, owner) — list.
- `GET /api/v1/simulations/{id}` (auth, owner).
- `POST /api/v1/simulations/{id}/results` (auth, owner) —
  body `{results}` with a `summary`; only for queued/running
  jobs (the browser posts rigid-body runs). A second post
  returns 400.
- `DELETE /api/v1/simulations/{id}` (auth, owner).

All results are labelled with their method; analytical
results are never FEA. See `docs/SOLVERS.md`.

Stage 7 adds eleven mechanical solvers to the same registry
and job API (no new endpoints): `gear_train`,
`shaft_combined`, `bearing_load`, `belt_drive`,
`spring_helical`, `flywheel`, `hydraulic_cylinder`,
`crank_slider`, `fatigue_shaft`, `vibration_1dof`,
`power_transmission`. Inputs are SI units; sections and
materials work exactly as in Stage 6. See
`docs/MECHANICAL.md` for the formulas and the assumptions of
each solver.

## Public data (read-only)

`GET /api/v1/materials`, `GET /api/v1/components` — served from
`data/*.json`.

## Simulations (not in Stage 2)

`POST /api/v1/simulate/*` → 501 Not Implemented. `results` stays
`null` until a real solver exists (Stage 3).

## Circuits (Stage 8)

- `GET /api/v1/circuits/schema` — public. The circuit JSON
  schema: component types, terminal counts, notes.
- `POST /api/v1/circuits/validate` — auth. Body
  `{circuit}`; returns `{valid, errors}`.
- `POST /api/v1/circuits/simulate` — auth, owner-scoped
  project. Body `{project_id, circuit, analysis}` where
  `analysis` is `{type: "dc"}` or `{type: "transient",
  duration, steps, output_nodes?}` or `{type: "ac",
  f_start, f_stop, points, output_node?}`. Runs the MNA
  solver and stores the result as a simulation job with
  solver `circuit_dc`, `circuit_transient` or `circuit_ac`
  (201 on success, 200 with status `failed` on a solver
  error). Components may use net names in `nodes`, or
  terminal labels plus a `connections` list (resolved by
  union-find); node `"0"` is ground.

Stage 8 adds eleven electrical solvers to the same registry
and job API (no new endpoints): `ohm_law`,
`series_parallel`, `rc_time_constant`, `rlc_resonance`,
`ac_power`, `transformer`, `dc_motor`, `battery_config`,
`motor_gearbox`, `solenoid`, `wire_resistance`. The circuit
solvers (`circuit_dc`, `circuit_transient`, `circuit_ac`)
are in the registry too, but they only run through the
circuit endpoint above — posting them to
`/api/v1/simulations` records a failed job explaining that.
See `docs/ELECTRICAL.md` for the solver's models and limits.
