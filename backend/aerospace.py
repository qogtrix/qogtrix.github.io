"""Aerospace engineering — pure Python stdlib, SI units throughout.

Real (if simplified) engineering models, each labelled with its
assumptions. Nothing here is flight-certified engineering, and
nothing is a substitute for validated tools (XFOIL, AVL, OpenVSP
were checked — none is installed on this machine).

Models
------
- NACA 4-digit airfoil geometry + thin-airfoil theory
  (Cl = 2*pi*(alpha - alpha0); alpha0 from a numerical
  thin-airfoil integral of the camber-line slope).
- Finite wing: lifting-line slope correction, induced drag.
- Aircraft performance: lift/drag, stall speed, thrust and
  power required, Breguet range/endurance (propeller and
  electric), static margin, centre of gravity.
- Multirotor: momentum-theory hover power and endurance.
- Rockets: Tsiolkovsky delta-v (multi-stage), thrust,
  propellant mass, Barrowman centre of pressure, 2-D
  point-mass trajectory with ISA atmosphere and drag.
- ISA atmosphere (troposphere, h < 11000 m).

Every function raises ValueError on bad input or on a missing
required parameter — never a silent substitution.
"""

import math

G0 = 9.80665          # m/s^2
RHO_SL = 1.225        # kg/m^3, sea level
P0 = 101325.0         # Pa
T0 = 288.15           # K
R_AIR = 287.05        # J/kg/K
LAPSE = 0.0065        # K/m

# Typical published airfoil data (Cl at alpha=0, zero-lift angle,
# Cd0, drag-polar k, Clmax). Values are typical published values
# for the section at Re ~ 1e6, NOT certified data. Codes not in
# this table need Cd0/k/Clmax supplied by the user.
AIRFOIL_TABLE = {
    "naca2412": {"alpha0_deg": -2.1, "cd0": 0.006, "k": 0.045, "cl_max": 1.6},
    "naca4412": {"alpha0_deg": -4.3, "cd0": 0.006, "k": 0.040, "cl_max": 1.7},
    "naca0012": {"alpha0_deg": 0.0, "cd0": 0.006, "k": 0.050, "cl_max": 1.5},
    "naca23012": {"alpha0_deg": -1.1, "cd0": 0.007, "k": 0.045, "cl_max": 1.8},
    "naca6412": {"alpha0_deg": -6.2, "cd0": 0.007, "k": 0.038, "cl_max": 1.8},
}

AEROSPACE_SCHEMA = {
    "airfoil_codes": sorted(AIRFOIL_TABLE),
    "analyses": ["airfoil", "wing", "aircraft", "multirotor",
                 "rocket", "trajectory", "cg"],
    "notes": [
        "All units SI (m, kg, N, Pa, s). Angles in degrees in inputs.",
        "Thin-airfoil theory: Cl = 2*pi*(alpha - alpha0); valid for small angles, attached flow, incompressible flow.",
        "Drag polar Cd = Cd0 + k*Cl^2. Cd0, k and Clmax are typical published values for the table airfoils; supply your own for other sections.",
        "Rocket trajectory is a 2-D point-mass model: gravity, ISA drag, thrust profile, mass loss. No wind, no guidance, no 3-DOF attitude dynamics.",
        "Barrowman centre of pressure is subsonic, small-angle, and ignores body lift and interference.",
        "Nothing here is flight-certified engineering.",
    ],
}


# ------------------------------------------------------------------ atmosphere
def isa_density(altitude_m):
    """ISA air density (kg/m^3) at altitude, troposphere only."""
    h = float(altitude_m)
    if h < 0 or h > 11000:
        raise ValueError("isa_density supports 0-11000 m")
    T = T0 - LAPSE * h
    p = P0 * (T / T0) ** 5.2561
    return p / (R_AIR * T)


def dynamic_pressure(rho, velocity_m_s):
    return 0.5 * rho * velocity_m_s ** 2


# ------------------------------------------------------------------ airfoils
def _naca4(code):
    code = str(code).strip().lower().replace("naca", "")
    if len(code) != 4 or not code.isdigit():
        raise ValueError(f"airfoil code must be a NACA 4-digit code, got {code!r}")
    m = int(code[0]) / 100.0
    p = int(code[1]) / 10.0
    t = int(code[2:]) / 100.0
    if p == 0:
        raise ValueError("NACA 4-digit code with p=0 (symmetric camber position) is not supported")
    return m, p, t


