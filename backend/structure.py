"""AI Engineering Laboratory — structural solver (Stage 9).

Pure Python, stdlib only. A REAL structural analysis engine based
on the direct stiffness method (DSM):

- 3D truss elements (axial only) and 3D Euler-Bernoulli beam
  elements (axial + torsion + bending in both planes), 12 DOF.
- Supports (any combination of fixed/free translational and
  rotational DOFs), point loads, uniform distributed loads,
  self-weight, and thermal loads.
- Static analysis: nodal displacements, reactions, member end
  forces, stresses, shear/moment/axial diagrams, utilisation
  against the material's recorded strength.
- Member buckling: Euler critical load with an effective-length
  factor K, plus the Johnson parabola for intermediate columns.
- Modal analysis: consistent mass matrices + a generalised
  eigenvalue solve (Cholesky + cyclic Jacobi) for natural
  frequencies and mode shapes.

Units: the API works in SI (metres, newtons, pascals). The
browser UI converts from millimetres. Y is UP (matching the
Three.js workspace); gravity acts in -Y.

What this is NOT: it is not a full finite-element package.
There is no plate/shell/solid meshing, no nonlinear or
second-order (P-delta) analysis, no system (eigenvalue)
buckling, and no code-compliance checking against IS 800,
IS 456, AISC, ACI or the Eurocodes — those are listed as NOT
IMPLEMENTED in docs/STRUCTURAL.md. Results are linear-elastic
and must be reviewed by a qualified engineer before any
real-world use.
"""

import math

MAX_NODES = 100
MAX_ELEMENTS = 200
MAX_FREE_DOF = 600
MAX_MODAL_DOF = 120

STRUCTURE_SCHEMA = {
    "description": "Structural model: nodes, elements, supports, loads, combinations. SI units (m, N, Pa). Y is up.",
    "nodes": [{"id": "n1", "x_m": 0.0, "y_m": 0.0, "z_m": 0.0, "mass_kg": 0}],
    "elements": [{"id": "e1", "type": "beam", "n1": "n1", "n2": "n2",
                  "material_id": "steel-s355",
                  "section": {"type": "rectangle", "b_m": 0.1, "h_m": 0.2},
                  "k_factor": 1.0}],
    "supports": [{"node": "n1", "ux": True, "uy": True, "uz": True,
                  "rx": True, "ry": True, "rz": True}],
    "loads": [
        {"case": "dead", "type": "point", "node": "n2",
         "fx_N": 0, "fy_N": -10000, "fz_N": 0,
         "mx_Nm": 0, "my_Nm": 0, "mz_Nm": 0},
        {"case": "dead", "type": "distributed", "element": "e1",
         "wx_N_m": 0, "wy_N_m": -5000, "wz_N_m": 0,
         "coords": "global"},
        {"case": "dead", "type": "self_weight"},
        {"case": "thermal", "type": "thermal", "element": "e1",
         "dT_K": 30},
    ],
    "combinations": [{"name": "1.5(DL+LL)",
                      "factors": {"dead": 1.5, "live": 1.5}}],
    "element_types": ["beam", "truss"],
    "section_types": ["rectangle", "circle", "ibeam", "box"],
    "notes": [
        "Beam elements: Euler-Bernoulli, 12 DOF, axial + torsion + bending.",
        "Truss elements: axial only, pinned at both ends.",
        "k_factor is the effective-length factor for member buckling (default 1.0).",
        "Thermal loads use the material's recorded thermal expansion coefficient; a material without one is an error, never a guess.",
        "Simple supports restrain torsion about the member axis (rx): a beam on bearings cannot spin about its own axis. Rotational DOFs with no stiffness at all (e.g. rotations at truss joints) are held at zero and reported as inactive.",
        "Load combinations follow the IS 800:2007 / IS 456:2000 factor sets in the UI; only the arithmetic is computed here — this is not a code check.",
    ],
}

DOF_NAMES = ("ux", "uy", "uz", "rx", "ry", "rz")


# ------------------------------------------------------------------ sections

def section_properties_2d(section):
    """Return dict(area_m2, Iy_m4, Iz_m4, J_m4, cy_m, cz_m).

    Section dimensions are in metres. Local axes: x along the
    member, y is the section depth direction (h), z is the width
    direction (b). Iz is the second moment for bending in the
    x-y plane (about the z axis); Iy for bending in the x-z
    plane. J is the torsional constant: exact for circles,
    standard thin-wall / rectangular approximations otherwise
    (labelled approximate in the docs).
    """
    if not isinstance(section, dict):
        raise ValueError("section must be an object")
    t = section.get("type")
    if t == "rectangle":
        b = _pos(section, "b_m")
        h = _pos(section, "h_m")
        area = b * h
        Iy = h * b ** 3 / 12
        Iz = b * h ** 3 / 12
        # Torsional constant for a rectangle (Roark's formula,
        # h >= b; swap if needed).
        a, c = (h, b) if h >= b else (b, h)
        beta = 1 / 3 - 0.21 * (c / a) * (1 - (c / a) ** 4 / 12)
        J = beta * a * c ** 3
        return {"area_m2": area, "Iy_m4": Iy, "Iz_m4": Iz, "J_m4": J,
                "cy_m": h / 2, "cz_m": b / 2}
    if t == "circle":
        d = _pos(section, "d_m")
        I = math.pi * d ** 4 / 64
        return {"area_m2": math.pi * d ** 2 / 4, "Iy_m4": I, "Iz_m4": I,
                "J_m4": math.pi * d ** 4 / 32, "cy_m": d / 2, "cz_m": d / 2}
    if t == "ibeam":
        h = _pos(section, "height_m")
        bf = _pos(section, "flange_width_m")
        tf = _pos(section, "flange_thickness_m")
        tw = _pos(section, "web_thickness_m")
        if 2 * tf >= h or tw >= bf:
            raise ValueError("ibeam dimensions are inconsistent")
        area = 2 * bf * tf + (h - 2 * tf) * tw
        Iz = (bf * h ** 3 - (bf - tw) * (h - 2 * tf) ** 3) / 12
        Iy = (2 * tf * bf ** 3 + (h - 2 * tf) * tw ** 3) / 12
        # Open-section torsion: sum of rectangles, /3.
        J = (2 * bf * tf ** 3 + (h - 2 * tf) * tw ** 3) / 3
        return {"area_m2": area, "Iy_m4": Iy, "Iz_m4": Iz, "J_m4": J,
                "cy_m": h / 2, "cz_m": bf / 2}
    if t == "box":
        b = _pos(section, "b_m")
        h = _pos(section, "h_m")
        th = _pos(section, "t_m")
        if 2 * th >= min(b, h):
            raise ValueError("box wall thickness is too large")
        area = b * h - (b - 2 * th) * (h - 2 * th)
        Iz = (b * h ** 3 - (b - 2 * th) * (h - 2 * th) ** 3) / 12
        Iy = (h * b ** 3 - (h - 2 * th) * (b - 2 * th) ** 3) / 12
        # Bredt's formula for a thin-walled closed section.
        am = (b - th) * (h - th)
        J = 4 * am ** 2 * th / (2 * (b - th) + 2 * (h - th))
        return {"area_m2": area, "Iy_m4": Iy, "Iz_m4": Iz, "J_m4": J,
                "cy_m": h / 2, "cz_m": b / 2}
    raise ValueError(f"unknown section type: {t}")


