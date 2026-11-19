"""AI Engineering Laboratory — modelling maths (Stage 5, backend).

Python mirror of assets/js/model-math.js: units, analytic volumes,
and model validation. Keep the two in sync — the rules are the
same on both sides so the API rejects exactly what the UI rejects.
Volumes are in mm^3. Analytic volumes are marked exact=False where
a closed-form value is not available; the browser computes exact
mesh volumes instead. Never invent a volume: unknown means None.
"""
import math

UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
PRIMITIVE_KINDS = ["box", "cylinder", "sphere", "cone", "torus",
                   "rounded_box", "chamfered_box", "extrude", "revolve"]
COMPONENT_KINDS = ["gear", "shaft", "bearing", "bolt", "nut",
                   "spring", "piston", "pipe", "beam", "motor", "enclosure"]
BOOLEAN_OPS = ["union", "subtract", "intersect"]

MODEL_SCHEMA = {
    "version": 5,
    "units": ["mm", "cm", "m", "in"],
    "component_types": ["primitive", "component", "boolean", "imported"],
    "primitive_kinds": PRIMITIVE_KINDS,
    "component_kinds": COMPONENT_KINDS,
    "boolean_ops": BOOLEAN_OPS,
    "component_fields": {
        "id": "string, unique, required",
        "name": "string, required",
        "type": "primitive | component | boolean | imported",
        "kind": "see primitive_kinds / component_kinds / 'boolean' / 'mesh'",
        "params": "dimensions in mm (see docs/MODELLING.md)",
        "position": "[x, y, z] in mm, default [0,0,0]",
        "rotation": "[rx, ry, rz] in degrees, default [0,0,0]",
        "scale": "[sx, sy, sz] positive, default [1,1,1]",
        "material_id": "Stage 4 material id or null",
        "color": "hex number or null",
        "visible": "boolean, default true",
        "parent_id": "component id or null",
        "tolerance_mm": "number >= 0, default 0.1",
        "constraints": "list of {type: align_origin|mate|lock, ...}",
    },
    "notes": [
        "All lengths are stored in mm in the model; the UI converts to cm/m/inches for display.",
        "A boolean component has params {op, operands: [idA, idB]} and produces a new solid; its operands are hidden in the viewport.",
        "Imported (mesh) components store geometry_data {positions: [...], index: [...]} in params.",
        "Analytic volumes are estimates for rounded_box, gear, bearing and piston; booleans and meshes return null here and are measured from the mesh in the browser.",
    ],
}


def to_mm(value, unit):
    try:
        return float(value) * UNITS[unit]
    except (KeyError, TypeError, ValueError):
        return float("nan")


def convert(value, from_unit, to_unit):
    return to_mm(value, from_unit) / UNITS[to_unit]


def polygon_area(points):
    area = 0.0
    for i, p in enumerate(points):
        q = points[(i + 1) % len(points)]
        area += p[0] * q[1] - q[0] * p[1]
    return abs(area) / 2


def polygon_centroid_x(points):
    cx = 0.0
    a = 0.0
    for i, p in enumerate(points):
        q = points[(i + 1) % len(points)]
        cross = p[0] * q[1] - q[0] * p[1]
        cx += (p[0] + q[0]) * cross
        a += cross
    return cx / (3 * a) if a else 0.0


def _num(p, key):
    v = p.get(key)
    return v if isinstance(v, (int, float)) and math.isfinite(v) else None


