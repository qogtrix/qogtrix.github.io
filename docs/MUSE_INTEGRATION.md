# Muse Integration — Stage 2 preparation

**Status:** contract + API-key mechanism implemented and tested.
No Muse agent runtime is connected yet. Nothing here gives any
other user access to Karan's Muse session, credentials, browser
session, or private projects.

## How it will work

1. Karan (and only Karan, in his own account) creates an API key in
   Account Settings → Muse agent access. The key looks like
   `aielab_<48 hex chars>`, is shown **once**, and only its SHA-256
   hash is stored.
2. The Muse agent calls the same backend endpoints a human uses,
   with `Authorization: Bearer aielab_…`:
   - `GET /api/v1/projects` — list Karan's projects
   - `POST /api/v1/projects` — create a project / experiment
   - `GET / PATCH /api/v1/projects/{id}` — continue / save a design
   - `POST /api/v1/projects/{id}/duplicate` — branch an experiment
3. The key is bound to one `user_id`. Every project query still
   filters `owner_id = that user`, so the key can never reach
   another user's projects (tested: API key + another user's
   project id → 404).
4. Keys are revocable instantly in Account Settings. Revoking a key
   does not affect the user's password sessions.
5. Every agent action is logged in `agent_runs` (user_id,
   project_id, tools used) — see `db/schema.sql`.

## Rules carried forward from Stage 1 (docs/AI_AGENT.md)

- The agent may read materials/components/projects and propose
  geometry/parameters, but may never write a simulation result.
- Results may only appear when a real solver writes them.
- No other user's session, credentials, or projects are accessible
  through the agent's key, the API, or the database.
- A key must never be pasted into chat, committed to git, or shared.
  If one leaks, revoke it and create a new one.

---

## Materials (Stage 4) — structured retrieval for Muse

The materials API is the retrieval system the agent uses to search,
compare, recommend and select materials. It is read-only except for
favorites and project selection, which are owner-scoped like all
project writes (agent tokens work the same as session tokens).

- **Search:** `GET /api/v1/materials?q=aluminium&category=metals&min_tensile=500&max_density=3000&sort=strength_to_weight`
- **Detail:** `GET /api/v1/materials/{id}` — full properties, source,
  standard, confidence, `missing_properties` (never treat a missing
  value as zero), `derived` (strength-to-weight, specific stiffness).
- **Compare:** `GET /api/v1/materials/compare?ids=a,b,c` — 19 rows
  with a computed `best` index per row.
- **Recommend:** `POST /api/v1/materials/recommend` with hard
  requirements; returns ranked candidates with `score`, `reasons`
  and `trade_offs` computed from stored data, plus the scoring
  formula and the count of excluded materials. Explain trade-offs
  from those fields — do not invent new ones.
- **Select:** `POST /api/v1/projects/{id}/materials` with
  `{material_id}` — only for the agent owner's own projects.
- **Favorites:** `GET/POST/DELETE /api/v1/materials/favorites`.

Rules: cite the `source` and `confidence` of any value you quote;
say "not on record" for missing properties; never present the
38-material sample as a complete database; cost is a relative
1–5 index, not a price.


---

## Modelling (Stage 5) — structured tools for Muse

The model API is the tool surface for creating and editing real
3D models. It operates on actual model data (validated JSON),
never on descriptions.

- **Schema:** `GET /api/v1/model/schema` — kinds, params,
  units, boolean ops, component fields. Read this first.
- **Inspect:** `GET /api/v1/projects/{id}/model` — model +
  analytic volumes and masses per component.
- **Create geometry:** `POST /api/v1/projects/{id}/model/components`
  with a component object (see `docs/MODELLING.md` for the
  format). Dimensions are in mm.
- **Modify dimensions:** `PATCH .../components/{cid}` with new
  `params` (or position / rotation / material_id / parent_id).
- **Add components:** same POST endpoint with a library kind
  (`gear`, `shaft`, `bearing`, `bolt`, `nut`, `spring`,
  `piston`, `pipe`, `beam`, `motor`, `enclosure`).
- **Assign materials:** `PATCH .../components/{cid}` with
  `material_id` (a Stage 4 material id — look it up with the
  materials search first).
