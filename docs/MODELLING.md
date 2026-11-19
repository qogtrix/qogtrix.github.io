# 3D Engineering Modelling Workspace (Stage 5)

## What this is

A real interactive 3D modelling environment at `workspace.html`:
parametric geometry, real CSG booleans, a component library,
assemblies, Stage 4 material assignment with mass, save/autosave
into user projects, and STL/OBJ/GLB/JSON export.

## The kernel — and its honest limits

The kernel is **mesh-based CSG** (`assets/js/model-kernel.js`,
three-bvh-csg 0.0.16, MIT), **not a B-rep CAD kernel** like
OpenCascade. That distinction decides what is and is not claimed:

| Capability | Status |
|---|---|
| Primitives (box, cylinder, sphere, cone, torus) | Real parametric geometry; dimensions editable, mesh rebuilt |
| Extrusion (custom 2D profiles, with holes) | Real (ExtrudeGeometry from the stored profile) |
| Revolve (profile around an axis) | Real for a full 360° revolve. A partial angle is stored in the model but the mesh is built as a full revolve — the UI says so |
| Boolean union / subtract / intersect | **Real CSG on triangle meshes** — verified by mesh volume: a subtract really removes the tool volume (test_stage5_kernel, 28/28) |
| Holes | Real boolean subtraction of a cylinder tool |
| Fillets | Rounded boxes only (box primitives, `rounded_box`) |
| Chamfers | Chamfered boxes only (`chamfered_box`, 4 vertical edges) |
| Arbitrary-edge fillets / chamfers | **Not supported** — not offered in the UI |
| Gears | Simplified trapezoidal tooth profile, **not a true involute** |
| Components (gear, shaft, bearing, bolt, nut, spring, piston, pipe, I-beam, motor, enclosure) | Real parametric geometry with editable dimensions |
| Import | STL, OBJ, GLB/GLTF (three.js loaders); imported meshes are stored as geometry data in the model |
| Export | STL, OBJ, GLB, JSON — real, via three.js exporters |
| STEP, 3MF, FCStd | **Not supported** by a mesh kernel — the UI refuses them with that explanation |
| React Three Fiber | Not adopted: the site is static with no build step. The same scene graph is exposed through the vanilla Three.js modeller |

Volumes are measured from the mesh (three-bvh-csg
`computeMeshVolume`, with a manual signed-tetrahedron fallback).
The API also reports analytic volumes for primitives and simple
components (exact for box/cylinder/sphere/cone/torus/extrude/
revolve/shaft/pipe/beam/bolt/nut/spring/motor/enclosure; estimates
for rounded_box, gear, bearing, piston; null for booleans and
imported meshes, which need the mesh).

## Model format

All dimensions are stored in **millimetres**; the UI converts to
cm / m / inches for display. A model is JSON:

```json
{
  "version": 5, "units": "mm",
  "components": [
    {"id": "gear-1", "name": "Spur gear 24T", "type": "component",
     "kind": "gear",
     "params": {"module": 2, "teeth": 24, "thickness": 12,
                "bore_diameter": 10, "pressure_angle": 20},
     "position": [0, 0, 0], "rotation": [0, 0, 0],
     "material_id": "steel-1045", "visible": true,
     "parent_id": null, "tolerance_mm": 0.1, "constraints": []}
  ]
}
```

- `type`: `primitive` | `component` | `boolean` | `imported`.
- `kind`: primitives `box, cylinder, sphere, cone, torus,
  rounded_box, chamfered_box, extrude, revolve`; components
  `gear, shaft, bearing, bolt, nut, spring, piston, pipe, beam,
  motor, enclosure`; booleans use kind `boolean` with
  `params: {op: union|subtract|intersect, operands: [idA, idB]}`;
  imported meshes use kind `mesh` with
  `params.geometry_data: {positions: [...], index: [...]}`.
- A boolean's operands are hidden in the viewport; the boolean
  component is the new solid.
- `parent_id` builds the assembly hierarchy (a gear can be a
  child of its shaft). Parent cycles are rejected by validation.
- `constraints` are stored (align_origin / mate / lock) — the
  modeller applies alignment and locking; full mechanical
  constraint solving is future work, not claimed.
- Validation rules (shared by `assets/js/model-math.js` and
  `backend/model.py`): unique ids, positive dimensions, gear
  teeth ≥ 6, shaft diameters/lengths matching, pipe inner <
  outer, revolve profile x ≥ 0, boolean operands exist, no
  parent cycles, material ids must exist in the Stage 4 database.

## Viewport

Orbit / zoom / pan (OrbitControls), move & rotate gizmos
(TransformControls), click-to-select with highlighting, grid +
axes, perspective/orthographic cameras, six view angles, fit
view, wireframe, section view (clipping plane with offset
slider), exploded view slider (parts offset from the model
centroid), and per-component visibility in the assembly tree.

## Materials

Each component can take a Stage 4 material. The inspector shows
the mesh volume and, when the material has a density, the mass
(volume × density). Material identity is stored in the model
(`material_id`) and survives save/reopen/duplicate/export.

## Saving — version-aware

The model lives in the project's payload (`payload.model`).
Saving sends `base_version`; if the server version moved on,
the API returns **409** and the UI offers reload or overwrite.
Autosave (2 s debounce, toggleable) does the same check.
Duplicate keeps the model; public/private visibility and
ownership rules from Stages 2–3 apply unchanged — another user
gets 404 on every model endpoint. Without a sign-in, the model
is kept in the browser only (guest mode, stated in the UI).

## AI modelling tools

`GET /api/v1/model/schema` (public) describes the whole model
format. Project-scoped, owner-only endpoints (session or agent
token): `GET/PUT /api/v1/projects/{id}/model`,
`POST /api/v1/projects/{id}/model/validate` (check + volumes
without saving), `POST /api/v1/projects/{id}/model/components`,
`PATCH/DELETE .../components/{id}`,
`GET /api/v1/projects/{id}/model/export?format=json`.
See `docs/MUSE_INTEGRATION.md` §Modelling and
`backend/api-spec.md`.

## Test models

`workspace/test-models/`: `shaft.json` (stepped shaft + bearing),
`gear.json` (spur gear 24T), `gearbox.json` (housing, 2 shafts,
2 gears parented to the shafts, 2 bolts),
`beam.json` (3 m I-beam + 2 end plates, ~72.5 kg),
`multi-component.json` (base plate, motor, shaft, gear, bearing,
pipe, bolt). Loadable from the workspace example menu.

## Dependencies

Three.js 0.160.0, three-bvh-csg 0.0.16, three-mesh-bvh 0.7.0 —
all MIT, all from jsDelivr CDN (see `docs/DEPENDENCIES.md`).
No paid APIs, no build step.
