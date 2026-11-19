"""AI Engineering Laboratory — analytical solvers (Stage 6).

Pure Python, stdlib only. These are ANALYTICAL engineering
calculations (closed-form beam theory, 1-D conduction, etc.),
not finite-element or CFD results. Every result carries
"method": "analytical" and its assumptions, so the UI can label
it correctly and never present it as validated FEA.

Units: the API works in SI (metres, newtons, pascals, watts,
kelvin). The browser UI converts from the model's millimetres.

Material properties come from the Stage 4 database. A missing
required property is an ERROR naming the property — never a
silent substitution or a guessed value.
"""
import math

# ---------------------------------------------------------------- solvers
SOLVER_REGISTRY = {
    "cantilever_beam": {
        "label": "Cantilever beam (point load at free end)",
        "method": "analytical",
        "engine": "python-analytical (Euler-Bernoulli beam theory)",
        "status": "available",
        "inputs": ["length_m", "load_N", "section", "material_id"],
        "outputs": ["deflection_m", "slope_rad", "max_stress_Pa",
                    "safety_factor", "bending_moment_Nm"],
        "requires": ["elastic_modulus_gpa", "yield_strength_mpa"],
        "assumptions": [
            "Euler-Bernoulli beam theory (small deflections, linear elasticity)",
            "Point load at the free end; self-weight ignored",
            "Material is homogeneous and isotropic",
        ],
    },
    "simply_supported_beam": {
        "label": "Simply supported beam (centre point load)",
        "method": "analytical",
        "engine": "python-analytical (Euler-Bernoulli beam theory)",
        "status": "available",
        "inputs": ["length_m", "load_N", "section", "material_id"],
        "outputs": ["deflection_m", "max_stress_Pa", "safety_factor",
                    "bending_moment_Nm"],
        "requires": ["elastic_modulus_gpa", "yield_strength_mpa"],
        "assumptions": [
            "Euler-Bernoulli beam theory (small deflections, linear elasticity)",
            "Point load at mid-span; self-weight ignored",
        ],
    },
    "axial_bar": {
        "label": "Axial bar (tension / compression)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["length_m", "force_N", "section", "material_id"],
        "outputs": ["stress_Pa", "strain", "elongation_m", "safety_factor"],
        "requires": ["elastic_modulus_gpa", "yield_strength_mpa"],
        "assumptions": ["Uniform axial stress; linear elasticity"],
    },
    "torsion_shaft": {
        "label": "Torsion of a circular shaft",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["length_m", "torque_Nm", "diameter_m", "material_id"],
        "outputs": ["shear_stress_Pa", "angle_rad", "safety_factor"],
        "requires": ["elastic_modulus_gpa", "poisson_ratio",
                     "yield_strength_mpa"],
        "assumptions": [
            "Circular cross-section; linear elasticity",
            "Shear modulus G = E / (2(1+nu))",
            "Yield in shear estimated as yield / sqrt(3) (von Mises)",
        ],
    },
    "thermal_conduction": {
        "label": "Steady 1-D heat conduction through a slab",
        "method": "analytical",
        "engine": "python-analytical (Fourier's law)",
        "status": "available",
        "inputs": ["thickness_m", "area_m2", "t_hot_C", "t_cold_C",
                   "material_id"],
        "outputs": ["heat_flow_W", "thermal_resistance_K_W",
                    "temperature_profile_C"],
        "requires": ["thermal_conductivity_w_mk"],
        "assumptions": [
            "Steady state, one-dimensional conduction, constant k",
            "No heat generation inside the slab",
        ],
    },
    "lumped_thermal": {
        "label": "Lumped-capacitance cooling / heating",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["volume_m3", "area_m2", "h_W_m2K", "t0_C", "t_inf_C",
                   "duration_s", "material_id"],
        "outputs": ["time_constant_s", "temperature_series_C"],
        "requires": ["density_kg_m3", "specific_heat_j_kgk"],
        "assumptions": [
            "Uniform body temperature (Biot number assumed small — "
            "check it for your geometry before trusting the result)",
            "Constant heat-transfer coefficient h",
        ],
    },
    "drag": {
        "label": "Drag and lift (steady flow)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["velocity_m_s", "area_m2", "cd", "cl", "fluid"],
        "outputs": ["drag_N", "lift_N", "reynolds", "dynamic_pressure_Pa"],
        "requires": [],
        "assumptions": [
            "Steady, incompressible flow",
            "Cd / Cl are supplied by the user (not computed here)",
            "Fluid: air (rho 1.225 kg/m3, mu 1.81e-5) or water "
            "(rho 1000, mu 1.0e-3) at ~20 C",
        ],
    },
    "free_fall": {
        "label": "Free fall (analytical kinematics)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["height_m", "mass_kg", "g_m_s2"],
        "outputs": ["fall_time_s", "impact_velocity_m_s",
                    "impact_kinetic_energy_J"],
        "requires": [],
        "assumptions": ["No air resistance; constant gravity"],
    },
    "rigid_body": {
        "label": "Rigid-body dynamics (Rapier, in the browser)",
        "method": "numerical",
        "engine": "Rapier 0.14.0 (WASM, in-browser)",
        "status": "browser",
        "inputs": ["project_id", "gravity_m_s2", "duration_s",
                   "bodies", "forces", "springs", "joints"],
        "outputs": ["time_series", "final_state", "contacts"],
        "requires": [],
        "assumptions": [
            "Rigid bodies only; collision shapes are bounding boxes "
            "(or ball/cylinder for sphere/cylinder parts)",
            "Fixed timestep 1/60 s; validated against analytical "
            "benchmarks in docs/VALIDATION_STAGE6.md",
        ],
    },
    "fea": {
        "label": "Finite element analysis (CalculiX / Code_Aster)",
        "method": "numerical",
        "engine": "not installed",
        "status": "not_implemented",
        "inputs": [],
        "outputs": [],
        "requires": [],
        "assumptions": [
            "No FEA solver is installed in this environment "
            "(checked 19 Nov 2026: ccx, Code_Aster, OpenFOAM all absent). "
            "The job system accepts FEA jobs and records them as "
            "not_implemented instead of faking results.",
        ],
    },
    "cfd": {
        "label": "Computational fluid dynamics (OpenFOAM)",
        "method": "numerical",
        "engine": "not installed",
        "status": "not_implemented",
        "inputs": [],
        "outputs": [],
        "requires": [],
        "assumptions": [
            "No CFD solver is installed in this environment "
            "(checked 19 Nov 2026). Analytical drag/lift is the "
            "available substitute, labelled as such.",
        ],
    },
}