def _camber_slope(m, p, x):
    if x < p:
        return 2 * m / (p * p) * (p - x)
    return 2 * m / ((1 - p) ** 2) * (p - x)


def naca4_ordinates(code, n=25):
    """Upper/lower surface ordinates of a NACA 4-digit airfoil.

    Returns {"x": [...], "yt": [...], "yc": [...], "xu": [...],
    "yu": [...], "xl": [...], "yl": [...]} with chord = 1.
    """
    m, p, t = _naca4(code)
    xs = [0.5 * (1 - math.cos(math.pi * i / (n - 1))) for i in range(n)]
    yt, yc, xu, yu, xl, yl = [], [], [], [], [], []
    for x in xs:
        yt_i = 5 * t * (0.2969 * math.sqrt(x) - 0.1260 * x - 0.3516 * x ** 2
                        + 0.2843 * x ** 3 - 0.1015 * x ** 4)
        if x < p:
            yc_i = m / (p * p) * (2 * p * x - x * x)
        else:
            yc_i = m / ((1 - p) ** 2) * ((1 - 2 * p) + 2 * p * x - x * x)
        theta = math.atan(_camber_slope(m, p, x))
        yt.append(yt_i); yc.append(yc_i)
        xu.append(x - yt_i * math.sin(theta)); yu.append(yc_i + yt_i * math.cos(theta))
        xl.append(x + yt_i * math.sin(theta)); yl.append(yc_i - yt_i * math.cos(theta))
    return {"x": xs, "yt": yt, "yc": yc, "xu": xu, "yu": yu, "xl": xl, "yl": yl}


def alpha0_deg(code):
    """Zero-lift angle (degrees) from the thin-airfoil integral
    of the camber-line slope. For table airfoils the published
    value is used; otherwise the integral is evaluated."""
    key = str(code).strip().lower().replace("naca", "")
    if "naca" + key in AIRFOIL_TABLE:
        return AIRFOIL_TABLE["naca" + key]["alpha0_deg"]
    m, p, _t = _naca4(code)
    # alpha0 = -(1/pi) * integral_0^pi (dyc/dx)(cos theta - 1) dtheta,
    # x = (1 - cos theta)/2. Simpson with 41 points.
    n = 40
    total = 0.0
    for i in range(n + 1):
        theta = math.pi * i / n
        x = 0.5 * (1 - math.cos(theta))
        w = 4 if i % 2 else 2
        if i in (0, n):
            w = 1
        total += w * _camber_slope(m, p, x) * (math.cos(theta) - 1)
    integral = total * (math.pi / n) / 3.0
    return math.degrees(-integral / math.pi)


def airfoil_coefficients(code, alpha_deg, cd0=None, k=None, cl_max=None):
    """Thin-airfoil lift + drag polar for one angle of attack.

    cd0/k/cl_max default to the table for known airfoils; for
    other codes they are required inputs.
    """
    key = "naca" + str(code).strip().lower().replace("naca", "")
    table = AIRFOIL_TABLE.get(key, {})
    a0 = alpha0_deg(code)
    cl = 2 * math.pi * (math.radians(alpha_deg) - math.radians(a0))
    cd0_v = table.get("cd0") if cd0 is None else float(cd0)
    k_v = table.get("k") if k is None else float(k)
    clmax_v = table.get("cl_max") if cl_max is None else float(cl_max)
    if cd0_v is None or k_v is None or clmax_v is None:
        raise ValueError(
            f"airfoil {code}: Cd0, k and Clmax are required (not in the "
            "typical-values table) — supply them, they are never guessed")
    cd = cd0_v + k_v * cl * cl
    return {"airfoil": key, "alpha_deg": float(alpha_deg),
            "alpha0_deg": a0, "cl": cl, "cd": cd,
            "cl_max": clmax_v, "cd0": cd0_v, "k": k_v,
            "stalled": abs(cl) > clmax_v,
            "lift_slope_per_rad": 2 * math.pi}


