# Mechanical Engineering Laboratory (Stage 7)

## What Stage 7 adds

- **11 new parametric components** in the Stage 5 kernel:
  crankshaft, connecting rod, flywheel, clutch, brake disc,
  coupling, pulley, sprocket, hydraulic cylinder, valve, pump.
  They join the existing gear, shaft, bearing, bolt, nut, spring,
  piston, pipe, beam, motor and enclosure.
- **11 analytical mechanical solvers** in `backend/solvers.py`:
  gear_train, shaft_combined, bearing_load, belt_drive,
  spring_helical, flywheel, hydraulic_cylinder, crank_slider,
  fatigue_shaft, vibration_1dof, power_transmission.
- **Mechanical workspace** (`mechanical.html`): assembly preview
  with exploded view, component library, gear-train calculator,
  crank-slider animator, calculation panel, bill of materials
  (CSV + print), and material alternatives.
- **4 demo assemblies** in `workspace/test-models/mechanical/`:
  gear_transmission, crank_slider, rotating_shaft, hydraulic_lift.

## Component notes (what each one actually models)

- **Crankshaft** — single-throw: two main journals, two webs,
  one crank pin. A multi-throw crankshaft is not modelled.
- **Connecting rod** — big-end and small-end rings with a
  rectangular shank. Bore sizes are assumed (big 60%, small
  50% of the outer diameter) and stated in the volume note.
- **Flywheel** — annular disc with a hub ring. Mass and
  inertia in the flywheel solver use the same disc formula.
- **Clutch** — a stack of friction plates (alternating colours).
- **Brake disc** — ventilated look is not modelled; it is a
  solid disc with a hub and a caliper block.
- **Coupling** — two flanges with bolts. No flexible element.
- **Pulley** — lathe profile with a single V-groove.
- **Sprocket** — reuses the gear tooth shape with
  module = chain pitch / pi. Teeth are trapezoidal, not true
  involute, like the gear.
- **Hydraulic cylinder** — barrel (wall assumed 5 mm, stated),
  end caps, extended rod. Seals and ports are not modelled.
- **Valve** — body, bonnet, stem and handwheel. No internals.
- **Pump** — housing, impeller disc and vanes, inlet pipe.
  It is a shape, not a flow simulation.

All of them are simplified parametric representations. The
modeller's honest limits still apply: mesh kernel, not B-rep;
no STEP/3MF/FCStd; gear/sprocket teeth simplified.

## Calculations (all analytical, all labelled)

| Solver | Formula basis |
|---|---|
| gear_train | i = z2/z1; n2 = n1/i; T2 = T1·i·η; P = T·ω; Ft = 2T/d; Fr = Ft·tan(α) |
| shaft_combined | σ = 32M/πd³; τ = 16T/πd³; von Mises √(σ²+3τ²); φ = TL/GJ; deflection as a simply supported centre-loaded beam |
| bearing_load | Deep-groove factors (e = 0.22; X/Y per Fa/Fr); L10 = (C/P)³ |
| belt_drive | Open-belt length; wrap angle; capstan T1/T2 = e^(μβ) |
| spring_helical | k = Gd⁴/8D³n; Wahl factor; τ = Kw·8FD/πd³ |
| flywheel | I = ½m(Ro²+Ri²); E = ½Iω²; rim stress ≈ ρv² |
| hydraulic_cylinder | F = p·A (extend and retract areas); v = Q/A |
| crank_slider | x = r·cosθ + √(l²−r²sin²θ), with exact first and second derivatives |
| fatigue_shaft | Rotating shaft: bending fully reversed, torsion steady; modified Goodman; endurance limit taken as recorded, no surface/size factors |
| vibration_1dof | fn = √(k/m)/2π (undamped) |
| power_transmission | P = T·ω |

Material properties come from the Stage 4 database. A required
property that is null is an error naming the property — never a
substitution. Test references are hand-computed in
`backend/test_stage7.py`.

## Mechanisms

- **Crank-slider:** exact kinematics, animated on a 2D canvas
  in the workspace and computed for 0–720° by the backend
  solver (73 points, every 10°). Max velocity and acceleration
  are validated against the closed form.
- **Gear trains:** ratio and tooth forces from the model's own
  gears (module and teeth read from the components).
- **Joints:** the Stage 6 joint system (fixed / revolute /
  spring, in the simulation workspace) is reused — mechanical
  assemblies run on Rapier exactly like any other model. There
  is no separate constraint solver; gear meshing is a
  calculation, not a simulated contact.

## Optimization (prepared, not automated)

The workspace's **Material alternatives** panel ranks Stage 4
materials that are at least as strong and no denser than the
component's current material, using the same 50/30/20 scoring
as the Materials Library, and shows the mass each would give
the component. Weight reduction, strength, efficiency and cost
trade-offs are therefore real comparisons on recorded data —
not an optimizer that invents a design. Any alternative still
has to be checked against the component's own constraints
(fatigue, temperature, corrosion), which the panel does not
do for you.

## Documentation

- **Bill of materials:** component, kind, material, analytic
  volume (estimates flagged), mass. CSV download and print.
- **Calculation reports:** every solver result shows its
  method, engine, assumptions and a safety-factor verdict.
- **Simulation reports:** the Stage 6 job system stores every
  run with its inputs and results.

## Safety

Everything in this laboratory is a **conceptual design**.
Calculations are analytical formulas for idealised geometry;
the geometry is simplified; there is no FEA, no CFD, no
validation against a real machine. Never present an
unvalidated machine as safe for manufacturing or real-world
operation. The workspace and every report carry this notice.