- **Assemble:** set `parent_id` on a component to make it a
  child of another (e.g. a gear on its shaft); set `position`
  and `rotation` (degrees) for placement.
- **Booleans:** add a component of type `boolean`, kind
  `boolean`, `params: {op: "subtract", operands: [idA, idB]}`.
- **Check before saving:** `POST .../model/validate` returns
  errors and volumes without writing anything.
- **Save:** `PUT /api/v1/projects/{id}/model` with the full
  model and `base_version` (the version you read). A 409 means
  the model changed — re-read it and re-apply your change.
- **Export:** `GET .../model/export?format=json`. STL/OBJ/GLB
  export happens in the browser workspace; tell the user to use
  Export there. Never claim STEP/3MF/FCStd export works.

Rules: only the agent owner's own projects (agent tokens are
owner-scoped); never invent a dimension or a volume — read the
schema and the validate response; say "not on record" for a
volume the API returns as null (booleans, imported meshes).


---

## Simulation (Stage 6) — structured tools for Muse

- **Discover solvers:** `GET /api/v1/solvers` — read the
  registry first; it says which solvers exist, what they
  need, and which are `not_implemented`.
- **Run an analytical solver:** `POST /api/v1/simulations`
  with `{project_id, solver, inputs}`. Inputs are SI units
  (metres, newtons, pascals). Sections are
  `{type: "rectangle"|"circle"|"ibeam"|"box", ...dims in m}`.
  `material_id` must be a Stage 4 material that has the
  solver's required properties on record — if the job comes
  back `failed`, read its `error` and tell the user which
  property is missing instead of guessing one.
- **Read results:** `GET /api/v1/simulations/{id}` — values
  carry `method: "analytical"` and the assumptions. Report
  the safety factor with its verdict (SF < 1 fails; 1–1.5
  marginal; ≥ 1.5 OK by the usual rule of thumb, not a code
  check). Never call an analytical result an FEA result.
- **Rigid-body runs:** create a `rigid_body` job (it stays
  `queued`), then run Rapier in the browser workspace and
  post `{summary, series}` to the job's `/results` endpoint.
- **Identify problems:** a safety factor below 1, a
  deflection larger than the design allows, or a rigid-body
  run that shows a collision or a fall — report the numbers
  and suggest the concrete change (bigger section, stronger
  material, shorter span, add a support). Never invent a
  solver result the API did not return.


---

## Mechanical engineering (Stage 7) — structured tools for Muse

- **Build a machine from a request:** break the machine into
  components from the Stage 5 + Stage 7 library (gear, shaft,
  bearing, crankshaft, connecting_rod, flywheel, clutch,
  brake_disc, coupling, pulley, sprocket, hydraulic_cylinder,
  valve, pump, spring, piston, motor, enclosure). Create the
  model with `POST /api/v1/projects/{id}/model/components`
  (one call per component) or `PUT /api/v1/projects/{id}/model`
  with a whole model; every component needs valid params
  (see `backend/model.py` — the validator is the contract).
  Parent gears to their shafts; keep positions in mm.
- **Run the calculations:** `POST /api/v1/simulations` with
  the mechanical solver and SI inputs. Read the job's results
  and assumptions. Check the safety factor (and the Goodman
  factor for fatigue) and report the verdict with the numbers.
  If a job comes back `failed`, the missing property is named
  in the error — tell the user which property is missing for
  that material instead of substituting one.
- **Crank-slider:** use the `crank_slider` solver for the
  full 720° series (position/velocity/acceleration every 10°)
  and the exact formulas; do not simulate the mechanism with
  Rapier and call it kinematics.
- **Material alternatives:** for a component, read its current
  material, then `POST /api/v1/materials/recommend` with
  `min_yield_mpa` = current yield and `max_density_kg_m3` =
  current density to find lighter options; report the mass
  each would give the component (volume x density) and check
  the alternative against fatigue, temperature and corrosion
  before recommending it.
- **Improvements:** propose a concrete change (bigger section,
  stronger material, different ratio, larger bearing), apply
  it to the model, and re-run the same solvers to show the
  before/after numbers. Never claim a design is safe to build:
  everything here is conceptual until a qualified engineer
  reviews it and a real FEA/CFD validation exists.


---