def _pos(d, key):
    v = d.get(key)
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
        raise ValueError(f"section.{key} must be a positive number")
    return float(v)


# ------------------------------------------------------------------ validation

def validate_structure(structure, material_ids=None):
    """Return a list of validation errors (empty = valid)."""
    errors = []
    if not isinstance(structure, dict):
        return ["structure must be an object"]
    nodes = structure.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errors.append("nodes must be a non-empty list")
        nodes = []
    if len(nodes) > MAX_NODES:
        errors.append(f"at most {MAX_NODES} nodes are supported")
    node_ids = []
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            errors.append(f"nodes[{i}] must be an object")
            continue
        nid = n.get("id")
        if not isinstance(nid, str) or not nid:
            errors.append(f"nodes[{i}].id must be a non-empty string")
            continue
        if nid in node_ids:
            errors.append(f"duplicate node id: {nid}")
        node_ids.append(nid)
        for k in ("x_m", "y_m", "z_m"):
            if not isinstance(n.get(k), (int, float)) or isinstance(n.get(k), bool):
                errors.append(f"node {nid}.{k} must be a number")
        m = n.get("mass_kg", 0)
        if not isinstance(m, (int, float)) or isinstance(m, bool) or m < 0:
            errors.append(f"node {nid}.mass_kg must be a number >= 0")
    elements = structure.get("elements")
    if not isinstance(elements, list) or not elements:
        errors.append("elements must be a non-empty list")
        elements = []
    if len(elements) > MAX_ELEMENTS:
        errors.append(f"at most {MAX_ELEMENTS} elements are supported")
    el_ids = []
    used_nodes = set()
    for i, e in enumerate(elements):
        if not isinstance(e, dict):
            errors.append(f"elements[{i}] must be an object")
            continue
        eid = e.get("id")
        if not isinstance(eid, str) or not eid:
            errors.append(f"elements[{i}].id must be a non-empty string")
            continue
        if eid in el_ids:
            errors.append(f"duplicate element id: {eid}")
        el_ids.append(eid)
        if e.get("type") not in ("beam", "truss"):
            errors.append(f"element {eid}.type must be 'beam' or 'truss'")
        for end in ("n1", "n2"):
            if e.get(end) not in node_ids:
                errors.append(f"element {eid}.{end} must be an existing node id")
            else:
                used_nodes.add(e.get(end))
        if e.get("n1") == e.get("n2"):
            errors.append(f"element {eid} has zero length (n1 == n2)")
        mid = e.get("material_id")
        if not isinstance(mid, str) or not mid:
            errors.append(f"element {eid}.material_id is required")
        elif material_ids is not None and mid not in material_ids:
            errors.append(f"element {eid}.material_id '{mid}' is not a known material")
        try:
            section_properties_2d(e.get("section") or {})
        except ValueError as ex:
            errors.append(f"element {eid} section: {ex}")
        kf = e.get("k_factor", 1.0)
        if not isinstance(kf, (int, float)) or isinstance(kf, bool) or kf <= 0:
            errors.append(f"element {eid}.k_factor must be a positive number")
    for nid in node_ids:
        if nid not in used_nodes:
            errors.append(f"node {nid} is not used by any element")
    supports = structure.get("supports") or []
    if not isinstance(supports, list):
        errors.append("supports must be a list")
        supports = []
    supported = set()
    for i, s in enumerate(supports):
        if not isinstance(s, dict):
            errors.append(f"supports[{i}] must be an object")
            continue
        if s.get("node") not in node_ids:
            errors.append(f"supports[{i}].node must be an existing node id")
            continue
        supported.add(s.get("node"))
        if not any(s.get(d) for d in DOF_NAMES):
            errors.append(f"support at {s.get('node')} fixes nothing")
    if not supported:
        errors.append("at least one support is required")
    loads = structure.get("loads") or []
    if not isinstance(loads, list):
        errors.append("loads must be a list")
        loads = []
    for i, ld in enumerate(loads):
        if not isinstance(ld, dict):
            errors.append(f"loads[{i}] must be an object")
            continue
        lt = ld.get("type")
        if lt == "point":
            if ld.get("node") not in node_ids:
                errors.append(f"loads[{i}].node must be an existing node id")
            for k in ("fx_N", "fy_N", "fz_N", "mx_Nm", "my_Nm", "mz_Nm"):
                v = ld.get(k, 0)
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    errors.append(f"loads[{i}].{k} must be a number")
        elif lt == "distributed":
            if ld.get("element") not in el_ids:
                errors.append(f"loads[{i}].element must be an existing element id")
            for k in ("wx_N_m", "wy_N_m", "wz_N_m"):
                v = ld.get(k, 0)
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    errors.append(f"loads[{i}].{k} must be a number")
            if ld.get("coords", "global") not in ("global", "local"):
                errors.append(f"loads[{i}].coords must be 'global' or 'local'")
        elif lt == "self_weight":
            pass
        elif lt == "thermal":
            if ld.get("element") not in el_ids:
                errors.append(f"loads[{i}].element must be an existing element id")
            if not isinstance(ld.get("dT_K"), (int, float)) or isinstance(ld.get("dT_K"), bool):
                errors.append(f"loads[{i}].dT_K must be a number")
        else:
            errors.append(f"loads[{i}].type must be point, distributed, self_weight or thermal")
    for i, c in enumerate(structure.get("combinations") or []):
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or not c.get("name"):
            errors.append(f"combinations[{i}] needs a non-empty name")
        elif not isinstance(c.get("factors"), dict) or not c["factors"]:
            errors.append(f"combination {c.get('name')} needs a factors object")
    return errors


