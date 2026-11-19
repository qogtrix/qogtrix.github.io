# Stage 5 — Test Results

**Date:** 19 Nov 2026

## Backend: 56 / 56 passed (`backend/test_stage5.py`)

Real backend on a temporary database, real HTTP. Covers: health
(stage 5), model schema, analytic volumes (box 6000 mm³, cylinder
500π, sphere 4000π/3, extrude 500, revolve 1000π by Pappus,
boolean → null, 1 inch = 25.4 mm), validation rejections
(negative dimension, unknown kind, unknown material, boolean
with a missing operand, parent cycle), model save → version 1
with volume 6000 and mass from steel density, reopen, stale
base_version → 409, Bob → 404, unauthenticated → 401, invalid
save rejected and the stored model unchanged, validate endpoint
(no save), component add (gear) → v2, patch thickness 12→15 →
v3, invalid patch rejected, delete → v4, material assignment
persists after reopen with mass from the new density, duplicate
project keeps the model, JSON export, STEP export honestly
refused (400), all five test models valid with computable
volumes and saving via the API, gearbox parent hierarchy, beam
volume 9.24e6 mm³ / mass ~72.5 kg, Stage 4 materials API still
working (12 metals).

Earlier suites re-run: Stage 2 **34/34**, Stage 3 **34/34**,
Stage 4 **42/42** (their health assertions were relaxed to
accept stage 5).

## JS maths: 29 / 29 passed (`backend/test_stage5_math.js`)

Node test of `assets/js/model-math.js` — the same volume and
validation checks as the Python mirror, plus all five test
models validating in JS.

## Headless kernel: 28 / 28 passed (`backend/test_stage5_kernel.mjs`)

The real `model-kernel.js` run in Node with three 0.160.0 +
three-bvh-csg 0.0.16 installed. Verifies geometry is actually
built and booleans actually cut, by mesh volume:

- Box mesh volume exactly 6000 mm³; cylinder ~500π (48 segments);
  sphere ~4000π/3.
- **Boolean subtract:** box 50×30×20 minus a cylinder tool →
  28,433.7 mm³, matching 30,000 − π·25·20 within 0.02%.
- **Boolean union:** two overlapping 20 mm cubes → 12,000 mm³.
- **Boolean intersect:** → 4,000 mm³ (the overlap only).
- Gear mesh volume between the root and outer cylinders.
- I-beam mesh volume ~9.24e6 mm³ (within 1% of analytic).
- All 11 library components build with positive volume.
- Rounded box < plain box; chamfered box exactly
  (50·30 − 2·25)·20 = 29,000 mm³.
- Extrude 40×30×10 = 12,000; revolve = cylinder r20 h20.
- All five test models evaluate with no errors, positive volume.
- STL export returns bytes; OBJ export returns vertex/face text.
- GLB export is **skipped in Node** (GLTFExporter needs the
  browser's FileReader) and is verified in the hosted app instead.

Two test expectations were wrong during development and were
corrected after checking the maths (revolve 1000π, not 5000π;
subtract removes the cylinder through the 20 mm height, not
30 mm) — the kernel was right in both cases.

## Not tested

- Browser rendering of the modeller UI (JS syntax checked with
  `node --check`; pages served locally return 200). The hosted
  app's builder verifies its UI in its own sandbox.
- GLB export in a browser (Node lacks FileReader).
