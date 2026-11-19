# Stage 6 — Test Results

**Date:** 19 Nov 2026

## Backend: 29 / 29 passed (`backend/test_stage6.py`)

Real backend on a temporary database, real HTTP. Analytical
solver references (cantilever 0.675 mm / 4.5 MPa, simply
supported 0.0422 mm, axial 10 MPa / 0.05 mm, torsion 63.66 MPa
/ 0.0828 rad, conduction 500 kW, lumped thermal τ 6411 s /
67.8 °C, drag 275.6 N / Re 2.03e6, free fall 1.428 s / 14.0 m/s
/ 98.1 J, I-beam I = 2.098e-5 m⁴), missing-property rejection,
FEA refusal, job create/list/get/delete, rigid-body
queue → results → completed, double-post rejection, Bob 404,
unknown solver 400, Stage 5 model API still working.

## Rapier benchmarks: 9 / 9 passed (`backend/test_stage6_rapier.mjs`)

Free fall (position, velocity, energy), collision bounce,
spring-mass period, rotation conservation, torque → angular
acceleration, static body. See `docs/VALIDATION_STAGE6.md`.

## Earlier suites re-run

Stage 2 **34/34**, Stage 3 **34/34**, Stage 4 **42/42**,
Stage 5 **56/56** (backend) + **29/29** (JS maths) +
**28/28** (headless kernel). Their health assertions were
relaxed to accept stage 6.

## Not tested

- Browser rendering of `simulate.html` (syntax checked with
  `node --check`; pages served locally return 200).
- FEA / CFD: no solver installed — the honest result is the
  `not_implemented` job status, which is tested.