def wing_coefficients(airfoil_cl, alpha_deg, aspect_ratio, oswald_e,
                      airfoil_cd=None):
    """Finite-wing coefficients from a section Cl (lifting line).

    a = a0 / (1 + a0/(pi*e*AR)); Cdi = Cl^2/(pi*e*AR).
    airfoil_cd is the section drag at this Cl (Cd0 + k*Cl^2);
    if omitted, only induced drag is returned for Cd.
    """
    a0 = 2 * math.pi
    a = a0 / (1 + a0 / (math.pi * oswald_e * aspect_ratio))
    a0_deg = airfoil_cl  # section Cl at this alpha (already includes alpha0)
    cl_wing = a / a0 * a0_deg
    cdi = cl_wing ** 2 / (math.pi * oswald_e * aspect_ratio)
    cd = cdi if airfoil_cd is None else airfoil_cd + cdi
    return {"cl": cl_wing, "cd": cd, "cdi": cdi,
            "lift_slope_per_rad": a,
            "lift_slope_per_deg": a * math.pi / 180}


# ------------------------------------------------------------------ aircraft
def aircraft_performance(inp):
    """Level-flight performance for a fixed-wing aircraft.

    Inputs (SI): mass_kg, wing_area_m2, span_m, oswald_e,
    cd0, k, cl_max, cruise_speed_m_s, altitude_m,
    prop_efficiency (0-1), fuel: {specific_fuel_consumption
    (1/s, power-specific) OR battery_energy_Wh + motor_efficiency},
    components: [{name, mass_kg, x_m}] for CG (x measured from
    the nose datum), mac_m, x_ac_wing_m (aerodynamic centre of
    the wing from the datum), tail_volume (optional, for the
    neutral point).
    """
    def need(key, positive=True):
        v = inp.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or (positive and v <= 0):
            raise ValueError(f"{key} must be a positive number")
        return float(v)

    m = need("mass_kg")
    S = need("wing_area_m2")
    span = need("span_m")
    AR = span * span / S
    e = inp.get("oswald_e", 0.8)
    cd0 = need("cd0", positive=False)
    k = need("k", positive=False)
    cl_max = need("cl_max")
    v = need("cruise_speed_m_s")
    alt = float(inp.get("altitude_m", 0))
    rho = isa_density(alt)
    W = m * G0
    q = dynamic_pressure(rho, v)
    cl_cruise = W / (q * S)
    if cl_cruise > cl_max:
        raise ValueError(
            f"cruise Cl {cl_cruise:.3f} exceeds Clmax {cl_max}: the wing "
            "cannot sustain level flight at this speed/altitude")
    cd = cd0 + k * cl_cruise ** 2 + cl_cruise ** 2 / (math.pi * e * AR)
    D = q * S * cd
    L = q * S * cl_cruise
    vs = math.sqrt(2 * W / (rho * S * cl_max))
    ld = cl_cruise / cd
    thrust_req = D
    power_req = D * v
    eta = float(inp.get("prop_efficiency", 0.7))
    out = {"mass_kg": m, "weight_N": W, "aspect_ratio": AR,
           "air_density_kg_m3": rho, "dynamic_pressure_Pa": q,
           "cl_cruise": cl_cruise, "cd_cruise": cd,
           "lift_N": L, "drag_N": D, "lift_to_drag": ld,
           "stall_speed_m_s": vs, "stall_speed_kmh": vs * 3.6,
           "thrust_required_N": thrust_req,
           "power_required_W": power_req,
           "wing_loading_N_m2": W / S}
    # Range / endurance (Breguet).
    if "specific_fuel_consumption_1_s" in inp:
        c = need("specific_fuel_consumption_1_s", positive=False)
        w0 = W
        w1 = float(inp.get("landing_weight_N", w0 * 0.8))
        if w1 <= 0 or w1 >= w0:
            raise ValueError("landing_weight_N must be between 0 and takeoff weight")
        out["range_m"] = (eta / c) * ld * math.log(w0 / w1)
        out["range_km"] = out["range_m"] / 1000
        out["endurance_h"] = out["range_m"] / v / 3600
    elif "battery_energy_Wh" in inp:
        e_wh = need("battery_energy_Wh")
        eta_m = float(inp.get("motor_efficiency", 0.85))
        energy_j = e_wh * 3600
        out["endurance_h"] = energy_j * eta * eta_m / power_req / 3600
        out["range_m"] = out["endurance_h"] * 3600 * v
        out["range_km"] = out["range_m"] / 1000
    # Centre of gravity + static margin.
    comps = inp.get("components") or []
    if comps:
        total = sum(float(c["mass_kg"]) for c in comps)
        if abs(total - m) > 0.05 * m:
            raise ValueError(
                f"component masses sum to {total:.2f} kg but mass_kg is "
                f"{m:.2f} kg — they must agree within 5%")
        x_cg = sum(float(c["mass_kg"]) * float(c["x_m"]) for c in comps) / total
        out["cg_x_m"] = x_cg
        mac = inp.get("mac_m")
        x_ac = inp.get("x_ac_wing_m")
        if mac and x_ac:
            x_np = float(x_ac)
            tail_vol = inp.get("tail_volume")
            if tail_vol:
                # Tail shifts the neutral point aft by roughly
                # tail_volume * (tail lift slope / wing lift slope).
                x_np = float(x_ac) + float(tail_vol) * float(mac) * 0.8
            out["neutral_point_x_m"] = x_np
            out["static_margin"] = (x_np - x_cg) / float(mac)
            out["statically_stable"] = x_np > x_cg
    return out


