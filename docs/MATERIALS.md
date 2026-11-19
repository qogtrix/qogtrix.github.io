# Material Database — Data Quality, Sources & Architecture (Stage 4)

## What this is — and what it is not

The library holds **38 materials across 10 categories** (metals 12,
polymers 7, ceramics 4, composites 2, electrical 2, magnetic 2,
thermal-insulation 3, aerospace 2, construction 2, advanced 2).
That is a **working sample, not a complete universal material
database**. Do not describe it as complete. It grows by adding
entries to `data/materials.json` — no code changes, no rebuild of
the application.

## Data quality rules (enforced, not aspirational)

- **Typical published values only.** Every number is a typical
  room-temperature value from a standard or a manufacturer's
  datasheet, labelled `confidence: typical` (or `estimated` where
  the value is known to vary, e.g. tungsten strength).
- **Missing values are null.** A null property means "not available"
  — it is shown as "—" / "Not available" and never treated as zero
  in filters, sorting, comparison or recommendations. The API
  returns a `missing_properties` list per material, and the UI
  greys those rows out.
- **Experimental, estimated and verified values are distinguished**
  by the per-material `confidence` field (`verified` / `typical` /
  `estimated`), shown on every card and detail page.
- **Units are explicit everywhere.** Every property has a fixed
  unit (see `property_definitions` in `data/materials.json` and
  `PROPERTY_UNITS` in `backend/db.py`). Tests check unit ranges
  (density 1–25,000 kg/m³, Poisson 0–0.5, modulus 0.001–1,000 GPa,
  no negative values).
- **Cost is a relative index, not a price.** `cost_index` 1–5 is an
  indicative relative cost ("1 = cheapest"), with the note
  "verify with suppliers" on every material. No fake prices.
- **Corrosion resistance is a 1–5 rating with a note** explaining
  the rating in words (e.g. "needs coating or anodizing").

## Sources

Per material, the `source` field names the standard and the
reference (e.g. "ASTM B221; ASM Handbook typical values",
"EN 10025-2; ASM Handbook typical values", "Manufacturer
datasheets (typical values)"). The `standard` field holds the
grade's specification where one exists (ASTM/EN/AMS/ISO); where
no standard applies it is "—", never invented.

## Properties (16, all optional per material)

Density, tensile strength, compressive strength, yield strength,
elastic modulus, Poisson's ratio, shear modulus, hardness (value +
scale, e.g. 95 HB), thermal conductivity, specific heat capacity,
thermal expansion coefficient, melting point, electrical
resistivity, electrical conductivity (% IACS), fatigue limit,
fracture toughness — plus derived metrics computed from stored
data only: strength-to-weight (tensile × 1000 / density,
kN·m/kg) and specific stiffness (modulus × 1000 / density,
10⁶ m²/s²).

## Architecture

- **Content:** `data/materials.json` (v2 format: nested
  `properties`, per-material quality fields) and
  `data/material_categories.json` (10 categories).
- **Normalized storage:** `db/schema.sql` Stage 4 tables —
  `materials` (core facts), `material_properties` (one row per
  property: key, numeric value, text value, unit, confidence),
  `material_favorites` (per-user, private). The backend seeds
  these tables from `materials.json` on first run and never
  re-seeds (idempotent — verified by test).
- **API:** `GET /api/v1/materials` (search `q`, `category`,
  `min_tensile`, `max_density`, `min_melting`, `max_cost`,
  `min_corrosion`, `sort`), `GET /api/v1/materials/{id}`,
  `GET /api/v1/material-categories`, `GET /api/v1/materials/compare?ids=`,
  `POST /api/v1/materials/recommend`, favorites
  (`GET/POST/DELETE /api/v1/materials/favorites`, auth required),
  project selection (`POST/DELETE /api/v1/projects/{id}/materials`,
  owner only — the project stores only the material id in
  `payload.materials`).
- **Frontend:** `materials.html` + `assets/js/materials-library.js`
  (search, category chips, filters, sort, favorites, compare tray,
  recommender), `material.html` + `assets/js/material-detail.js`
  (grouped properties, data quality, select-for-project, related
  materials). Both work from the static JSON files on GitHub Pages
  with no backend; when the backend is running, favorites sync to
  the server and the same scoring formulas run there.
- **Adding a material:** append one entry to
  `data/materials.json` with the same fields, set unknown
  properties to `null`, and restart the backend (it seeds new
  entries) — no code change needed.

## AI retrieval (Muse integration preparation)

The structured retrieval system for Muse is the materials API
itself (see `docs/MUSE_INTEGRATION.md` §Materials):

- **Search:** `GET /api/v1/materials?q=&category=&min_tensile=...`
- **Compare:** `GET /api/v1/materials/compare?ids=a,b,c` — returns
  per-row best values, computed, never asserted.
- **Recommend:** `POST /api/v1/materials/recommend` — hard filters
  first, then a documented score (50% strength-to-weight + 30%
  specific stiffness + 20% low cost), with per-candidate reasons
  and trade-offs computed from stored data.
- **Select:** `POST /api/v1/projects/{id}/materials` with an
  agent token (owner-scoped, like all project writes).
- **Explain trade-offs:** every candidate carries `reasons` and
  `trade_offs` derived from its own data (e.g. "Expensive",
  "Needs corrosion protection", "No melting point on record").
