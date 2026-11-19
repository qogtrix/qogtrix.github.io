# Stage 4 — Test Results

**Date:** 19 Nov 2026
**How:** `cd backend && python3 test_stage4.py` — real backend on a
temporary SQLite database, real HTTP. Stage 2 and Stage 3 suites
re-run as well: 34/34 each, still passing. A separate live curl
check confirmed the full user flow (register → favorite → project
material selection → recommend) against the backend on port 8001.

## Result: 42 / 42 tests passed (Stage 4) + 34/34 (Stage 2) + 34/34 (Stage 3)

```
PASS  health endpoint (stage 4)
PASS  10 material categories
PASS  category counts sum to 38
PASS  material list returns 38
PASS  list carries the data-quality notice
PASS  search 'aluminium' finds 3 grades
PASS  search 'peek' finds PEEK
PASS  search with no match returns empty list
PASS  category filter polymers = 7
PASS  category filter ceramics = 4
PASS  min_tensile=500 keeps 7075/Ti/Inconel, drops PLA
PASS  max_density=2000 keeps PLA, drops steel
PASS  min_melting=1500 keeps steel/tungsten, drops aluminium
PASS  sort by strength-to-weight puts 7075 first among metals
PASS  detail: 6061 has source, standard and confidence
PASS  detail: 6061 strength-to-weight is 114.8 kN·m/kg
PASS  detail: 6061 missing list flags compressive strength (not zero)
PASS  missing-data: mineral wool has many nulls, all listed, none zero
PASS  unknown material id → 404
PASS  unit consistency + source attribution for all 38 materials
PASS  compare returns 19 rows for 3 materials
PASS  compare: titanium wins strength-to-weight (best=1)
PASS  compare: 6061 is lightest (density best=0)
PASS  compare: missing values are null, not zero
PASS  compare with 1 material → 400
PASS  compare with unknown id → 404
PASS  recommend: carbon fibre/epoxy ranks first for light + strong
PASS  recommend: excluded count is honest (35 of 38)
PASS  recommend: trade-offs listed from stored data
PASS  recommend: impossible requirements return empty, not fake data
PASS  Alice favorites 6061
PASS  favorite unknown material → 404
PASS  unauthenticated favorite → 401
PASS  Alice's favorites list 6061
PASS  Bob's favorites are empty (no leak from Alice)
PASS  favorite persists after logout + login
PASS  remove favorite works
PASS  select material for own project
PASS  Bob cannot add a material to Alice's project (404)
PASS  select unknown material → 404
PASS  material selection persists after logout + login
PASS  seed is idempotent: still 38 materials after re-init

42/42 tests passed
```

## Mapping to the spec §9 (Testing)

| Check | Evidence |
|---|---|
| Material search | 'aluminium' → 3, 'peek' → 1, no-match → empty |
| Property filtering | min_tensile / max_density / min_melting / category filters verified |
| Unit consistency | Density, Poisson, modulus ranges + no negatives + source/confidence for all 38 |
| Material comparisons | 19-row compare table; Ti best strength-to-weight (214.4), 6061 lightest; nulls stay null |
| Source attribution | Every material has source + standard + confidence; detail page shows them |
| Missing-data handling | 6061 compressive = null and listed; mineral wool ≥8 nulls, all listed, none zero |
| Database persistence | Favorites + project selection persist after logout/login; re-init keeps 38 materials |

## Not tested

- Hosted fullstack app's Stage 4 update (artifact edit, separate
  build — its own verification is reported with that build).
- Browser rendering of the new library/detail pages (JS syntax
  checked with node --check; pages served locally return 200).
  The hosted app's builder verifies its UI in its own sandbox.