# ------------------------------------------------------------------ linear algebra

def _solve_linear(A, b):
    """Gaussian elimination with partial pivoting. A is a list of
    lists (n x n), b a list (n). Returns x. Raises ValueError if
    the matrix is singular."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            raise ValueError("singular matrix")
        if piv != col:
            M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        for r in range(col + 1, n):
            f = M[r][col] / pv
            if f == 0:
                continue
            for c in range(col, n + 1):
                M[r][c] -= f * M[col][c]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))
        x[i] = s / M[i][i]
    return x


def _mat_vec(A, v):
    return [sum(A[i][j] * v[j] for j in range(len(v))) for i in range(len(A))]


def _cholesky(A):
    """Lower Cholesky factor L of a symmetric positive-definite A."""
    n = len(A)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = A[i][j] - sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                if s <= 0:
                    raise ValueError("matrix is not positive definite")
                L[i][j] = math.sqrt(s)
            else:
                L[i][j] = s / L[j][j]
    return L


def _solve_lower(L, b):
    n = len(b)
    y = [0.0] * n
    for i in range(n):
        y[i] = (b[i] - sum(L[i][k] * y[k] for k in range(i))) / L[i][i]
    return y


def _solve_upper(U, b):
    n = len(b)
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (b[i] - sum(U[i][k] * x[k] for k in range(i + 1, n))) / U[i][i]
    return x


def _jacobi_eigen(A, tol=1e-10, max_sweeps=100):
    """Cyclic Jacobi eigenvalue decomposition of a symmetric
    matrix A. Returns (eigenvalues, eigenvectors as columns)."""
    n = len(A)
    a = [row[:] for row in A]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(max_sweeps):
        off = math.sqrt(sum(a[i][j] ** 2 for i in range(n)
                            for j in range(n) if i != j))
        if off < tol:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                if abs(a[p][q]) < 1e-14:
                    continue
                theta = 0.5 * math.atan2(2 * a[p][q], a[q][q] - a[p][p])
                c, s = math.cos(theta), math.sin(theta)
                for k in range(n):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p] = c * akp - s * akq
                    a[k][q] = s * akp + c * akq
                for k in range(n):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k] = c * apk - s * aqk
                    a[q][k] = s * apk + c * aqk
                for k in range(n):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p] = c * vkp - s * vkq
                    v[k][q] = s * vkp + c * vkq
    return [a[i][i] for i in range(n)], v


# ------------------------------------------------------------------ element maths

def _vec_sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _norm(a):
    return math.sqrt(sum(x * x for x in a))


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def _rotation(p1, p2):
    """3x3 rotation matrix whose rows are the local x, y, z axes.
    Local x is along the element; local y is the component of
    global +Y perpendicular to x (global +Z for vertical members)."""
    d = _vec_sub(p2, p1)
    L = _norm(d)
    x = [c / L for c in d]
    ref = [0.0, 1.0, 0.0] if abs(x[1]) < 0.999 else [0.0, 0.0, 1.0]
    y = [ref[i] - sum(ref[j] * x[j] for j in range(3)) * x[i] for i in range(3)]
    yn = _norm(y)
    y = [c / yn for c in y]
    z = _cross(x, y)
    return [x, y, z], L


def _expand_T(R, n_dof_per_node):
    """Block-diagonal transformation for 2 nodes."""
    n = 2 * n_dof_per_node
    T = [[0.0] * n for _ in range(n)]
    blocks = 2 if n_dof_per_node == 3 else 4
    for b in range(blocks):
        for i in range(3):
            for j in range(3):
                T[b * 3 + i][b * 3 + j] = R[i][j]
    return T


def _beam_local_k(E, G, A, Iy, Iz, J, L):
    k = [[0.0] * 12 for _ in range(12)]
    k[0][0] = k[6][6] = E * A / L
    k[0][6] = k[6][0] = -E * A / L
    k[3][3] = k[9][9] = G * J / L
    k[3][9] = k[9][3] = -G * J / L
    # Bending in the x-y plane (about z).
    k[1][1] = k[7][7] = 12 * E * Iz / L ** 3
    k[1][7] = k[7][1] = -12 * E * Iz / L ** 3
    k[1][5] = k[5][1] = 6 * E * Iz / L ** 2
    k[1][11] = k[11][1] = 6 * E * Iz / L ** 2
    k[7][5] = k[5][7] = -6 * E * Iz / L ** 2
    k[7][11] = k[11][7] = -6 * E * Iz / L ** 2
    k[5][5] = k[11][11] = 4 * E * Iz / L
    k[5][11] = k[11][5] = 2 * E * Iz / L
    # Bending in the x-z plane (about y).
    k[2][2] = k[8][8] = 12 * E * Iy / L ** 3
    k[2][8] = k[8][2] = -12 * E * Iy / L ** 3
    k[2][4] = k[4][2] = -6 * E * Iy / L ** 2
    k[2][10] = k[10][2] = -6 * E * Iy / L ** 2
    k[8][4] = k[4][8] = 6 * E * Iy / L ** 2
    k[8][10] = k[10][8] = 6 * E * Iy / L ** 2
    k[4][4] = k[10][10] = 4 * E * Iy / L
    k[4][10] = k[10][4] = 2 * E * Iy / L
    return k


def _beam_local_mass(rho, A, Iy, Iz, J, L):
    """Consistent mass matrix (Przemieniecki), 12x12 local."""
    m = rho * A * L
    k = [[0.0] * 12 for _ in range(12)]
    # Axial.
    k[0][0] = k[6][6] = m / 3
    k[0][6] = k[6][0] = m / 6
    # Torsion (polar mass per length = rho*J).
    mt = rho * J * L
    k[3][3] = k[9][9] = mt / 3
    k[3][9] = k[9][3] = mt / 6
    # Bending in x-y plane: DOFs (uy1, rz1, uy2, rz2) = (1,5,7,11).
    for idx, sgn in (((1, 5, 7, 11), 1), ((2, 4, 8, 10), -1)):
        a, b, c, d = idx
        k[a][a] = k[c][c] = 156 * m / 420
        k[a][c] = k[c][a] = 54 * m / 420
        k[a][b] = k[b][a] = sgn * 22 * m * L / 420
        k[a][d] = k[d][a] = sgn * -13 * m * L / 420
        k[c][b] = k[b][c] = sgn * 13 * m * L / 420
        k[c][d] = k[d][c] = sgn * -22 * m * L / 420
        k[b][b] = k[d][d] = 4 * m * L * L / 420
        k[b][d] = k[d][b] = -3 * m * L * L / 420
    return k


def _truss_local_k(E, A, L):
    ea = E * A / L
    return [[ea, 0, 0, -ea, 0, 0],
            [0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
            [-ea, 0, 0, ea, 0, 0],
            [0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0]]


def _truss_local_mass(rho, A, L):
    m = rho * A * L
    return [[m / 3, 0, 0, m / 6, 0, 0],
            [0, m / 3, 0, 0, m / 6, 0],
            [0, 0, m / 3, 0, 0, m / 6],
            [m / 6, 0, 0, m / 3, 0, 0],
            [0, m / 6, 0, 0, m / 3, 0],
            [0, 0, m / 6, 0, 0, m / 3]]


def _transform(K_local, T):
    """K_global = T^T K_local T."""
    n = len(K_local)
    tmp = [[sum(K_local[i][k] * T[k][j] for k in range(n)) for j in range(n)]
           for i in range(n)]
    return [[sum(T[k][i] * tmp[k][j] for k in range(n)) for j in range(n)]
            for i in range(n)]


def _transform_vec(v_local, T):
    """v_global = T^T v_local."""
    n = len(v_local)
    return [sum(T[k][i] * v_local[k] for k in range(n)) for i in range(n)]


def _local_vec(v_global, T):
    """v_local = T v_global."""
    n = len(v_global)
    return [sum(T[i][k] * v_global[k] for k in range(n)) for i in range(n)]


# ------------------------------------------------------------------ assembly

class _Model:
    def __init__(self, structure, props_fn):
        self.structure = structure
        self.nodes = {n["id"]: n for n in structure["nodes"]}
        self.node_index = {nid: i for i, nid in enumerate(self.nodes)}
        self.n_dof = 6 * len(self.nodes)
        self.elements = []
        for e in structure["elements"]:
            p1 = self.nodes[e["n1"]]
            p2 = self.nodes[e["n2"]]
            R, L = _rotation([p1["x_m"], p1["y_m"], p1["z_m"]],
                             [p2["x_m"], p2["y_m"], p2["z_m"]])
            if L <= 0:
                raise ValueError(f"element {e['id']} has zero length")
            props = props_fn(e["material_id"])
            E = _need_prop(props, "elastic_modulus_gpa", e["id"]) * 1e9
            rho = _need_prop(props, "density_kg_m3", e["id"])
            nu = props.get("poisson_ratio")
            G = E / (2 * (1 + nu)) if nu is not None else E / 2.6
            sec = section_properties_2d(e.get("section") or {})
            self.elements.append({
                "def": e, "R": R, "L": L, "E": E, "G": G, "rho": rho,
                "sec": sec,
                "alpha": (props.get("thermal_expansion_um_mk") or 0) * 1e-6
                if props.get("thermal_expansion_um_mk") is not None else None,
                "strength_Pa": _strength(props),
            })
        self.fixed = set()
        for s in structure.get("supports") or []:
            ni = self.node_index[s["node"]]
            for j, d in enumerate(DOF_NAMES):
                if s.get(d):
                    self.fixed.add(6 * ni + j)
        self.free = [i for i in range(self.n_dof) if i not in self.fixed]

    def assemble(self, want_mass=False):
        K = [[0.0] * self.n_dof for _ in range(self.n_dof)]
        M = [[0.0] * self.n_dof for _ in range(self.n_dof)] if want_mass else None
        for el in self.elements:
            e = el["def"]
            i1, i2 = self.node_index[e["n1"]], self.node_index[e["n2"]]
            dofs = [6 * i1 + j for j in range(6)] + [6 * i2 + j for j in range(6)]
            if e["type"] == "truss":
                kl = _truss_local_k(el["E"], el["sec"]["area_m2"], el["L"])
                T = _expand_T(el["R"], 3)
                kg6 = _transform(kl, T)
                # Expand the 6x6 translational matrix to 12x12
                # (rotational DOFs carry no stiffness for a truss).
                kg = [[0.0] * 12 for _ in range(12)]
                idx = [0, 1, 2, 6, 7, 8]
                for a in range(6):
                    for b in range(6):
                        kg[idx[a]][idx[b]] = kg6[a][b]
                if want_mass:
                    ml = _truss_local_mass(el["rho"], el["sec"]["area_m2"], el["L"])
                    mg6 = _transform(ml, T)
                    mg = [[0.0] * 12 for _ in range(12)]
                    for a in range(6):
                        for b in range(6):
                            mg[idx[a]][idx[b]] = mg6[a][b]
            else:
                kl = _beam_local_k(el["E"], el["G"], el["sec"]["area_m2"],
                                   el["sec"]["Iy_m4"], el["sec"]["Iz_m4"],
                                   el["sec"]["J_m4"], el["L"])
                T = _expand_T(el["R"], 6)
                kg = _transform(kl, T)
                if want_mass:
                    ml = _beam_local_mass(el["rho"], el["sec"]["area_m2"],
                                          el["sec"]["Iy_m4"], el["sec"]["Iz_m4"],
                                          el["sec"]["J_m4"], el["L"])
                    mg = _transform(ml, T)
            for a in range(12):
                for b in range(12):
                    K[dofs[a]][dofs[b]] += kg[a][b]
                    if want_mass:
                        M[dofs[a]][dofs[b]] += mg[a][b]
        # Lumped point masses on translational DOFs.
        if want_mass:
            for nid, n in self.nodes.items():
                m = n.get("mass_kg", 0) or 0
                if m:
                    ni = self.node_index[nid]
                    for j in range(3):
                        M[6 * ni + j][6 * ni + j] += m
        return K, M

    def load_vector(self, factors):
        """Assemble the global load vector for a case->factor map.
        Returns (F, fixed_end_global) where fixed_end_global is the
        equivalent nodal load vector (for element force recovery)."""
        F = [0.0] * self.n_dof
        fef = [0.0] * self.n_dof
        for ld in self.structure.get("loads") or []:
            case = ld.get("case", "dead")
            f = factors.get(case, 0.0)
            if f == 0:
                continue
            lt = ld["type"]
            if lt == "point":
                ni = self.node_index[ld["node"]]
                vals = [ld.get("fx_N", 0), ld.get("fy_N", 0), ld.get("fz_N", 0),
                        ld.get("mx_Nm", 0), ld.get("my_Nm", 0), ld.get("mz_Nm", 0)]
                for j in range(6):
                    F[6 * ni + j] += f * float(vals[j])
            elif lt == "distributed":
                el = next(x for x in self.elements if x["def"]["id"] == ld["element"])
                w_glob = [ld.get("wx_N_m", 0), ld.get("wy_N_m", 0), ld.get("wz_N_m", 0)]
                if ld.get("coords", "global") == "global":
                    R = el["R"]
                    w_loc = [sum(R[i][j] * w_glob[j] for j in range(3)) for i in range(3)]
                else:
                    w_loc = w_glob
                L = el["L"]
                if el["def"]["type"] == "truss":
                    # Truss elements carry axial load only; transverse
                    # distributed load is split to the end nodes.
                    # Consistent load vector (forces on the element):
                    # w*L/2 at each end.
                    w_ax = w_loc[0]
                    f_loc = [w_ax * L / 2, w_loc[1] * L / 2, w_loc[2] * L / 2,
                             0, 0, 0,
                             w_ax * L / 2, w_loc[1] * L / 2, w_loc[2] * L / 2,
                             0, 0, 0]
                else:
                    # Consistent load vector for a uniform load
                    # (Hermite shape functions): w*L/2 shear and
                    # +/-w*L^2/12 moments at the ends.
                    wx, wy, wz = w_loc
                    f_loc = [wx * L / 2, wy * L / 2, wz * L / 2, 0,
                             -wz * L ** 2 / 12, wy * L ** 2 / 12,
                             wx * L / 2, wy * L / 2, wz * L / 2, 0,
                             wz * L ** 2 / 12, -wy * L ** 2 / 12]
                T = _expand_T(el["R"], 6)
                f_glob = _transform_vec(f_loc, T)
                e = el["def"]
                i1, i2 = self.node_index[e["n1"]], self.node_index[e["n2"]]
                dofs = [6 * i1 + j for j in range(6)] + [6 * i2 + j for j in range(6)]
                for a in range(12):
                    F[dofs[a]] += f * f_glob[a]
                    fef[dofs[a]] += f * f_glob[a]
            elif lt == "self_weight":
                for el in self.elements:
                    rho, A = el["rho"], el["sec"]["area_m2"]
                    w_glob = [0.0, -rho * A * 9.81, 0.0]
                    R = el["R"]
                    w_loc = [sum(R[i][j] * w_glob[j] for j in range(3)) for i in range(3)]
                    L = el["L"]
                    wx, wy, wz = w_loc
                    if el["def"]["type"] == "truss":
                        f_loc = [wx * L / 2, wy * L / 2, wz * L / 2, 0, 0, 0,
                                 wx * L / 2, wy * L / 2, wz * L / 2, 0, 0, 0]
                    else:
                        f_loc = [wx * L / 2, wy * L / 2, wz * L / 2, 0,
                                 -wz * L ** 2 / 12, wy * L ** 2 / 12,
                                 wx * L / 2, wy * L / 2, wz * L / 2, 0,
                                 wz * L ** 2 / 12, -wy * L ** 2 / 12]
                    T = _expand_T(el["R"], 6)
                    f_glob = _transform_vec(f_loc, T)
                    e = el["def"]
                    i1, i2 = self.node_index[e["n1"]], self.node_index[e["n2"]]
                    dofs = [6 * i1 + j for j in range(6)] + [6 * i2 + j for j in range(6)]
                    for a in range(12):
                        F[dofs[a]] += f * f_glob[a]
                        fef[dofs[a]] += f * f_glob[a]
            elif lt == "thermal":
                el = next(x for x in self.elements if x["def"]["id"] == ld["element"])
                if el["alpha"] is None:
                    raise ValueError(
                        f"thermal load on element {ld['element']}: material "
                        f"{el['def']['material_id']} has no thermal expansion "
                        "coefficient on record — refusing to guess one")
                dT = float(ld["dT_K"])
                N = el["E"] * el["sec"]["area_m2"] * el["alpha"] * dT
                f_loc = [-N, 0, 0, 0, 0, 0, N, 0, 0, 0, 0, 0]
                T = _expand_T(el["R"], 6)
                f_glob = _transform_vec(f_loc, T)
                e = el["def"]
                i1, i2 = self.node_index[e["n1"]], self.node_index[e["n2"]]
                dofs = [6 * i1 + j for j in range(6)] + [6 * i2 + j for j in range(6)]
                for a in range(12):
                    F[dofs[a]] += f * f_glob[a]
                    fef[dofs[a]] += f * f_glob[a]
        return F, fef


def _need_prop(props, key, element_id):
    v = (props or {}).get(key)
    if v is None:
        raise ValueError(
            f"material property '{key}' is not on record for element "
            f"{element_id} — refusing to substitute a guessed value")
    return float(v)


def _strength(props):
    """Allowable strength in Pa: yield if recorded, else the
    tensile/compressive strength as a (tension, compression)
    pair. Returns (tension_Pa, compression_Pa) with None where
    the database has no value."""
    y = props.get("yield_strength_mpa")
    t = props.get("tensile_strength_mpa")
    c = props.get("compressive_strength_mpa")
    if y is not None:
        return (float(y) * 1e6, float(y) * 1e6)
    return ((float(t) * 1e6 if t is not None else None),
            (float(c) * 1e6 if c is not None else None))


# ------------------------------------------------------------------ analysis

def _active_free_dofs(model, K, F, M=None):
    """Free DOFs that actually have stiffness. A free DOF whose
    whole row of K is zero (e.g. a rotation at a truss joint —
    truss elements carry no moment) is inactive: it cannot move
    under load and does not affect any other DOF, so it is held
    at zero and reported, not solved for. A load applied to such
    a DOF is a real error (e.g. a moment on a truss joint)."""
    inactive = []
    notes = []
    for dof in model.free:
        row_zero = all(abs(K[dof][j]) < 1e-9 for j in range(model.n_dof))
        if row_zero:
            if abs(F[dof]) > 1e-9:
                ni, dj = dof // 6, dof % 6
                nid = model.structure["nodes"][ni]["id"]
                raise ValueError(
                    f"load applied to {DOF_NAMES[dj]} at node {nid}, "
                    "which has no stiffness (for example a moment at a "
                    "truss joint) — the structure cannot resist it")
            inactive.append(dof)
            ni, dj = dof // 6, dof % 6
            nid = model.structure["nodes"][ni]["id"]
            notes.append(f"{DOF_NAMES[dj]} at node {nid} has no "
                         "stiffness and is held at zero")
    active = [d for d in model.free if d not in set(inactive)]
    return active, inactive, notes


def _solve_static(model, factors):
    K, _ = model.assemble()
    F, fef = model.load_vector(factors)
    active, _inactive, notes = _active_free_dofs(model, K, F)
    if len(active) > MAX_FREE_DOF:
        raise ValueError(f"too many free degrees of freedom "
                         f"({len(active)} > {MAX_FREE_DOF})")
    Kf = [[K[i][j] for j in active] for i in active]
    Ff = [F[i] for i in active]
    try:
        uf = _solve_linear(Kf, Ff)
    except ValueError:
        raise ValueError("structure is unstable: the stiffness matrix "
                         "is singular — check supports and connectivity "
                         "(a mechanism or an unrestrained node; note "
                         "that a straight beam on simple supports also "
                         "needs its torsional rotation restrained — "
                         "see docs/STRUCTURAL.md)")
    u = [0.0] * model.n_dof
    for k, dof in enumerate(active):
        u[dof] = uf[k]
    # Reactions at fixed DOFs: R = K u - F.
    Ku = _mat_vec(K, u)
    reactions = {}
    for dof in sorted(model.fixed):
        reactions[dof] = Ku[dof] - F[dof]
    return u, reactions, fef, notes


def _element_results(model, u, fef, dist):
    """Per-element end forces (internal, sagging-positive), stresses,
    diagrams and buckling. f_loc is the force the nodes exert on
    the element (k*u - f_eq); internal diagrams follow from left-
    segment equilibrium:
      N(x)  = -f[0] - w_x*x            (tension positive)
      V_y(x)=  f[1] + w_y*x
      M_z(x)= -f[5] + f[1]*x + w_y*x^2/2   (sagging positive)
      M_y(x)= -f[4] - f[2]*x - w_z*x^2/2
    (verified against the simply supported and fixed-fixed beam
    benchmarks in test_stage9.py)."""
    out = []
    for el in model.elements:
        e = el["def"]
        i1, i2 = model.node_index[e["n1"]], model.node_index[e["n2"]]
        dofs = [6 * i1 + j for j in range(6)] + [6 * i2 + j for j in range(6)]
        u_glob = [u[d] for d in dofs]
        T = _expand_T(el["R"], 6)
        u_loc = _local_vec(u_glob, T)
        f_loc = [0.0] * 12
        if e["type"] == "truss":
            kl = _truss_local_k(el["E"], el["sec"]["area_m2"], el["L"])
            # Truss local DOFs are the 6 translations:
            # [n1 ux,uy,uz, n2 ux,uy,uz] = u_loc[0,1,2,6,7,8].
            idx = [0, 1, 2, 6, 7, 8]
            u6 = [u_loc[i] for i in idx]
            f6 = [sum(kl[i][j] * u6[j] for j in range(6)) for i in range(6)]
            fef_loc = _local_vec([fef[d] for d in dofs], T)
            fef6 = [fef_loc[i] for i in idx]
            for k, i in enumerate(idx):
                f_loc[i] = f6[k] - fef6[k]
        else:
            kl = _beam_local_k(el["E"], el["G"], el["sec"]["area_m2"],
                               el["sec"]["Iy_m4"], el["sec"]["Iz_m4"],
                               el["sec"]["J_m4"], el["L"])
            f12 = [sum(kl[i][j] * u_loc[j] for j in range(12)) for i in range(12)]
            fef_loc = _local_vec([fef[d] for d in dofs], T)
            f_loc = [f12[i] - fef_loc[i] for i in range(12)]
        w = dist[e["id"]]
        L = el["L"]
        stations = []
        for i in range(11):
            x = L * i / 10
            stations.append({
                "x_m": x,
                "axial_N": -f_loc[0] - w[0] * x,
                "shear_y_N": f_loc[1] + w[1] * x,
                "shear_z_N": f_loc[2] + w[2] * x,
                "moment_y_Nm": -f_loc[4] - f_loc[2] * x - w[2] * x ** 2 / 2,
                "moment_z_Nm": -f_loc[5] + f_loc[1] * x + w[1] * x ** 2 / 2,
                "torque_Nm": f_loc[3],
            })
        sec = el["sec"]
        A, cy, cz = sec["area_m2"], sec["cy_m"], sec["cz_m"]
        max_N = max(abs(s["axial_N"]) for s in stations)
        min_N = min(s["axial_N"] for s in stations)
        sig_axial = max_N / A
        sig_bend_y = max(abs(s["moment_y_Nm"]) for s in stations) * cz / sec["Iy_m4"]
        sig_bend_z = max(abs(s["moment_z_Nm"]) for s in stations) * cy / sec["Iz_m4"]
        sig_max = sig_axial + sig_bend_y + sig_bend_z
        tau = 0.0
        if sec["J_m4"]:
            r = max(cy, cz)
            tau = abs(f_loc[3]) * r / sec["J_m4"]
        von_mises = math.sqrt(sig_max ** 2 + 3 * tau ** 2) if tau else sig_max
        strength_t, strength_c = el["strength_Pa"]
        strength = strength_t if min_N >= 0 else strength_c
        utilization = (von_mises / strength) if strength else None
        # Buckling (compression members only).
        buckling = None
        if min_N < 0:
            Imin = min(sec["Iy_m4"], sec["Iz_m4"])
            rmin = math.sqrt(Imin / A)
            kf = float(e.get("k_factor", 1.0))
            Le = kf * L
            lam = Le / rmin if rmin > 0 else float("inf")
            Pcr = math.pi ** 2 * el["E"] * Imin / Le ** 2
            sig_cr_euler = Pcr / A
            if strength_c:
                lam_c = math.sqrt(2 * math.pi ** 2 * el["E"] / strength_c)
                if lam >= lam_c:
                    sig_cr = sig_cr_euler
                    regime = "euler"
                else:
                    sig_cr = strength_c * (1 - strength_c * lam ** 2
                                           / (4 * math.pi ** 2 * el["E"]))
                    regime = "johnson"
            else:
                sig_cr = sig_cr_euler
                regime = "euler"
            buckling = {
                "axial_force_N": min_N,
                "critical_load_N": Pcr,
                "critical_stress_Pa": sig_cr,
                "slenderness": lam,
                "effective_length_m": Le,
                "regime": regime,
                "utilization": abs(min_N) / Pcr if Pcr else None,
            }
        s0, s1 = stations[0], stations[-1]
        out.append({
            "id": e["id"], "type": e["type"],
            "material_id": e["material_id"],
            "length_m": L,
            "end_forces_local": {
                "n1": {"axial_N": s0["axial_N"], "shear_y_N": s0["shear_y_N"],
                       "shear_z_N": s0["shear_z_N"], "torque_Nm": s0["torque_Nm"],
                       "moment_y_Nm": s0["moment_y_Nm"],
                       "moment_z_Nm": s0["moment_z_Nm"]},
                "n2": {"axial_N": s1["axial_N"], "shear_y_N": s1["shear_y_N"],
                       "shear_z_N": s1["shear_z_N"], "torque_Nm": s1["torque_Nm"],
                       "moment_y_Nm": s1["moment_y_Nm"],
                       "moment_z_Nm": s1["moment_z_Nm"]},
            },
            "max_stress_Pa": sig_max,
            "von_mises_Pa": von_mises,
            "shear_stress_Pa": tau,
            "utilization": utilization,
            "strength_Pa": strength,
            "buckling": buckling,
            "diagrams": stations,
        })
    return out


def _diagram_loads(model, factors):
    """Per-element distributed load in local coords (N/m), summed
    over the active cases with their factors. Used for diagrams."""
    dist = {}
    for el in model.elements:
        dist[el["def"]["id"]] = [0.0, 0.0, 0.0]
    for ld in model.structure.get("loads") or []:
        f = factors.get(ld.get("case", "dead"), 0.0)
        if f == 0:
            continue
        if ld["type"] == "distributed":
            el = next(x for x in model.elements if x["def"]["id"] == ld["element"])
            w = [ld.get("wx_N_m", 0), ld.get("wy_N_m", 0), ld.get("wz_N_m", 0)]
            if ld.get("coords", "global") == "global":
                R = el["R"]
                w = [sum(R[i][j] * w[j] for j in range(3)) for i in range(3)]
            for j in range(3):
                dist[el["def"]["id"]][j] += f * float(w[j])
        elif ld["type"] == "self_weight":
            for el in model.elements:
                w = -el["rho"] * el["sec"]["area_m2"] * 9.81
                R = el["R"]
                w_loc = [sum(R[i][j] * [0.0, w, 0.0][j] for j in range(3))
                         for i in range(3)]
                for j in range(3):
                    dist[el["def"]["id"]][j] += f * w_loc[j]
    return dist


def analyze_static(structure, props_fn, combination=None, case=None):
    """Linear-elastic static analysis. Returns a results dict.
    combination: name of a load combination, or case: a single
    load case name. Defaults to all cases unfactored."""
    errors = validate_structure(structure)
    if errors:
        raise ValueError("invalid structure: " + "; ".join(errors))
    model = _Model(structure, props_fn)
    if combination:
        combo = next((c for c in structure.get("combinations") or []
                      if c["name"] == combination), None)
        if combo is None:
            raise ValueError(f"unknown combination: {combination}")
        factors = {k: float(v) for k, v in combo["factors"].items()}
    elif case:
        factors = {case: 1.0}
    else:
        factors = {}
        for ld in structure.get("loads") or []:
            factors[ld.get("case", "dead")] = 1.0
    u, reactions, fef, notes = _solve_static(model, factors)
    dist = _diagram_loads(model, factors)
    elem_results = _element_results(model, u, fef, dist)
    # Node results.
    node_results = {}
    max_disp = 0.0
    max_disp_node = None
    for nid, n in model.nodes.items():
        ni = model.node_index[nid]
        disp = [u[6 * ni + j] for j in range(6)]
        mag = math.sqrt(sum(d * d for d in disp[:3]))
        if mag > max_disp:
            max_disp, max_disp_node = mag, nid
        reac = [reactions.get(6 * ni + j, 0.0) if (6 * ni + j) in model.fixed else None
                for j in range(6)]
        node_results[nid] = {"displacement_m": disp[:3],
                             "rotation_rad": disp[3:],
                             "displacement_magnitude_m": mag,
                             "reaction": reac}
    max_util, max_util_el = None, None
    max_buck, max_buck_el = None, None
    for r in elem_results:
        if r["utilization"] is not None and (max_util is None or r["utilization"] > max_util):
            max_util, max_util_el = r["utilization"], r["id"]
        b = r["buckling"]
        if b and b["utilization"] is not None and (max_buck is None or b["utilization"] > max_buck):
            max_buck, max_buck_el = b["utilization"], r["id"]
    warnings = list(notes)
    if max_util is not None and max_util > 1:
        warnings.append(f"member {max_util_el} is overstressed "
                        f"(utilisation {max_util:.2f} > 1.0)")
    if max_buck is not None and max_buck > 1:
        warnings.append(f"member {max_buck_el} buckles under this load "
                        f"(buckling utilisation {max_buck:.2f} > 1.0)")
    if max_disp > 0:
        warnings.append(f"largest displacement {max_disp * 1000:.2f} mm "
                        f"at node {max_disp_node}")
    return {
        "analysis": "static",
        "combination": combination or case or "all cases (unfactored)",
        "factors": factors,
        "nodes": node_results,
        "elements": elem_results,
        "max_displacement_m": max_disp,
        "max_displacement_node": max_disp_node,
        "max_utilization": max_util,
        "max_utilization_element": max_util_el,
        "max_buckling_utilization": max_buck,
        "max_buckling_element": max_buck_el,
        "warnings": warnings,
        "assumptions": [
            "Linear elasticity, small deflections (Euler-Bernoulli beam theory)",
            "Loads are static; dynamic, wind and seismic effects are separate load cases, not time-history analysis",
            "Buckling is per-member Euler/Johnson, not system (eigenvalue) buckling",
            "Supports are idealised as fully fixed or fully free per DOF",
        ],
    }


def analyze_modal(structure, props_fn, n_modes=5):
    """Natural frequencies and mode shapes (generalised eigenvalue
    problem on the consistent mass matrix)."""
    errors = validate_structure(structure)
    if errors:
        raise ValueError("invalid structure: " + "; ".join(errors))
    model = _Model(structure, props_fn)
    K, M = model.assemble(want_mass=True)
    F0 = [0.0] * model.n_dof
    active, _inactive, _notes = _active_free_dofs(model, K, F0)
    free = active
    if len(free) > MAX_MODAL_DOF:
        raise ValueError(f"modal analysis supports at most "
                         f"{MAX_MODAL_DOF} free DOFs ({len(free)} here)")
    Kf = [[K[i][j] for j in free] for i in free]
    Mf = [[M[i][j] for j in free] for i in free]
    n = len(free)
    L = _cholesky(Mf)
    # A = L^-1 K L^-T : solve L Y = K, then A = Y L^-T.
    Y = [[0.0] * n for _ in range(n)]
    for col in range(n):
        rhs = [Kf[i][col] for i in range(n)]
        sol = _solve_lower(L, rhs)
        for i in range(n):
            Y[i][col] = sol[i]
    # L^-T via back substitution on identity columns.
    LinvT = [[0.0] * n for _ in range(n)]
    for col in range(n):
        e = [1.0 if i == col else 0.0 for i in range(n)]
        # Solve L^T x = e (L^T is upper triangular).
        sol = _solve_upper([[L[j][i] for j in range(n)] for i in range(n)], e)
        for i in range(n):
            LinvT[i][col] = sol[i]
    A = [[sum(Y[i][k] * LinvT[k][j] for k in range(n)) for j in range(n)]
         for i in range(n)]
    vals, vecs = _jacobi_eigen(A)
    order = sorted(range(n), key=lambda i: vals[i])
    modes = []
    for k in order[:max(1, min(int(n_modes), n))]:
        lam = vals[k]
        if lam <= 0:
            modes.append({"mode": len(modes) + 1, "frequency_hz": 0.0,
                          "angular_frequency_rad_s": 0.0,
                          "warning": "rigid-body mode (lambda <= 0) — check supports",
                          "shape": {}})
            continue
        omega = math.sqrt(lam)
        y = [vecs[i][k] for i in range(n)]
        # phi = L^-T y
        phi_free = _mat_vec(LinvT, y)
        mx = max(abs(v) for v in phi_free) or 1.0
        phi_free = [v / mx for v in phi_free]
        shape = {}
        for idx, dof in enumerate(free):
            ni = dof // 6
            nid = model.structure["nodes"][ni]["id"]
            shape.setdefault(nid, [0.0] * 6)[dof % 6] = phi_free[idx]
        modes.append({"mode": len(modes) + 1,
                      "frequency_hz": omega / (2 * math.pi),
                      "angular_frequency_rad_s": omega,
                      "period_s": 2 * math.pi / omega,
                      "shape": shape})
    return {
        "analysis": "modal",
        "modes": modes,
        "assumptions": [
            "Consistent mass matrices; lumped point masses added on translational DOFs",
            "Undamped free vibration; no damping ratio is computed",
            "Linear elasticity, small deflections",
        ],
    }