def analytic_volume(comp):
    """Return {'value': float|None, 'exact': bool, 'note': str}."""
    p = comp.get("params") or {}
    kind = comp.get("kind")
    if kind == "box":
        l, w, h = _num(p, "length"), _num(p, "width"), _num(p, "height")
        if None in (l, w, h):
            return {"value": None, "exact": False, "note": "missing dimension"}
        return {"value": l * w * h, "exact": True, "note": ""}
    if kind == "cylinder":
        r, h = _num(p, "radius"), _num(p, "height")
        if None in (r, h):
            return {"value": None, "exact": False, "note": "missing dimension"}
        return {"value": math.pi * r * r * h, "exact": True, "note": ""}
    if kind == "sphere":
        r = _num(p, "radius")
        if r is None:
            return {"value": None, "exact": False, "note": "missing dimension"}
        return {"value": 4 / 3 * math.pi * r ** 3, "exact": True, "note": ""}
    if kind == "cone":
        r, h = _num(p, "radius"), _num(p, "height")
        if None in (r, h):
            return {"value": None, "exact": False, "note": "missing dimension"}
        return {"value": math.pi * r * r * h / 3, "exact": True, "note": ""}
    if kind == "torus":
        R, r = _num(p, "radius"), _num(p, "tube")
        if None in (R, r):
            return {"value": None, "exact": False, "note": "missing dimension"}
        return {"value": 2 * math.pi ** 2 * R * r * r, "exact": True, "note": ""}
    if kind == "rounded_box":
        l, w, h = _num(p, "length"), _num(p, "width"), _num(p, "height")
        if None in (l, w, h):
            return {"value": None, "exact": False, "note": "missing dimension"}
        return {"value": l * w * h, "exact": False, "note": "estimate: rounded corners ignored"}
    if kind == "chamfered_box":
        l, w, h, ch = _num(p, "length"), _num(p, "width"), _num(p, "height"), _num(p, "chamfer")
        if None in (l, w, h, ch):
            return {"value": None, "exact": False, "note": "missing dimension"}
        return {"value": (l * w - 2 * ch * ch) * h, "exact": True, "note": "chamfer on the 4 vertical edges"}
    if kind == "extrude":
        prof = p.get("profile")
        if not isinstance(prof, list) or len(prof) < 3:
            return {"value": None, "exact": False, "note": "profile needs at least 3 points"}
        area = polygon_area(prof)
        for hole in p.get("holes") or []:
            area -= polygon_area(hole)
        depth = _num(p, "depth")
        if depth is None:
            return {"value": None, "exact": False, "note": "missing depth"}
        return {"value": area * depth, "exact": True, "note": ""}
    if kind == "revolve":
        prof = p.get("profile")
        if not isinstance(prof, list) or len(prof) < 2:
            return {"value": None, "exact": False, "note": "profile needs at least 2 points"}
        angle = _num(p, "angle")
        if angle is None:
            return {"value": None, "exact": False, "note": "missing angle"}
        return {"value": polygon_area(prof) * 2 * math.pi * abs(polygon_centroid_x(prof)) * angle / 360,
                "exact": True, "note": ""}
    if kind == "shaft":
        ds, ls = p.get("diameters"), p.get("lengths")
        if not isinstance(ds, list) or not isinstance(ls, list) or not ds or len(ds) != len(ls):
            return {"value": None, "exact": False, "note": "diameters and lengths must match"}
        v = 0.0
        for d, L in zip(ds, ls):
            if not isinstance(d, (int, float)) or not isinstance(L, (int, float)):
                return {"value": None, "exact": False, "note": "bad step"}
            v += math.pi * (d / 2) ** 2 * L
        return {"value": v, "exact": True, "note": ""}
    if kind == "pipe":
        Do, Di, L = _num(p, "outer_diameter"), _num(p, "inner_diameter"), _num(p, "length")
        if None in (Do, Di, L):
            return {"value": None, "exact": False, "note": "missing dimension"}
        return {"value": math.pi / 4 * (Do * Do - Di * Di) * L, "exact": True, "note": ""}
    if kind == "beam":
        L, H, fw, ft, wt = (_num(p, k) for k in ("length", "height", "flange_width", "flange_thickness", "web_thickness"))
        if None in (L, H, fw, ft, wt):
            return {"value": None, "exact": False, "note": "missing dimension"}
        return {"value": (2 * fw * ft + (H - 2 * ft) * wt) * L, "exact": True, "note": ""}
    if kind == "bolt":
        d, L, hh = _num(p, "diameter"), _num(p, "length"), _num(p, "head_height")
        if None in (d, L, hh):
            return {"value": None, "exact": False, "note": "missing dimension"}
        af = 1.8 * d
        return {"value": math.pi * (d / 2) ** 2 * L + math.sqrt(3) / 2 * af * af * hh, "exact": True, "note": ""}
    if kind == "nut":
        d, h = _num(p, "diameter"), _num(p, "height")
        if None in (d, h):
            return {"value": None, "exact": False, "note": "missing dimension"}
        af = 1.8 * d
        return {"value": math.sqrt(3) / 2 * af * af * h - math.pi * (d / 2) ** 2 * h, "exact": True, "note": ""}
    if kind == "spring":
        cd, wd, coils, L = _num(p, "coil_diameter"), _num(p, "wire_diameter"), _num(p, "coils"), _num(p, "length")
        if None in (cd, wd, coils, L):
            return {"value": None, "exact": False, "note": "missing dimension"}
        pitch = L / coils
        helix = coils * math.sqrt((math.pi * cd) ** 2 + pitch ** 2)
        return {"value": math.pi * (wd / 2) ** 2 * helix, "exact": True, "note": ""}
    if kind == "piston":
        d, h = _num(p, "diameter"), _num(p, "height")
        if None in (d, h):
            return {"value": None, "exact": False, "note": "missing dimension"}
        return {"value": math.pi * (d / 2) ** 2 * h, "exact": False, "note": "estimate: ring grooves ignored"}
    if kind == "motor":
        d, L, sd, sl = _num(p, "diameter"), _num(p, "length"), _num(p, "shaft_diameter"), _num(p, "shaft_length")
        if None in (d, L, sd, sl):
            return {"value": None, "exact": False, "note": "missing dimension"}
        return {"value": math.pi * (d / 2) ** 2 * L + math.pi * (sd / 2) ** 2 * sl, "exact": True, "note": ""}
    if kind == "enclosure":
        l, w, h, th = _num(p, "length"), _num(p, "width"), _num(p, "height"), _num(p, "wall_thickness")
        if None in (l, w, h, th):
            return {"value": None, "exact": False, "note": "missing dimension"}
        inner = max(0, l - 2 * th) * max(0, w - 2 * th) * max(0, h - th)
        return {"value": l * w * h - inner, "exact": True, "note": "open-top shell"}
    if kind == "gear":
        mod, teeth, tg, bore = _num(p, "module"), _num(p, "teeth"), _num(p, "thickness"), _num(p, "bore_diameter")
        if None in (mod, teeth, tg):
            return {"value": None, "exact": False, "note": "missing dimension"}
        outer_d = mod * teeth + 2 * mod
        v = math.pi * (outer_d / 2) ** 2 * tg * 0.9
        if bore is not None:
            v -= math.pi * (bore / 2) ** 2 * tg
        return {"value": v, "exact": False, "note": "estimate: teeth approximated as 90% of the outer cylinder"}
    if kind == "bearing":
        bo, bi, w = _num(p, "outer_diameter"), _num(p, "bore_diameter"), _num(p, "width")
        if None in (bo, bi, w):
            return {"value": None, "exact": False, "note": "missing dimension"}
        return {"value": math.pi / 4 * (bo * bo - bi * bi) * w, "exact": False, "note": "estimate: balls and races ignored"}
    if kind in ("boolean", "mesh"):
        return {"value": None, "exact": False,
                "note": "boolean/mesh volume needs the mesh — computed in the browser"}
    return {"value": None, "exact": False, "note": "unknown kind: " + str(kind)}


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _validate_params(comp, errors, where):
    p = comp.get("params") or {}
    kind = comp.get("kind")

    def pos(key):
        if not _is_num(p.get(key)) or p[key] <= 0:
            errors.append(f"{where}.params.{key} must be a positive number")

    def non_neg(key):
        if not _is_num(p.get(key)) or p[key] < 0:
            errors.append(f"{where}.params.{key} must be a number >= 0")

    if kind == "box":
        pos("length"); pos("width"); pos("height")
    elif kind == "cylinder":
        pos("radius"); pos("height")
    elif kind == "sphere":
        pos("radius")
    elif kind == "cone":
        pos("radius"); pos("height")
    elif kind == "torus":
        pos("radius"); pos("tube")
    elif kind == "rounded_box":
        pos("length"); pos("width"); pos("height"); pos("radius")
    elif kind == "chamfered_box":
        pos("length"); pos("width"); pos("height"); pos("chamfer")
    elif kind == "extrude":
        pos("depth")
        prof = p.get("profile")
        if not isinstance(prof, list) or len(prof) < 3:
            errors.append(f"{where}.params.profile needs at least 3 points")
        elif any(not isinstance(pt, list) or len(pt) != 2 or not all(_is_num(v) for v in pt) for pt in prof):
            errors.append(f"{where}.params.profile points must be [x, y] numbers")
        for i, hole in enumerate(p.get("holes") or []):
            if not isinstance(hole, list) or len(hole) < 3:
                errors.append(f"{where}.params.holes[{i}] needs at least 3 points")
    elif kind == "revolve":
        if not _is_num(p.get("angle")) or not (0 < p["angle"] <= 360):
            errors.append(f"{where}.params.angle must be > 0 and <= 360")
        prof = p.get("profile")
        if not isinstance(prof, list) or len(prof) < 2:
            errors.append(f"{where}.params.profile needs at least 2 points")
        elif any(not isinstance(pt, list) or len(pt) != 2 or not all(_is_num(v) for v in pt) or pt[0] < 0 for pt in prof):
            errors.append(f"{where}.params.profile points must be [x, y] numbers with x >= 0")
    elif kind == "gear":
        pos("module"); pos("thickness")
        teeth = p.get("teeth")
        if not isinstance(teeth, int) or teeth < 6:
            errors.append(f"{where}.params.teeth must be an integer >= 6")
        if "bore_diameter" in p:
            pos("bore_diameter")
    elif kind == "shaft":
        ds, ls = p.get("diameters"), p.get("lengths")
        if not isinstance(ds, list) or not isinstance(ls, list) or not ds or len(ds) != len(ls):
            errors.append(f"{where}.params.diameters and lengths must be non-empty arrays of equal length")
        else:
            if any(not _is_num(d) or d <= 0 for d in ds):
                errors.append(f"{where}.params.diameters must be positive")
            if any(not _is_num(v) or v <= 0 for v in ls):
                errors.append(f"{where}.params.lengths must be positive")
    elif kind == "bearing":
        pos("bore_diameter"); pos("outer_diameter"); pos("width")
    elif kind == "bolt":
        pos("diameter"); pos("length"); pos("head_height")
    elif kind == "nut":
        pos("diameter"); pos("height")
    elif kind == "spring":
        pos("coil_diameter"); pos("wire_diameter"); pos("length")
        if not _is_num(p.get("coils")) or p["coils"] < 1:
            errors.append(f"{where}.params.coils must be >= 1")
    elif kind == "piston":
        pos("diameter"); pos("height")
        if "ring_grooves" in p:
            non_neg("ring_grooves")
    elif kind == "pipe":
        pos("outer_diameter"); pos("inner_diameter"); pos("length")
        if _is_num(p.get("inner_diameter")) and _is_num(p.get("outer_diameter")) \
                and p["inner_diameter"] >= p["outer_diameter"]:
            errors.append(f"{where}.params.inner_diameter must be smaller than outer_diameter")
    elif kind == "beam":
        pos("length"); pos("height"); pos("flange_width"); pos("flange_thickness"); pos("web_thickness")
    elif kind == "motor":
        pos("diameter"); pos("length"); pos("shaft_diameter"); pos("shaft_length")
    elif kind == "enclosure":
        pos("length"); pos("width"); pos("height"); pos("wall_thickness")
    if kind == "rounded_box" and _is_num(p.get("radius")):
        min_dim = min(p.get("length") or 0, p.get("width") or 0, p.get("height") or 0)
        if p["radius"] * 2 > min_dim:
            errors.append(f"{where}.params.radius must be at most half the smallest dimension")
    if kind == "chamfered_box" and _is_num(p.get("chamfer")):
        min_dim = min(p.get("length") or 0, p.get("width") or 0)
        if p["chamfer"] * 2 > min_dim:
            errors.append(f"{where}.params.chamfer must be at most half the smallest side")