## Electrical engineering (Stage 8) — structured tools for Muse

- **Build a circuit from a request:** translate the request
  into components from the circuit schema
  (`GET /api/v1/circuits/schema`): resistor, capacitor,
  inductor, voltage/current source, diode, LED, NPN/PNP,
  NMOS/PMOS, op-amp, switch, relay, ground. Give every
  component an id and net names in `nodes` (`"0"` is
  ground), or terminal labels plus a `connections` list.
  Validate with `POST /api/v1/circuits/validate` before
  running.
- **Run a real simulation:** `POST /api/v1/circuits/simulate`
  with `analysis` `{type: "dc"}`, `{type: "transient",
  duration, steps}` or `{type: "ac", f_start, f_stop,
  points}`. Read the job's results: node voltages, branch
  currents, power per component, time series, or Bode
  magnitude/phase. Compare the result with the analytical
  solver for the same circuit (RC tau, RLC resonance) and
  say so when they agree — and when they do not.
- **Calculate first, simulate second:** for a quick answer
  use the analytical solvers through the job API
  (`ohm_law`, `rc_time_constant`, `rlc_resonance`,
  `ac_power`, `transformer`, `dc_motor`,
  `battery_config`, `solenoid`, `wire_resistance`).
  `wire_resistance` needs a material whose resistivity is
  on record — check the material first; a missing value is
  an error, never a guess.
- **Motor + gearbox:** use `motor_gearbox` to connect a DC
  motor to a gear pair: electrical input in, mechanical
  output out, with the combined efficiency. If the load
  exceeds the stall torque the solver refuses — report
  that, and propose a bigger motor or a different ratio.
- **Find circuit problems:** read the simulation's warnings
  (hazardous voltage above 50 V, a resistor above its
  rating), check node voltages against the design intent,
  and check power balance (the source's negative power
  should match the resistors' positive power). Suggest a
  concrete change (different value, added resistor, lower
  supply) and re-run to show the before/after numbers.
- **Never present a design as safe to build:** everything
  here is conceptual until a qualified engineer reviews it
  and real hardware is tested. Say that with every design.

## Structural engineering (Stage 9) — structured tools for Muse

- **Build a structure from a request:** translate the request
  into nodes, elements, supports and loads from the structure
  schema (`GET /api/v1/structures/schema`). Members are
  `beam` (frame, 12 DOF) or `truss` (axial only). Sections:
  rectangle, circle, ibeam, box — all dimensions in metres.
  Materials come from the Stage 4 database by id; check the
  material first, because a missing property is an error,
  never a guess. Validate with
  `POST /api/v1/structures/validate` before running.
- **Mind the torsion convention:** a straight beam line needs
  at least one support restraining torsion about the member
  axis (rx for a beam along X, ry for a vertical column) —
  the Pin preset does this. A model without it is refused as
  unstable, and that is the solver being correct, not a bug.
- **Run a real analysis:** `POST /api/v1/structures/analyze`
  with `analysis` `{type: "static"}`, `{type: "modal",
  n_modes}` or `{type: "buckling"}`. Read the job's results:
  reactions, displacements, per-member diagrams (11 stations),
  max stress, utilisation, buckling (Pcr, regime, utilisation),
  modal frequencies and shapes. Cross-check the DSM result
  against the analytical solvers for the same case (SS beam
  deflection, cantilever frequency, column Pcr) and say so
  when they agree — and when they do not.
- **Calculate first, analyse second:** for a quick answer use
  the analytical solvers through the job API
  (`column_buckling`, `fixed_beam`, `natural_frequency_beam`,
  `wind_load_is875`, `seismic_base_shear_is1893`,
  `load_combination`). The wind and seismic solvers are
  formula calculators with user-supplied factors — say that,
  and never present their output as a code check.
- **Save the structure:** `PUT /api/v1/projects/{id}/structure`
  with `base_version` from the last GET; a 409 means the
  structure changed elsewhere — reload and re-apply.
- **Never call a structure safe to build.** The solver is
  first-order, linear-elastic, preliminary only. No code
  compliance exists in this lab (IS 800 / IS 456 / AISC /
  Eurocodes not implemented), no connection or foundation
  design, no P-delta. Say so whenever a result is reported.