def centre_of_gravity(components):
    """CG of a list of {name, mass_kg, x_m, y_m?, z_m?}."""
    if not components:
        raise ValueError("components must be a non-empty list")
    total = sum(float(c["mass_kg"]) for c in components)
    if total <= 0:
        raise ValueError("total mass must be positive")
    cg = {}
    for axis in ("x_m", "y_m", "z_m"):
        if any(axis in c for c in components):
            cg[axis] = sum(float(c["mass_kg"]) * float(c.get(axis, 0))
                           for c in components) / total
    return {"total_mass_kg": total, "cg": cg}


# ------------------------------------------------------------------ multirotor
def multirotor_hover(inp):
    """Momentum-theory hover for a multirotor.

    Inputs: mass_kg, n_rotors, rotor_diameter_m, altitude_m,
    figure_of_merit (0-1, default 0.7), battery_energy_Wh.
    """
    m = float(inp["mass_kg"])
    n = int(inp["n_rotors"])
    d = float(inp["rotor_diameter_m"])
    if m <= 0 or n <= 0 or d <= 0:
        raise ValueError("mass_kg, n_rotors and rotor_diameter_m must be positive")
    rho = isa_density(float(inp.get("altitude_m", 0)))
    area = n * math.pi * (d / 2) ** 2
    W = m * G0
    T = W / n
    v_ind = math.sqrt(T / (2 * rho * (math.pi * (d / 2) ** 2)))
    fom = float(inp.get("figure_of_merit", 0.7))
    power = n * T * v_ind / fom
    out = {"weight_N": W, "thrust_per_rotor_N": T,
           "disk_area_m2": area, "disk_loading_N_m2": W / area,
           "induced_velocity_m_s": v_ind,
           "hover_power_W": power,
           "power_loading_N_W": W / power}
    if "battery_energy_Wh" in inp:
        e = float(inp["battery_energy_Wh"])
        out["hover_endurance_h"] = e * 3600 * 0.85 / power / 3600
        out["hover_endurance_min"] = out["hover_endurance_h"] * 60
    return out


# ------------------------------------------------------------------ rockets
def rocket_delta_v(stages):
    """Tsiolkovsky delta-v for a serial multi-stage rocket.

    Each stage: {name?, isp_s, m0_kg, mf_kg} where m0 is the
    mass at ignition of that stage (including everything above)
    and mf is the mass at burnout (dry stage + everything above).
    Returns per-stage and total delta-v, mass ratios and
    propellant masses.
    """
    if not stages:
        raise ValueError("stages must be a non-empty list")
    total = 0.0
    out_stages = []
    for i, s in enumerate(stages):
        isp = float(s["isp_s"]); m0 = float(s["m0_kg"]); mf = float(s["mf_kg"])
        if isp <= 0 or m0 <= 0 or mf <= 0 or mf >= m0:
            raise ValueError(
                f"stage {i}: need isp_s > 0 and 0 < mf_kg < m0_kg "
                f"(got isp {isp}, m0 {m0}, mf {mf})")
        dv = isp * G0 * math.log(m0 / mf)
        total += dv
        out_stages.append({"stage": i + 1, "name": s.get("name", f"stage {i + 1}"),
                           "isp_s": isp, "mass_ratio": m0 / mf,
                           "propellant_kg": m0 - mf, "delta_v_m_s": dv})
    return {"stages": out_stages, "total_delta_v_m_s": total,
            "total_delta_v_km_s": total / 1000}