def validate_model(model, material_ids=None):
    """Return a list of error strings (empty = valid)."""
    if not isinstance(model, dict):
        return ["model must be an object"]
    errors = []
    if not isinstance(model.get("version"), (int, float)) or model.get("version", 0) < 1:
        errors.append("model.version must be a positive integer")
    if model.get("units") not in UNITS:
        errors.append("model.units must be one of: " + ", ".join(UNITS))
    comps = model.get("components")
    if not isinstance(comps, list):
        return errors + ["model.components must be an array"]
    ids, by_id = set(), {}
    for i, c in enumerate(comps):
        where = f"components[{i}]"
        if not isinstance(c, dict):
            errors.append(f"{where} must be an object")
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            errors.append(f"{where}.id is required")
            continue
        if cid in ids:
            errors.append(f"duplicate component id: {cid}")
        ids.add(cid)
        by_id[cid] = c
        if not isinstance(c.get("name"), str) or not c.get("name"):
            errors.append(f"{where}.name is required")
        if c.get("type") not in ("primitive", "component", "boolean", "imported"):
            errors.append(f"{where}.type is invalid: {c.get('type')}")
        if c.get("type") == "primitive" and c.get("kind") not in PRIMITIVE_KINDS:
            errors.append(f"{where}.kind is not a primitive: {c.get('kind')}")
        if c.get("type") == "component" and c.get("kind") not in COMPONENT_KINDS:
            errors.append(f"{where}.kind is not a library component: {c.get('kind')}")
        if c.get("type") == "boolean" and c.get("kind") != "boolean":
            errors.append(f"{where}.kind must be \"boolean\" for a boolean component")
        if c.get("type") == "imported" and c.get("kind") != "mesh":
            errors.append(f"{where}.kind must be \"mesh\" for an imported component")
        if not isinstance(c.get("params"), dict):
            errors.append(f"{where}.params is required")
        else:
            _validate_params(c, errors, where)
        mid = c.get("material_id")
        if mid is not None and material_ids is not None and mid not in material_ids:
            errors.append(f"{where}.material_id is not in the material database: {mid}")
        for key in ("position", "rotation"):
            v = c.get(key)
            if v is not None and (not isinstance(v, list) or len(v) != 3 or not all(_is_num(x) for x in v)):
                errors.append(f"{where}.{key} must be [x, y, z] numbers")
        sc = c.get("scale")
        if sc is not None and (not isinstance(sc, list) or len(sc) != 3 or not all(_is_num(x) and x > 0 for x in sc)):
            errors.append(f"{where}.scale must be three positive numbers")
        tol = c.get("tolerance_mm")
        if tol is not None and (not _is_num(tol) or tol < 0):
            errors.append(f"{where}.tolerance_mm must be >= 0")
        if c.get("parent_id") is not None and not isinstance(c.get("parent_id"), str):
            errors.append(f"{where}.parent_id must be a string or null")
    for c in comps:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        if c.get("type") == "boolean":
            ops = (c.get("params") or {}).get("operands")
            if not isinstance(ops, list) or len(ops) != 2:
                errors.append(f"{c['id']}: boolean needs exactly 2 operands")
            else:
                if c["params"].get("op") not in BOOLEAN_OPS:
                    errors.append(f"{c['id']}: boolean op must be union/subtract/intersect")
                for op in ops:
                    if op == c["id"]:
                        errors.append(f"{c['id']}: boolean cannot use itself as an operand")
                    elif op not in by_id:
                        errors.append(f"{c['id']}: boolean operand not found: {op}")
        parent = c.get("parent_id")
        if parent:
            if parent not in by_id:
                errors.append(f"{c['id']}: parent not found: {parent}")
            else:
                seen, cur = set(), c
                while cur and cur.get("parent_id"):
                    if cur["id"] in seen:
                        errors.append(f"parent cycle involving: {c['id']}")
                        break
                    seen.add(cur["id"])
                    cur = by_id.get(cur["parent_id"])
    return errors


def mass_kg(volume_mm3, density_kg_m3):
    if volume_mm3 is None or density_kg_m3 is None:
        return None
    return volume_mm3 / 1e9 * density_kg_m3
