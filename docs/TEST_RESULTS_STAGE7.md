# Stage 7 — Test Results

**Date:** 19 Nov 2026

## Backend: 99 / 99 passed (`backend/test_stage7.py`)

Real backend on a temporary database, real HTTP. Hand-computed
references: gear train (ratio 2, 750 rpm, 19 N·m, Ft 500 N,
Fr 182.0 N); shaft (von Mises 127.32 MPa, SF 2.435, twist
0.0821 rad, deflection 2.653 mm); bearing (P 5000 N, L10 900 M
rev, C 48276 N); belt (length 1.4762 m, wrap 2.9413 rad,
tensions 434.4/179.8 N); spring (k 4845 N/m, deflection
20.64 mm, shear 323.9 MPa, Wahl 1.1448); flywheel (mass
5.918 kg, I 0.02959 kg·m², energy 1460.3 J); hydraulic
(extend 19635 N, retract 14726 N, speeds 0.5093/0.6791 m/s);
crank-slider (stroke 50 mm, mean piston speed 5.0 m/s, max
velocity 8.02 m/s, max acceleration ~2981 m/s², 73 series
points, positions at 0°/180° exact); fatigue (Goodman SF
2.405, static SF 2.435); vibration (11.04 Hz, 662 rpm);
power (1570.8 W). Also: missing material properties refused
with named errors; rod shorter than crank refused; all 11
new kinds validate with positive volumes; 3 invalid kinds
rejected; all 4 demo models validate with positive volumes;
gear-train and crank-slider jobs complete via the API;
fatigue job with mineral-wool is recorded failed; demo model
saves and a flywheel adds via the model API; solver registry
lists the mechanical solvers.

Two wrong test expectations were corrected during development
after checking the maths (crank max velocity is 8.02 m/s, not
8.67 — the code was right; the model-API responses nest the
model under `model.version`, not `version`).

## JS maths: 36 / 36 passed (`backend/test_stage7_math.js`)

New kinds validate and have positive analytic volumes in the
browser maths; flywheel/sprocket/hydraulic volumes match their
closed forms; demo models validate in JS with the same volumes
as Python (bit-for-bit on the printed values).

## Headless kernel: 22 / 22 passed (`backend/test_stage7_kernel.mjs`)

All 11 new components build real geometry with positive mesh
volume; flywheel and clutch mesh volumes match their analytic
values within 2–3%; hydraulic cylinder in range; all 4 demo
models evaluate with no errors and positive mesh volume.

Two real bugs were found and fixed by this test: extruded
circles were faceted with the default 12 curve segments
(~2.5% volume error) — now `curveSegments: 48` — and clutch
plates were built at 90% thickness, losing 10% of the volume
— now full thickness.

## Earlier suites re-run

Stage 2 **34/34**, Stage 3 **34/34**, Stage 4 **42/42**,
Stage 5 **56/56** (backend) + **29/29** (JS maths) +
**28/28** (headless kernel), Stage 6 **29/29** (backend) +
**9/9** (Rapier). Their health assertions were relaxed to
accept stage 7.

## Not tested

- Browser rendering of `mechanical.html` (syntax checked with
  `node --check`; pages served locally return 200).
- FEA / CFD: no solver installed — the honest result is the
  `not_implemented` job status, which is tested.