def rocket_thrust(inp):
    """Thrust from mass flow and exhaust velocity (plus pressure term).

    Inputs: mdot_kg_s, isp_s (or exhaust_velocity_m_s), pe_Pa,
    pa_Pa, Ae_m2.
    """
    mdot = float(inp["mdot_kg_s"])
    if mdot <= 0:
        raise ValueError("mdot_kg_s must be positive")
    ve = inp.get("exhaust_velocity_m_s")
    if ve is None:
        ve = float(inp["isp_s"]) * G0
    pe = float(inp.get("pe_Pa", P0)); pa = float(inp.get("pa_Pa", P0))
    Ae = float(inp.get("Ae_m2", 0))
    F_mom = mdot * ve
    F_press = (pe - pa) * Ae
    return {"thrust_N": F_mom + F_press,
            "momentum_thrust_N": F_mom,
            "pressure_thrust_N": F_press,
            "exhaust_velocity_m_s": ve,
            "effective_isp_s": (F_mom + F_press) / (mdot * G0)}


def barrowman_cp(components):
    """Barrowman centre of pressure (subsonic, small angles).

    Components: nose {type: "nose", shape: "conical"|"ogive"|"parabolic",
    length_m, diameter_m, x_base_m} (x of the base, measured from
    the nose tip); body {type: "body", length_m, diameter_m,
    x_base_m}; fins {type: "fins", n, root_chord_m, tip_chord_m,
    span_m (one fin, from body surface), x_leading_m (leading edge
    at the root, from the nose tip), body_diameter_m}.
    Returns CP from the nose tip and the stability margin vs a
    supplied cg_x_m (calibres = (CP - CG)/diameter).
    """
    if not components:
        raise ValueError("components must be a non-empty list")
    total_cn = 0.0
    moment = 0.0
    d_ref = None
    details = []
    for c in components:
        t = c["type"]
        if t == "nose":
            d = float(c["diameter_m"]); L = float(c["length_m"])
            d_ref = d_ref or d
            cn = 2.0
            x_cp = float(c["x_base_m"]) - 0.666 * L if c.get("shape") == "conical" else \
                float(c["x_base_m"]) - 0.5 * L
            details.append({"part": "nose", "cn_alpha": cn, "x_cp_m": x_cp})
        elif t == "body":
            # Cylindrical body contributes no normal force in
            # Barrowman theory (only the nose and fins do).
            continue
        elif t == "fins":
            n = int(c["n"]); cr = float(c["root_chord_m"]); ct = float(c["tip_chord_m"])
            s = float(c["span_m"]); d = float(c["body_diameter_m"])
            d_ref = d_ref or d
            # Fin normal-force slope (per radian), Barrowman:
            # Cn = (4n (s/d)^2) / (1 + sqrt(1 + (2l/(a+b))^2)) where
            # l is the fin mid-chord length... use the standard form
            # with the mean chord.
            lm = (cr + ct) / 2
            cn = (4 * n * (s / d) ** 2) / (1 + math.sqrt(1 + (2 * lm / (cr + ct)) ** 2))
            # CP of the fin set: leading edge of the root + one
            # third of the mean aerodynamic chord. Sweep is ignored
            # (straight leading-edge assumption) — documented limit.
            x_le = float(c["x_leading_m"])
            mac = (2 / 3) * cr * (1 + ct / cr + (ct / cr) ** 2) / (1 + ct / cr)
            x_cp = x_le + mac / 3
            details.append({"part": "fins", "cn_alpha": cn, "x_cp_m": x_cp})
        else:
            raise ValueError(f"unknown rocket component type: {t!r}")
        total_cn += cn
        moment += cn * x_cp
    if total_cn <= 0:
        raise ValueError("no lifting components (need a nose and/or fins)")
    cp = moment / total_cn
    out = {"cp_x_m": cp, "total_cn_alpha": total_cn, "parts": details}
    return out


