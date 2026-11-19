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
    "gear_train": {
        "label": "Gear train (ratio, speed, torque, tooth forces)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["z1", "z2", "module_mm", "input_speed_rpm",
                   "input_torque_Nm", "efficiency", "pressure_angle_deg"],
        "outputs": ["gear_ratio", "output_speed_rpm", "output_torque_Nm",
                    "power_in_W", "power_out_W", "pitch_diameter_1_m",
                    "pitch_diameter_2_m", "centre_distance_m",
                    "tangential_force_N", "radial_force_N"],
        "requires": [],
        "assumptions": [
            "Spur gears, module in mm, pressure angle 20 deg by default",
            "Efficiency is a single user-supplied number for the mesh",
            "Tooth forces from the input torque and pitch diameter",
        ],
    },
    "shaft_combined": {
        "label": "Shaft under combined bending and torsion",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["diameter_m", "length_m", "torque_Nm",
                   "bending_moment_Nm", "material_id"],
        "outputs": ["bending_stress_Pa", "shear_stress_Pa",
                    "von_mises_stress_Pa", "safety_factor",
                    "angle_of_twist_rad", "deflection_m"],
        "requires": ["elastic_modulus_gpa", "poisson_ratio",
                     "yield_strength_mpa"],
        "assumptions": [
            "Solid circular shaft; linear elasticity",
            "von Mises equivalent stress vs yield strength",
            "Deflection estimated as a simply supported beam with a "
            "centre load equivalent to the given bending moment",
        ],
    },
    "bearing_load": {
        "label": "Bearing load and required dynamic rating",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["radial_load_N", "axial_load_N", "speed_rpm", "life_h"],
        "outputs": ["equivalent_load_N", "life_million_rev",
                    "required_rating_N"],
        "requires": [],
        "assumptions": [
            "Deep-groove ball bearing factors: e = 0.22; "
            "Fa/Fr <= e -> X = 1, Y = 0; otherwise X = 0.56, Y = 1.4",
            "Basic rating life L10 = (C/P)^3 (ball bearings)",
        ],
    },
    "belt_drive": {
        "label": "Open belt drive (length, tensions, ratio)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["d1_m", "d2_m", "centre_m", "input_speed_rpm",
                   "power_W", "mu"],
        "outputs": ["gear_ratio", "output_speed_rpm", "belt_speed_m_s",
                    "belt_length_m", "wrap_angle_rad",
                    "tension_ratio", "tight_tension_N", "slack_tension_N"],
        "requires": [],
        "assumptions": [
            "Open belt (not crossed); capstan equation T1/T2 = e^(mu*beta)",
            "No slip, no belt stretch, no centrifugal tension",
        ],
    },
    "spring_helical": {
        "label": "Helical compression spring",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["wire_d_m", "coil_d_m", "coils", "load_N", "material_id"],
        "outputs": ["spring_rate_N_m", "deflection_m", "shear_stress_Pa",
                    "wahl_factor", "solid_length_m"],
        "requires": ["elastic_modulus_gpa", "poisson_ratio"],
        "assumptions": [
            "Wahl correction factor for curvature and direct shear",
            "Shear modulus G = E / (2(1+nu))",
            "Ends squared and ground assumed for the solid length",
        ],
    },
    "flywheel": {
        "label": "Flywheel (inertia, stored energy, rim stress)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["outer_d_m", "inner_d_m", "thickness_m", "speed_rpm",
                   "material_id"],
        "outputs": ["mass_kg", "inertia_kg_m2", "energy_J",
                    "rim_speed_m_s", "rim_stress_Pa"],
        "requires": ["density_kg_m3"],
        "assumptions": [
            "Annular disc; inertia I = 1/2 m (Ro^2 + Ri^2)",
            "Rim stress approximated as rho * v^2 (thin-rim estimate)",
        ],
    },
    "hydraulic_cylinder": {
        "label": "Hydraulic cylinder (force and speed)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["bore_d_m", "rod_d_m", "pressure_Pa", "flow_m3_s"],
        "outputs": ["extend_force_N", "retract_force_N",
                    "extend_speed_m_s", "retract_speed_m_s"],
        "requires": [],
        "assumptions": ["Ideal cylinder: no friction, no leakage, incompressible fluid"],
    },
    "crank_slider": {
        "label": "Crank-slider kinematics (position, velocity, acceleration)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["crank_r_m", "rod_l_m", "speed_rpm"],
        "outputs": ["stroke_m", "max_velocity_m_s", "max_acceleration_m_s2",
                    "mean_piston_speed_m_s", "series"],
        "requires": [],
        "assumptions": [
            "Rigid crank and rod, constant crank speed, no clearance",
            "Position measured from the crank centre along the cylinder axis",
        ],
    },
    "fatigue_shaft": {
        "label": "Shaft fatigue check (modified Goodman)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["diameter_m", "bending_moment_Nm", "torque_Nm",
                   "material_id"],
        "outputs": ["alternating_stress_Pa", "mean_stress_Pa",
                    "goodman_safety_factor", "static_safety_factor"],
        "requires": ["tensile_strength_mpa", "fatigue_limit_mpa",
                     "yield_strength_mpa"],
        "assumptions": [
            "Rotating shaft: bending fully reversed, torsion steady",
            "Modified Goodman: 1/SF = sigma_a'/Se + sigma_m'/Sut",
            "Endurance limit taken as recorded; no surface/size factors applied",
        ],
    },
    "vibration_1dof": {
        "label": "Single-degree-of-freedom vibration",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["stiffness_N_m", "mass_kg"],
        "outputs": ["natural_frequency_Hz", "natural_frequency_rad_s",
                    "period_s", "critical_speed_rpm"],
        "requires": [],
        "assumptions": ["Undamped, linear spring-mass system"],
    },
    "power_transmission": {
        "label": "Power from torque and speed",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["torque_Nm", "speed_rpm"],
        "outputs": ["angular_velocity_rad_s", "power_W", "power_kW", "power_hp"],
        "requires": [],
        "assumptions": ["Steady rotation; P = T * omega"],
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
    if solver == "gear_train":
        z1 = inputs.get("z1"); z2 = inputs.get("z2")
        if not isinstance(z1, int) or isinstance(z1, bool) or z1 < 6:
            raise ValueError("z1 must be an integer >= 6")
        if not isinstance(z2, int) or isinstance(z2, bool) or z2 < 6:
            raise ValueError("z2 must be an integer >= 6")
        mod = _need_number(inputs, "module_mm") / 1000
        n1 = _need_number(inputs, "input_speed_rpm", positive=False)
        T1 = _need_number(inputs, "input_torque_Nm", positive=False)
        eta = inputs.get("efficiency", 0.95)
        if not isinstance(eta, (int, float)) or not 0 < eta <= 1:
            raise ValueError("efficiency must be in (0, 1]")
        alpha = math.radians(inputs.get("pressure_angle_deg", 20))
        ratio = z2 / z1
        d1, d2 = mod * z1, mod * z2
        n2 = n1 / ratio
        T2 = T1 * ratio * eta
        w1 = n1 * 2 * math.pi / 60
        Ft = 2 * T1 / d1 if d1 else 0
        return {"gear_ratio": ratio, "output_speed_rpm": n2,
                "output_torque_Nm": T2, "power_in_W": T1 * w1,
                "power_out_W": T1 * w1 * eta,
                "pitch_diameter_1_m": d1, "pitch_diameter_2_m": d2,
                "centre_distance_m": (d1 + d2) / 2,
                "tangential_force_N": Ft,
                "radial_force_N": Ft * math.tan(alpha)}
    if solver == "shaft_combined":
        d = _need_number(inputs, "diameter_m")
        L = _need_number(inputs, "length_m")
        T = _need_number(inputs, "torque_Nm", positive=False)
        M = _need_number(inputs, "bending_moment_Nm", positive=False)
        E = props["elastic_modulus_gpa"] * 1e9
        nu = props["poisson_ratio"]
        yld = props["yield_strength_mpa"] * 1e6
        G = E / (2 * (1 + nu))
        sigma = 32 * M / (math.pi * d ** 3)
        tau = 16 * T / (math.pi * d ** 3)
        vm = math.sqrt(sigma ** 2 + 3 * tau ** 2)
        J = math.pi * d ** 4 / 32
        I = math.pi * d ** 4 / 64
        phi = T * L / (G * J)
        F_eq = 4 * M / L  # simply supported centre load giving moment M
        delta = F_eq * L ** 3 / (48 * E * I)
        return {"bending_stress_Pa": sigma, "shear_stress_Pa": tau,
                "von_mises_stress_Pa": vm,
                "safety_factor": _safety_factor(yld, vm),
                "angle_of_twist_rad": phi, "deflection_m": delta}
    if solver == "bearing_load":
        Fr = _need_number(inputs, "radial_load_N", positive=False)
        Fa = _need_number(inputs, "axial_load_N", positive=False)
        n = _need_number(inputs, "speed_rpm", positive=False)
        Lh = _need_number(inputs, "life_h")
        ratio_f = Fa / Fr if Fr else 0
        if ratio_f <= 0.22:
            X, Y = 1.0, 0.0
        else:
            X, Y = 0.56, 1.4
        P = X * Fr + Y * Fa
        L10 = 60 * n * Lh / 1e6
        return {"equivalent_load_N": P, "life_million_rev": L10,
                "required_rating_N": P * L10 ** (1 / 3)}
    if solver == "belt_drive":
        d1 = _need_number(inputs, "d1_m"); d2 = _need_number(inputs, "d2_m")
        C = _need_number(inputs, "centre_m")
        n1 = _need_number(inputs, "input_speed_rpm", positive=False)
        Pwr = _need_number(inputs, "power_W", positive=False)
        mu = inputs.get("mu", 0.3)
        if not isinstance(mu, (int, float)) or mu <= 0:
            raise ValueError("mu must be a positive number")
        ratio = d2 / d1
        v = math.pi * d1 * n1 / 60
        Lb = 2 * C + math.pi / 2 * (d1 + d2) + (d2 - d1) ** 2 / (4 * C)
        beta = math.pi - 2 * math.asin(min(1, (d2 - d1) / (2 * C)))
        tr = math.exp(mu * beta)
        dT = Pwr / v if v else 0
        T1 = dT * tr / (tr - 1) if tr > 1 else dT
        return {"gear_ratio": ratio, "output_speed_rpm": n1 / ratio,
                "belt_speed_m_s": v, "belt_length_m": Lb,
                "wrap_angle_rad": beta, "tension_ratio": tr,
                "tight_tension_N": T1, "slack_tension_N": T1 - dT}
    if solver == "spring_helical":
        dw = _need_number(inputs, "wire_d_m")
        Dc = _need_number(inputs, "coil_d_m")
        n = inputs.get("coils")
        if not isinstance(n, (int, float)) or n < 1:
            raise ValueError("coils must be >= 1")
        F = _need_number(inputs, "load_N", positive=False)
        E = props["elastic_modulus_gpa"] * 1e9
        nu = props["poisson_ratio"]
        G = E / (2 * (1 + nu))
        k = G * dw ** 4 / (8 * Dc ** 3 * n)
        Cidx = Dc / dw
        Kw = (4 * Cidx - 1) / (4 * Cidx - 4) + 0.615 / Cidx
        tau = Kw * 8 * F * Dc / (math.pi * dw ** 3)
        return {"spring_rate_N_m": k, "deflection_m": F / k if k else 0,
                "shear_stress_Pa": tau, "wahl_factor": Kw,
                "solid_length_m": n * dw}
    if solver == "flywheel":
        Do = _need_number(inputs, "outer_d_m")
        Di = inputs.get("inner_d_m", 0) or 0
        if not isinstance(Di, (int, float)) or Di < 0 or Di >= Do:
            raise ValueError("inner_d_m must be >= 0 and smaller than outer_d_m")
        th = _need_number(inputs, "thickness_m")
        n = _need_number(inputs, "speed_rpm", positive=False)
        rho = props["density_kg_m3"]
        mass = rho * math.pi / 4 * (Do ** 2 - Di ** 2) * th
        I = 0.5 * mass * ((Do / 2) ** 2 + (Di / 2) ** 2)
        w = n * 2 * math.pi / 60
        v = w * Do / 2
        return {"mass_kg": mass, "inertia_kg_m2": I,
                "energy_J": 0.5 * I * w * w, "rim_speed_m_s": v,
                "rim_stress_Pa": rho * v * v}
    if solver == "hydraulic_cylinder":
        bore = _need_number(inputs, "bore_d_m")
        rod = _need_number(inputs, "rod_d_m")
        p = _need_number(inputs, "pressure_Pa")
        Q = _need_number(inputs, "flow_m3_s", positive=False)
        if rod >= bore:
            raise ValueError("rod_d_m must be smaller than bore_d_m")
        A_ext = math.pi / 4 * bore ** 2
        A_ret = math.pi / 4 * (bore ** 2 - rod ** 2)
        return {"extend_force_N": p * A_ext, "retract_force_N": p * A_ret,
                "extend_speed_m_s": Q / A_ext if A_ext else 0,
                "retract_speed_m_s": Q / A_ret if A_ret else 0}
    if solver == "crank_slider":
        r = _need_number(inputs, "crank_r_m")
        l = _need_number(inputs, "rod_l_m")
        n = _need_number(inputs, "speed_rpm", positive=False)
        if l <= r:
            raise ValueError("rod_l_m must be larger than crank_r_m")
        w = n * 2 * math.pi / 60
        series = []
        max_v = 0.0; max_a = 0.0
        for deg in range(0, 721, 10):
            th = math.radians(deg)
            s_, c_ = math.sin(th), math.cos(th)
            root = math.sqrt(max(l * l - r * r * s_ * s_, 0))
            x = r * c_ + root
            ds = -r * s_ - (r * r * s_ * c_) / root if root else -r * s_
            d2s = -r * c_ - ((r * r * (2 * c_ * c_ - 1)) / root
                             + (r ** 4 * s_ * s_ * c_ * c_) / (root ** 3)) if root else -r * c_
            v = w * ds; a = w * w * d2s
            max_v = max(max_v, abs(v)); max_a = max(max_a, abs(a))
            series.append({"angle_deg": deg, "position_m": round(x, 6),
                           "velocity_m_s": round(v, 4),
                           "acceleration_m_s2": round(a, 3)})
        return {"stroke_m": 2 * r, "max_velocity_m_s": round(max_v, 4),
                "max_acceleration_m_s2": round(max_a, 3),
                "mean_piston_speed_m_s": 2 * (2 * r) * n / 60,
                "series": series}
    if solver == "fatigue_shaft":
        d = _need_number(inputs, "diameter_m")
        M = _need_number(inputs, "bending_moment_Nm", positive=False)
        T = _need_number(inputs, "torque_Nm", positive=False)
        Sut = props["tensile_strength_mpa"] * 1e6
        Se = props["fatigue_limit_mpa"] * 1e6
        yld = props["yield_strength_mpa"] * 1e6
        sigma_a = 32 * M / (math.pi * d ** 3)
        tau_m = 16 * T / (math.pi * d ** 3)
        sigma_m = math.sqrt(3) * tau_m
        sf_goodman = 1 / (sigma_a / Se + sigma_m / Sut) if (sigma_a or sigma_m) else None
        sigma_static = math.sqrt(sigma_a ** 2 + 3 * tau_m ** 2)
        return {"alternating_stress_Pa": sigma_a, "mean_stress_Pa": sigma_m,
                "goodman_safety_factor": sf_goodman,
                "static_safety_factor": _safety_factor(yld, sigma_static)}
    if solver == "vibration_1dof":
        k = _need_number(inputs, "stiffness_N_m")
        m = _need_number(inputs, "mass_kg")
        wn = math.sqrt(k / m)
        fn = wn / (2 * math.pi)
        return {"natural_frequency_Hz": fn, "natural_frequency_rad_s": wn,
                "period_s": 1 / fn if fn else 0, "critical_speed_rpm": fn * 60}
    if solver == "power_transmission":
        T = _need_number(inputs, "torque_Nm", positive=False)
        n = _need_number(inputs, "speed_rpm", positive=False)
        w = n * 2 * math.pi / 60
        P = T * w
        return {"angular_velocity_rad_s": w, "power_W": P,
                "power_kW": P / 1000, "power_hp": P / 745.7}
    raise ValueError(f"solver {solver} has no analytical implementation")