FLUIDS = {
    "air": {"rho": 1.225, "mu": 1.81e-5, "label": "Air at ~20 C"},
    "water": {"rho": 1000.0, "mu": 1.0e-3, "label": "Water at ~20 C"},
}


def section_properties(section):
    """Return (area_m2, I_m4, J_m4, c_m) for a cross-section dict.
    Section dimensions are in metres."""
    if not isinstance(section, dict):
        raise ValueError("section must be an object")
    t = section.get("type")
    if t == "rectangle":
        b, h = section["b_m"], section["h_m"]
        return b * h, b * h ** 3 / 12, None, h / 2
    if t == "circle":
        d = section["d_m"]
        return (math.pi * d ** 2 / 4, math.pi * d ** 4 / 64,
                math.pi * d ** 4 / 32, d / 2)
    if t == "ibeam":
        h = section["height_m"]
        bf, tf, tw = (section["flange_width_m"],
                      section["flange_thickness_m"], section["web_thickness_m"])
        area = 2 * bf * tf + (h - 2 * tf) * tw
        I = (bf * h ** 3 - (bf - tw) * (h - 2 * tf) ** 3) / 12
        return area, I, None, h / 2
    if t == "box":
        b, h, th = section["b_m"], section["h_m"], section["t_m"]
        area = b * h - (b - 2 * th) * (h - 2 * th)
        I = (b * h ** 3 - (b - 2 * th) * (h - 2 * th) ** 3) / 12
        return area, I, None, h / 2
    raise ValueError(f"unknown section type: {t}")


