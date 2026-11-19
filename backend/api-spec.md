# API Spec — Stage 1 (contract for Stage 2)

Base: `/api/v1` (not live in Stage 1; see `app.py` — only `/health` works).

## Health (real in Stage 1)

`GET /health` → `{"status":"ok","stage":1,"solver_available":false}`

## Simulations (Stage 2 — return 501 in Stage 1)

All simulation endpoints follow the same pattern:

- `POST /api/v1/simulate/{beam|circuit|frame|...}`
- Request: JSON with `project_id`, `inputs` (solver-specific, defined
  when the solver is chosen), `material_id` where relevant.
- Response while queued: `202 {"simulation_id": "...", "status": "queued"}`
- Poll: `GET /api/v1/simulations/{id}` →
  `{"id","status":"queued|running|completed|failed","solver",
  "solver_version","results": null | {...}}`
- **Rule:** `results` is `null` until a real solver writes it.
  No endpoint may return a hardcoded result.

## Materials / Components / Projects (Stage 2)

- `GET /api/v1/materials` — list, filter by `category`
- `GET /api/v1/materials/{id}`
- `GET /api/v1/components?lab=mechanical`
- `GET /api/v1/projects`, `POST /api/v1/projects`,
  `GET /api/v1/projects/{id}`, `DELETE /api/v1/projects/{id}`

In Stage 1 these are served from `data/*.json` in the browser and
from `localStorage` for projects — the API mirrors that shape so the
frontend can switch to the server in Stage 2 without changing its
data model.
