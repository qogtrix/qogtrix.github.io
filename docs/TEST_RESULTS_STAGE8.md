# Stage 8 — Test Results

**Date:** 19 Nov 2026

## Backend: 71 / 71 passed (`backend/test_stage8.py`)

Real backend on a temporary database, real HTTP.

**MNA solver vs hand-computed references:** voltage divider
5.0 V (R1 25 mW, source −50 mW); RC step response 0 V at
t = 0, 3.16 V at one tau (1 ms), 4.97 V at five tau; RLC AC
peak 3.16 near 5033 Hz; half-wave rectifier peak 9.29 V,
mean 2.84 V, no negative output; BJT common-emitter
collector 7.63 V, base 0.63 V; op-amp non-inverting gain 11
→ 5.5 V; NMOS saturation Vd 3.0 V; PMOS saturation Vd 2.0 V;
switch closed 5 V / open ~0 V; editor-style wires (union-find)
resolve the divider to 5.0 V.

**Validation and safety:** no-ground circuit rejected;
duplicate id rejected; negative resistance rejected;
voltage-source loop refused (singular matrix); 100 V node
flagged hazardous; 10 W in a 0.25 W resistor flagged.

**Analytical solvers:** Ohm's law 12 V/4 Ω = 3 A, 36 W;
RC tau 1 ms, cutoff 159.15 Hz (agrees with the MNA transient
at one tau); RLC f0 5032.9 Hz, Q 3.162 (agrees with the MNA
AC peak); AC power 1150 VA / 1035 W / 501 var; transformer
230 → 12 V; DC motor stall 8 A/0.4 N·m, no-load 2292 rpm,
75% at 0.1 N·m, overload refused; motor+gearbox 844 rpm,
0.2 N·m, 70% overall; battery 4s2p 14.8 V, 5.2 Ah,
76.96 Wh, 2.6 h; solenoid L 0.314 mH, B 12.57 mT; wire
resistance copper 10 m/1.5 mm² = 0.115 Ω, 0.57 V drop;
mineral wool refused (no resistivity on record);
series/parallel resistor 50 Ω, capacitor 5 µF.

**Demo circuits:** all four circuit files validate and run
to their reference values; both parameter files run through
their solvers.

**API:** health stage 8; circuit schema; validate (valid and
invalid); DC/transient/AC jobs complete via the API with the
right values; bad circuit recorded failed; Bob cannot
simulate on Alice's project (404); dc_motor and
wire_resistance jobs complete via the API; wire_resistance
with mineral wool recorded failed; registry lists the
circuit and electrical solvers.

## Earlier suites re-run

Stage 2 **34/34**, Stage 3 **34/34**, Stage 4 **42/42**,
Stage 5 **56/56** (backend) + **29/29** (JS maths) +
**28/28** (headless kernel), Stage 6 **29/29** (backend) +
**9/9** (Rapier), Stage 7 **99/99** (backend) + **36/36**
(JS maths) + **22/22** (headless kernel). Health assertions
accept stage 8.

## Not tested

- Browser rendering of `electrical.html` (syntax checked with
  `node --check`; pages served locally return 200).
- ngspice / FEMM / Elmer: not installed — the honest result
  is our own MNA solver, which is what is tested.