def _need_number(inputs, key, positive=True):
    v = inputs.get(key)
    if not isinstance(v, (int, float)) or isinstance(v, bool) \
            or (positive and v <= 0) or (not positive and v < 0):
        raise ValueError(f"{key} must be a {'positive ' if positive else ''}number")
    return float(v)


def _safety_factor(yield_pa, stress_pa):
    if stress_pa == 0:
        return None
    return yield_pa / abs(stress_pa)


def run_solver(solver, inputs, material_props):
    """Run an analytical solver. material_props maps property key ->
    value (or None when the database has no value).
    Returns a results dict. Raises ValueError on bad input or a
    missing required material property — never substitutes one."""
    if solver not in SOLVER_REGISTRY:
        raise ValueError(f"unknown solver: {solver}")
    meta = SOLVER_REGISTRY[solver]
    if meta["status"] == "not_implemented":
        raise ValueError(f"{solver} is not implemented: no solver "
                         "installed in this environment")
    if meta["status"] == "browser":
        raise ValueError("rigid_body runs in the browser workspace, "
                         "not on the backend")
    # Material requirements.
    props = {}
    for key in meta["requires"]:
        v = (material_props or {}).get(key)
        if v is None:
            raise ValueError(
                f"material property '{key}' is not on record for this "
                "material — refusing to substitute a guessed value")
        props[key] = float(v)

    if solver == "cantilever_beam":
        L = _need_number(inputs, "length_m")
        F = _need_number(inputs, "load_N", positive=False)
        area, I, _J, c = section_properties(inputs.get("section") or {})
        E = props["elastic_modulus_gpa"] * 1e9
        yld = props["yield_strength_mpa"] * 1e6
        delta = F * L ** 3 / (3 * E * I)
        slope = F * L ** 2 / (2 * E * I)
        moment = F * L
        stress = moment * c / I
        return {"deflection_m": delta, "slope_rad": slope,
                "bending_moment_Nm": moment, "max_stress_Pa": stress,
                "safety_factor": _safety_factor(yld, stress),
                "section_area_m2": area, "second_moment_m4": I}
    if solver == "simply_supported_beam":
        L = _need_number(inputs, "length_m")
        F = _need_number(inputs, "load_N", positive=False)
        area, I, _J, c = section_properties(inputs.get("section") or {})
        E = props["elastic_modulus_gpa"] * 1e9
        yld = props["yield_strength_mpa"] * 1e6
        delta = F * L ** 3 / (48 * E * I)
        moment = F * L / 4
        stress = moment * c / I
        return {"deflection_m": delta, "bending_moment_Nm": moment,
                "max_stress_Pa": stress,
                "safety_factor": _safety_factor(yld, stress),
                "section_area_m2": area, "second_moment_m4": I}
    if solver == "axial_bar":
        L = _need_number(inputs, "length_m")
        F = _need_number(inputs, "force_N", positive=False)
        area, _I, _J, _c = section_properties(inputs.get("section") or {})
        E = props["elastic_modulus_gpa"] * 1e9
        yld = props["yield_strength_mpa"] * 1e6
        stress = F / area
        strain = stress / E
        return {"stress_Pa": stress, "strain": strain,
                "elongation_m": strain * L,
                "safety_factor": _safety_factor(yld, stress),
                "section_area_m2": area}
    if solver == "torsion_shaft":
        L = _need_number(inputs, "length_m")
        T = _need_number(inputs, "torque_Nm", positive=False)
        d = _need_number(inputs, "diameter_m")
        E = props["elastic_modulus_gpa"] * 1e9
        nu = props["poisson_ratio"]
        yld = props["yield_strength_mpa"] * 1e6
        G = E / (2 * (1 + nu))
        J = math.pi * d ** 4 / 32
        tau = T * (d / 2) / J
        phi = T * L / (G * J)
        return {"shear_stress_Pa": tau, "angle_rad": phi,
                "shear_modulus_Pa": G,
                "safety_factor": _safety_factor(yld / math.sqrt(3), tau)}
    if solver == "thermal_conduction":
        th = _need_number(inputs, "thickness_m")
        area = _need_number(inputs, "area_m2")
        t_hot = inputs.get("t_hot_C")
        t_cold = inputs.get("t_cold_C")
        if not isinstance(t_hot, (int, float)) or not isinstance(t_cold, (int, float)):
            raise ValueError("t_hot_C and t_cold_C must be numbers")
        k = props["thermal_conductivity_w_mk"]
        R = th / (k * area)
        Q = (t_hot - t_cold) / R
        profile = [{"x_m": th * i / 10,
                    "t_C": t_hot + (t_cold - t_hot) * i / 10}
                   for i in range(11)]
        return {"heat_flow_W": Q, "thermal_resistance_K_W": R,
                "temperature_profile_C": profile}
    if solver == "lumped_thermal":
        vol = _need_number(inputs, "volume_m3")
        area = _need_number(inputs, "area_m2")
        h = _need_number(inputs, "h_W_m2K")
        t0 = inputs.get("t0_C")
        t_inf = inputs.get("t_inf_C")
        dur = _need_number(inputs, "duration_s")
        if not isinstance(t0, (int, float)) or not isinstance(t_inf, (int, float)):
            raise ValueError("t0_C and t_inf_C must be numbers")
        rho = props["density_kg_m3"]
        cp = props["specific_heat_j_kgk"]
        tau = rho * vol * cp / (h * area)
        series = [{"t_s": dur * i / 20,
                   "t_C": t_inf + (t0 - t_inf) * math.exp(-dur * i / 20 / tau)}
                  for i in range(21)]
        return {"time_constant_s": tau, "temperature_series_C": series,
                "final_temperature_C": series[-1]["t_C"]}
    if solver == "drag":
        v = _need_number(inputs, "velocity_m_s", positive=False)
        area = _need_number(inputs, "area_m2")
        cd = inputs.get("cd")
        if not isinstance(cd, (int, float)) or cd < 0:
            raise ValueError("cd must be a number >= 0")
        cl = inputs.get("cl", 0)
        if not isinstance(cl, (int, float)):
            raise ValueError("cl must be a number")
        fluid = FLUIDS.get(inputs.get("fluid", "air"))
        if fluid is None:
            raise ValueError("fluid must be 'air' or 'water'")
        L = inputs.get("length_m", 1.0)
        if not isinstance(L, (int, float)) or isinstance(L, bool) or L <= 0:
            raise ValueError("length_m must be a positive number")
        L = float(L)
        q = 0.5 * fluid["rho"] * v * v
        Re = fluid["rho"] * abs(v) * L / fluid["mu"]
        return {"drag_N": q * cd * area, "lift_N": q * cl * area,
                "dynamic_pressure_Pa": q, "reynolds": Re,
                "fluid": inputs.get("fluid", "air")}
    if solver == "free_fall":
        h = _need_number(inputs, "height_m")
        m = _need_number(inputs, "mass_kg")
        g = inputs.get("g_m_s2", 9.81)
        if not isinstance(g, (int, float)) or g <= 0:
            raise ValueError("g_m_s2 must be a positive number")
        t = math.sqrt(2 * h / g)
        v = g * t
        return {"fall_time_s": t, "impact_velocity_m_s": v,
                "impact_kinetic_energy_J": 0.5 * m * v * v}
    raise ValueError(f"solver {solver} has no analytical implementation")
