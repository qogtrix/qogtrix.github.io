# Electrical Engineering Laboratory (Stage 8)

## What Stage 8 adds

- **A real circuit simulator** (`backend/circuit.py`): Modified
  Nodal Analysis with Newton-Raphson for nonlinear devices,
  backward-Euler transient stepping, and small-signal AC sweeps.
  Pure Python stdlib — no new dependency.
- **11 analytical electrical solvers** in `backend/solvers.py`:
  ohm_law, series_parallel, rc_time_constant, rlc_resonance,
  ac_power, transformer, dc_motor, battery_config,
  motor_gearbox, solenoid, wire_resistance.
- **Electrical workspace** (`electrical.html`): a schematic
  editor (place, wire, drag, edit), DC / transient / AC runs
  with real charts, calculations, motors and batteries,
  bill of materials, and simulation jobs.
- **6 demo circuits** in `workspace/test-circuits/`: voltage
  divider, RC step response, RLC resonance, half-wave
  rectifier, DC motor parameters, 4s2p battery pack.

## The simulator (honest architecture)

ngspice, FEMM and Elmer FEM were checked on 19 Nov 2026 and
are **not installed** on this machine, so the lab does not
pretend to use them. Instead it implements the same algorithm
SPICE itself uses — Modified Nodal Analysis — from scratch:

- **DC operating point:** MNA + Newton-Raphson. Diodes use the
  Shockley equation, BJTs a simplified Ebers-Moll model,
  MOSFETs a Level-1 (Shichman-Hodges) model, op-amps an ideal
  voltage-controlled voltage source. Convergence is kept by
  SPICE-style junction-voltage limiting (a junction may move
  0.1 V forward per iteration) plus a gmin of 1e-12 S on every
  node so nodes with no DC path (e.g. behind a capacitor) do
  not make the matrix singular.
- **Transient:** backward Euler with companion models
  (capacitor = conductance C/dt + current source from the
  previous voltage; inductor = conductance dt/L + current
  source from the previous current). Capacitors start
  uncharged, inductors start with no current. Waveforms:
  dc, step, sine, pulse.
- **AC:** small-signal sweep, nonlinear devices linearised at
  the DC operating point, complex MNA per frequency.

Three real bugs were found and fixed while validating it
against hand-computed answers: inductors were wrongly kept as
voltage-source branches in AC/transient (singular matrix);
the diode's constant current was stamped with the wrong sign
(it drove the output above the supply and the iteration
limit-cycled); and a global step limit held source-driven
nodes back so the solver never reached the source voltage.

## What the models do and do not do

- **BJT:** simplified Ebers-Moll — active region only. No
  Early effect, no saturation limiting: a saturated BJT will
  over-predict its collector current.
- **MOSFET:** Level-1 only. No subthreshold conduction, no
  body diode, no breakdown.
- **Op-amp:** ideal VCVS. No supply rails, no saturation, no
  slew rate, no input offset.
- **Relay:** modelled as a switch. The coil is not modelled.
- **Switch:** 1 mΩ closed, 1 GΩ open.
- **LED:** a diode with typical LED saturation current and
  ideality factor; no light output model.
- Limits: 200 nodes, 5000 transient steps, 200 AC points,
  100 Newton iterations per operating point.

## Calculations (all analytical, all labelled)

| Solver | Formula basis |
|---|---|
| ohm_law | V = I·R; give exactly two, the third is solved |
| series_parallel | R and L add in series, reciprocate in parallel; C is the other way round |
| rc_time_constant | τ = RC; f = 1/2πRC; V(τ) = 63.2% of the step |
| rlc_resonance | f0 = 1/2π√(LC); Q = (1/R)√(L/C) |
| ac_power | S = VI; P = S·cos φ; Q = S·sin φ |
| transformer | V2/V1 = N2/N1; currents from power and efficiency |
| dc_motor | I = T/Kt; ω = (V − I·Ra)/Ke; η = Pout/Pin |
| battery_config | Series adds voltage, parallel adds capacity; Wh = V·Ah |
| motor_gearbox | Motor equations with the load torque reflected through the gear ratio and efficiency |
| solenoid | L = μ0μrN²A/l; B = μ0μrNI/l (long solenoid) |
| wire_resistance | R = ρL/A using the material's recorded resistivity |

The analytical RC and RLC results agree with the MNA solver:
τ = 1 ms gives V(1 ms) = 3.16 V in both, and Q = 3.16 gives
an AC peak of 3.2 V in both.

## Motors, batteries, power

- **DC motor:** stall current/torque, no-load speed,
  operating current/speed/power/efficiency at a given load.
  An overload (load above stall torque) is refused, not
  faked.
- **Motor + gearbox:** the Stage 7 integration — the motor
  equations with the load reflected through the gear ratio
  and efficiency, so electrical input and mechanical output
  are one calculation.
- **Battery:** series/parallel pack voltage, capacity,
  energy and runtime at a load current. Identical cells,
  no Peukert effect.
- **Transformer:** ideal, with an efficiency applied to
  power transfer.
- **Power systems beyond this:** distribution networks,
  transmission lines, switchgear and protection are
  architecture notes, not built. Solar and storage
  integration is the battery solver plus the same
  calculations.

## Electromagnetics

FEMM and Elmer are not installed, so there is no field
solver. What exists is the analytical solenoid solver
(inductance, field, flux, stored energy) and the magnetic
material data already in the Stage 4 database (resistivity
for conductors; no permeability is recorded, so μr is a
user input, never a guessed value). A real field solver is
a future stage, recorded as not built.

## Electrical materials

`wire_resistance` reads the material's recorded
electrical resistivity from the Stage 4 database — copper
1.72e-8 Ω·m, silver 1.59e-8 Ω·m, and so on. A material
with no resistivity on record (e.g. mineral wool) is an
error naming the property, never a substitution.

## Safety

Results flag hazardous voltages (any node above 50 V) and
components dissipating more than their rating. The
workspace and every report carry the notice: conceptual
designs only, never validated for a real electrical
installation.

## Documentation

- **Circuit diagrams:** the schematic editor itself, plus
  save/load as JSON (a netlist the solver runs).
- **Component lists:** bill of materials with CSV download.
- **Calculation reports:** every solver result shows its
  method, engine and assumptions.
- **Simulation reports:** every run is stored as a job with
  its inputs and results.
- **Wiring documentation:** the wire list in the designer
  shows every connection as component:terminal pairs.