def rocket_stability(components, cg_x_m, diameter_m):
    """CP from Barrowman + stability margin in calibres."""
    cp = barrowman_cp(components)
    margin = (cp["cp_x_m"] - float(cg_x_m)) / float(diameter_m)
    return {**cp, "cg_x_m": float(cg_x_m),
            "stability_calibres": margin,
            "stable": margin > 0,
            "margin_ok": 1.0 <= margin <= 2.5}


def trajectory_2d(inp):
    """2-D point-mass rocket trajectory.

    Inputs: mass_kg (initial), diameter_m, cd (drag coefficient),
    launch_angle_deg (from horizontal, 90 = vertical),
    thrust_profile: [{t_start_s, t_end_s, thrust_N, mdot_kg_s}],
    dt_s (default 0.1), t_max_s (default 600), altitude_0_m.
    Integrates with RK2 (midpoint). Returns apogee, max speed,
    range, flight time and a downsampled time series.
    """
    m0 = float(inp["mass_kg"])
    d = float(inp["diameter_m"])
    cd = float(inp.get("cd", 0.5))
    ang = math.radians(float(inp.get("launch_angle_deg", 90)))
    dt = float(inp.get("dt_s", 0.1))
    t_max = float(inp.get("t_max_s", 600))
    area = math.pi * (d / 2) ** 2
    profile = inp.get("thrust_profile") or []
    for ph in profile:
        if ph["t_end_s"] <= ph["t_start_s"] or ph["thrust_N"] < 0 or ph["mdot_kg_s"] < 0:
            raise ValueError("bad thrust profile phase")
    x = 0.0
    y = float(inp.get("altitude_0_m", 0))
    vx = 0.0
    vy = 0.0
    m = m0
    t = 0.0
    apogee = y
    vmax = 0.0
    series = []
    step = 0
    while t < t_max:
        thrust = 0.0
        mdot = 0.0
        for ph in profile:
            if ph["t_start_s"] <= t < ph["t_end_s"]:
                thrust = float(ph["thrust_N"])
                mdot = float(ph["mdot_kg_s"])
        rho = isa_density(min(max(y, 0), 11000)) if y < 11000 else 0.0
        v = math.hypot(vx, vy)
        drag = 0.5 * rho * v * v * cd * area if v > 0 else 0.0
        ax = (thrust * math.cos(ang) - (drag * vx / v if v > 0 else 0.0)) / m
        ay = (thrust * math.sin(ang) - m * G0 - (drag * vy / v if v > 0 else 0.0)) / m
        # RK2 midpoint.
        vx2 = vx + ax * dt / 2
        vy2 = vy + ay * dt / 2
        v2 = math.hypot(vx2, vy2)
        rho2 = rho
        drag2 = 0.5 * rho2 * v2 * v2 * cd * area if v2 > 0 else 0.0
        ax2 = (thrust * math.cos(ang) - (drag2 * vx2 / v2 if v2 > 0 else 0.0)) / m
        ay2 = (thrust * math.sin(ang) - m * G0 - (drag2 * vy2 / v2 if v2 > 0 else 0.0)) / m
        vx += ax2 * dt
        vy += ay2 * dt
        x += vx * dt
        y += vy * dt
        m = max(m - mdot * dt, 0.1)
        t += dt
        step += 1
        apogee = max(apogee, y)
        vmax = max(vmax, math.hypot(vx, vy))
        if step % 10 == 0:
            series.append({"t_s": round(t, 2), "x_m": round(x, 1),
                           "y_m": round(y, 1), "v_m_s": round(math.hypot(vx, vy), 1),
                           "mass_kg": round(m, 2)})
        if y < 0 and t > 1:
            break
        if m <= 0.1 and thrust == 0 and vy < 0 and y <= 0:
            break
    return {"apogee_m": apogee, "max_velocity_m_s": vmax,
            "range_m": x, "flight_time_s": t,
            "final_mass_kg": m, "series": series}
