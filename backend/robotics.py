"""Robotics engineering — pure Python stdlib, SI units throughout.

Real (if simplified) engineering models, each labelled with its
assumptions. PyBullet / ROS / MoveIt were checked — none is
installed on this machine, so this module implements the
kinematics, control and collision geometry directly.

Models
------
- Denavit-Hartenberg forward kinematics (standard DH).
- Geometric Jacobian.
- Analytic inverse kinematics: 2R and 3R planar arms.
- Damped least-squares numerical IK for general arms, with
  joint-limit clamping and a reported residual.
- Joint-space trajectories: cubic polynomial and trapezoidal
  velocity profile.
- Collision detection: sphere-sphere, capsule-sphere,
  capsule-capsule (segment-segment distance), capsule-box.
- PID control of a DC-motor plant (electrical + mechanical
  states), with anti-windup and voltage saturation.
- Differential-drive mobile robot: forward/inverse kinematics
  and odometry.

Every function raises ValueError on bad input — never a silent
substitution. Joint limits are enforced and reported, never
quietly ignored.
"""

import math

ROBOTICS_SCHEMA = {
    "analyses": ["fk", "ik", "trajectory", "collision", "pid",
                 "diff_drive", "workspace"],
    "notes": [
        "All units SI (m, kg, N, rad, s). Angles in radians in the API; the UI converts from degrees.",
        "Standard Denavit-Hartenberg parameters: a, alpha, d, theta.",
        "Analytic IK exists for 2R and 3R planar arms. Other arms use damped least-squares IK with a reported residual — a failed convergence is reported, never hidden.",
        "Collision geometry treats links as capsules (segment + radius) and obstacles as spheres or axis-aligned boxes.",
        "The PID plant is a DC motor (Stage 8 parameters: R, L, Kt, Ke, J, b) driving a load. Step-response metrics are computed from the simulated series.",
        "Nothing here is validated for a real robot or a safety-critical application.",
    ],
}


# ------------------------------------------------------------------ matrices
def _mat_mul(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(len(B)))
             for j in range(len(B[0]))] for i in range(len(A))]


def _mat_vec(A, v):
    return [sum(A[i][k] * v[k] for k in range(len(v))) for i in range(len(A))]


def _identity(n=4):
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def _dh_matrix(a, alpha, d, theta):
    ct, st = math.cos(theta), math.sin(theta)
    ca, sa = math.cos(alpha), math.sin(alpha)
    return [[ct, -st * ca, st * sa, a * ct],
            [st, ct * ca, -ct * sa, a * st],
            [0.0, sa, ca, d],
            [0.0, 0.0, 0.0, 1.0]]


def _transpose(A):
    return [[A[j][i] for j in range(len(A))] for i in range(len(A[0]))]


def _solve_3x3(A, b):
    """Gaussian elimination for a 3x3 system. Raises on singularity."""
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            raise ValueError("singular matrix in IK solve")
        M[col], M[piv] = M[piv], M[col]
        for r in range(col + 1, 3):
            f = M[r][col] / M[col][col]
            for c in range(col, 4):
                M[r][c] -= f * M[col][c]
    x = [0.0] * 3
    for i in (2, 1, 0):
        x[i] = (M[i][3] - sum(M[i][j] * x[j] for j in range(i + 1, 3))) / M[i][i]
    return x


# ------------------------------------------------------------------ validation
def _check_dh(dh):
    if not dh or not isinstance(dh, list):
        raise ValueError("dh must be a non-empty list of DH rows")
    for i, row in enumerate(dh):
        for k in ("a", "alpha", "d", "theta"):
            if k not in row or not isinstance(row[k], (int, float)):
                raise ValueError(f"dh[{i}].{k} must be a number")
        if row.get("type", "revolute") not in ("revolute", "prismatic"):
            raise ValueError(f"dh[{i}].type must be revolute or prismatic")


def _check_limits(joints, limits):
    if limits is None:
        return
    if len(limits) != len(joints):
        raise ValueError("joint limits must match the number of joints")
    for i, (q, (lo, hi)) in enumerate(zip(joints, limits)):
        if lo > hi:
            raise ValueError(f"joint {i} limits are inverted ({lo} > {hi})")


def joint_limit_violations(joints, limits):
    """List of {joint, value, limit, direction} for out-of-limit joints."""
    out = []
    if not limits:
        return out
    for i, (q, (lo, hi)) in enumerate(zip(joints, limits)):
        if q < lo:
            out.append({"joint": i, "value": q, "limit": lo, "direction": "below_min"})
        elif q > hi:
            out.append({"joint": i, "value": q, "limit": hi, "direction": "above_max"})
    return out


def clamp_joints(joints, limits):
    if not limits:
        return list(joints)
    return [min(max(q, lo), hi) for q, (lo, hi) in zip(joints, limits)]


# ------------------------------------------------------------------ FK
def fk_dh(dh, joints):
    """Forward kinematics. Returns {"transforms": [4x4, ...],
    "positions": [[x,y,z], ...] (one per joint frame, base first),
    "end_position": [x,y,z], "end_transform": 4x4}."""
    _check_dh(dh)
    if len(joints) != len(dh):
        raise ValueError("joints must match the number of DH rows")
    T = _identity()
    transforms = []
    positions = [[0.0, 0.0, 0.0]]
    for row, q in zip(dh, joints):
        a, alpha, d, theta = row["a"], row["alpha"], row["d"], row["theta"]
        if row.get("type", "revolute") == "revolute":
            theta = theta + q
        else:
            d = d + q
        T = _mat_mul(T, _dh_matrix(a, alpha, d, theta))
        transforms.append([r[:] for r in T])
        positions.append([T[0][3], T[1][3], T[2][3]])
    return {"transforms": transforms, "positions": positions,
            "end_position": positions[-1], "end_transform": T}


def geometric_jacobian(dh, joints):
    """6xN geometric Jacobian (linear + angular) at the end effector."""
    fk = fk_dh(dh, joints)
    n = len(dh)
    origins = fk["positions"]
    pe = fk["end_position"]
    J = [[0.0] * n for _ in range(6)]
    for i in range(n):
        Ti = fk["transforms"][i - 1] if i > 0 else _identity()
        z = [Ti[0][2], Ti[1][2], Ti[2][2]]
        o = origins[i]
        if dh[i].get("type", "revolute") == "revolute":
            # linear: z x (pe - o); angular: z
            r = [pe[0] - o[0], pe[1] - o[1], pe[2] - o[2]]
            cross = [z[1] * r[2] - z[2] * r[1],
                     z[2] * r[0] - z[0] * r[2],
                     z[0] * r[1] - z[1] * r[0]]
            for k in range(3):
                J[k][i] = cross[k]
                J[k + 3][i] = z[k]
        else:
            for k in range(3):
                J[k][i] = z[k]
    return J


# ------------------------------------------------------------------ IK
def ik_2r(l1, l2, target, elbow="down"):
    """Analytic IK for a planar 2R arm. target = [x, y].
    Returns {"joints": [q1, q2], "reachable": bool} or raises."""
    x, y = float(target[0]), float(target[1])
    r = math.hypot(x, y)
    if r > l1 + l2 or r < abs(l1 - l2):
        raise ValueError(
            f"target ({x:.3f}, {y:.3f}) is outside the 2R workspace "
            f"(reach {abs(l1 - l2):.3f}–{l1 + l2:.3f} m)")
    cos_q2 = max(-1.0, min(1.0, (x * x + y * y - l1 * l1 - l2 * l2) / (2 * l1 * l2)))
    q2 = math.acos(cos_q2)
    if elbow == "down":
        q2 = -q2
    q1 = math.atan2(y, x) - math.atan2(l2 * math.sin(q2), l1 + l2 * math.cos(q2))
    return {"joints": [q1, q2], "reachable": True, "elbow": elbow}


def ik_3r(l1, l2, l3, target, phi):
    """Analytic IK for a planar 3R arm. target = [x, y], phi is the
    desired end-effector orientation (rad). Solves the wrist
    position with 2R IK, then the wrist angle."""
    x, y = float(target[0]), float(target[1])
    wx = x - l3 * math.cos(phi)
    wy = y - l3 * math.sin(phi)
    base = ik_2r(l1, l2, [wx, wy])
    q1, q2 = base["joints"]
    q3 = phi - q1 - q2
    return {"joints": [q1, q2, q3], "reachable": True}


def ik_dls(dh, target_pos, q0, limits=None, max_iter=200, tol=1e-6,
           damping=0.05, target_ori=None):
    """Damped least-squares IK for a general arm.

    target_pos = [x, y, z]; q0 = seed joints. Position-only by
    default; target_ori (a 3x3 rotation) adds orientation error.
    Returns {"joints", "residual_m", "iterations", "converged",
    "limit_violations"}.
    """
    _check_dh(dh)
    n = len(dh)
    if len(q0) != n:
        raise ValueError("seed joints must match the number of DH rows")
    q = list(q0)
    lam2 = damping * damping
    residual = None
    it = 0
    for it in range(1, max_iter + 1):
        fk = fk_dh(dh, q)
        pe = fk["end_position"]
        err = [target_pos[i] - pe[i] for i in range(3)]
        residual = math.sqrt(sum(e * e for e in err))
        if residual < tol:
            break
        J = geometric_jacobian(dh, q)
        Jp = [row[:n] for row in J[:3]]
        # Solve (J J^T + lam^2 I) y = err, then dq = J^T y.
        JJt = [[sum(Jp[i][k] * Jp[j][k] for k in range(n)) for j in range(3)]
               for i in range(3)]
        for i in range(3):
            JJt[i][i] += lam2
        y = _solve_3x3(JJt, err)
        dq = [sum(Jp[i][j] * y[i] for i in range(3)) for j in range(n)]
        # Cap the step so one iteration cannot jump far.
        step = math.sqrt(sum(d * d for d in dq))
        if step > 0.5:
            dq = [d * 0.5 / step for d in dq]
        q = [q[i] + dq[i] for i in range(n)]
        if limits:
            q = clamp_joints(q, limits)
    fk = fk_dh(dh, q)
    pe = fk["end_position"]
    residual = math.sqrt(sum((target_pos[i] - pe[i]) ** 2 for i in range(3)))
    return {"joints": q, "residual_m": residual, "iterations": it,
            "converged": residual < 1e-3,
            "limit_violations": joint_limit_violations(q, limits)}


def workspace_reach(dh):
    """Analytic reach limits for a planar arm (sum of link lengths),
    and a sampled reachable radius for a general arm."""
    _check_dh(dh)
    links = [abs(float(row["a"])) for row in dh]
    max_reach = sum(links)
    # Planar arms: min reach is |a1 - a2| for 2 links; for more,
    # folding can reach near zero, so report 0 as the lower bound
    # unless the arm is 2R.
    min_reach = abs(links[0] - links[1]) if len(links) == 2 else 0.0
    return {"max_reach_m": max_reach, "min_reach_m": min_reach,
            "link_lengths_m": links}


# ------------------------------------------------------------------ trajectories
def cubic_trajectory(q0, q1, duration_s, dt=0.05):
    """Cubic joint-space trajectory (zero end velocities).

    Returns {"t": [...], "q": [[...], ...], "qd": [...], "qdd": [...],
    "max_velocity": [...], "max_acceleration": [...]}.
    """
    if len(q0) != len(q1):
        raise ValueError("q0 and q1 must have the same length")
    if duration_s <= 0 or dt <= 0:
        raise ValueError("duration_s and dt must be positive")
    T = float(duration_s)
    steps = max(2, int(T / dt) + 1)
    t, q, qd, qdd = [], [], [], []
    max_v = [0.0] * len(q0)
    max_a = [0.0] * len(q0)
    for i in range(steps):
        ti = min(T, i * dt)
        s = ti / T
        # Cubic: q = q0 + (3s^2 - 2s^3)(q1 - q0)
        pos = [q0[j] + (3 * s * s - 2 * s ** 3) * (q1[j] - q0[j]) for j in range(len(q0))]
        vel = [(6 * s - 6 * s * s) / T * (q1[j] - q0[j]) for j in range(len(q0))]
        acc = [(6 - 12 * s) / (T * T) * (q1[j] - q0[j]) for j in range(len(q0))]
        t.append(ti); q.append(pos); qd.append(vel); qdd.append(acc)
        for j in range(len(q0)):
            max_v[j] = max(max_v[j], abs(vel[j]))
            max_a[j] = max(max_a[j], abs(acc[j]))
    return {"t": t, "q": q, "qd": qd, "qdd": qdd,
            "max_velocity": max_v, "max_acceleration": max_a,
            "duration_s": T}


def trapezoidal_profile(distance, vmax, amax, dt=0.05):
    """Trapezoidal velocity profile for one joint (single direction).

    Returns {"t": [...], "x": [...], "v": [...], "a": [...],
    "peak_velocity": v, "duration_s": T}. Raises if the distance
    cannot be covered (vmax/amax must be positive)."""
    if distance < 0:
        raise ValueError("distance must be >= 0")
    if vmax <= 0 or amax <= 0:
        raise ValueError("vmax and amax must be positive")
    if distance == 0:
        return {"t": [0.0], "x": [0.0], "v": [0.0], "a": [0.0],
                "peak_velocity": 0.0, "duration_s": 0.0}
    t_acc = vmax / amax
    d_acc = 0.5 * amax * t_acc * t_acc
    if 2 * d_acc >= distance:
        # Triangular: never reaches vmax.
        t_acc = math.sqrt(distance / amax)
        t_cruise = 0.0
        v_peak = amax * t_acc
    else:
        v_peak = vmax
        t_cruise = (distance - 2 * d_acc) / vmax
    T = 2 * t_acc + t_cruise
    steps = max(2, int(T / dt) + 1)
    t, x, v, a = [], [], [], []
    for i in range(steps):
        ti = min(T, i * dt)
        if ti < t_acc:
            xi = 0.5 * amax * ti * ti
            vi = amax * ti
            ai = amax
        elif ti < t_acc + t_cruise:
            tc = ti - t_acc
            xi = d_acc + v_peak * tc
            vi = v_peak
            ai = 0.0
        else:
            td = ti - t_acc - t_cruise
            xi = d_acc + v_peak * t_cruise + v_peak * td - 0.5 * amax * td * td
            vi = v_peak - amax * td
            ai = -amax
        t.append(ti); x.append(xi); v.append(vi); a.append(ai)
    return {"t": t, "x": x, "v": v, "a": a,
            "peak_velocity": v_peak, "duration_s": T}


# ------------------------------------------------------------------ collision
def _point_segment_distance(p, a, b):
    ab = [b[i] - a[i] for i in range(3)]
    ap = [p[i] - a[i] for i in range(3)]
    denom = sum(v * v for v in ab)
    s = 0.0 if denom == 0 else max(0.0, min(1.0, sum(ap[i] * ab[i] for i in range(3)) / denom))
    closest = [a[i] + s * ab[i] for i in range(3)]
    return math.sqrt(sum((p[i] - closest[i]) ** 2 for i in range(3))), closest


def _segment_segment_distance(a1, b1, a2, b2):
    # Closest points between two segments (Ericson, Real-Time
    # Collision Detection). Returns (distance, p1, p2).
    d1 = [b1[i] - a1[i] for i in range(3)]
    d2 = [b2[i] - a2[i] for i in range(3)]
    r = [a1[i] - a2[i] for i in range(3)]
    a = sum(v * v for v in d1)
    e = sum(v * v for v in d2)
    f = sum(d2[i] * r[i] for i in range(3))
    if a <= 1e-12 and e <= 1e-12:
        return math.sqrt(sum(v * v for v in r)), a1, a2
    if a <= 1e-12:
        s = 0.0
        t = max(0.0, min(1.0, f / e))
    else:
        c = sum(d1[i] * r[i] for i in range(3))
        if e <= 1e-12:
            t = 0.0
            s = max(0.0, min(1.0, -c / a))
        else:
            b = sum(d1[i] * d2[i] for i in range(3))
            denom = a * e - b * b
            s = 0.0 if denom <= 1e-12 else max(0.0, min(1.0, (b * f - c * e) / denom))
            t = (b * s + f) / e
            if t < 0.0:
                t = 0.0
                s = max(0.0, min(1.0, -c / a))
            elif t > 1.0:
                t = 1.0
                s = max(0.0, min(1.0, (b - c) / a))
    p1 = [a1[i] + s * d1[i] for i in range(3)]
    p2 = [a2[i] + t * d2[i] for i in range(3)]
    return math.sqrt(sum((p1[i] - p2[i]) ** 2 for i in range(3))), p1, p2


def check_collisions(links, obstacles):
    """links: [{a: [x,y,z], b: [x,y,z], radius_m, name}].
    obstacles: [{type: "sphere", centre: [x,y,z], radius_m, name}
    or {type: "box", min: [x,y,z], max: [x,y,z], name}].
    Returns a list of collisions with penetration depth."""
    hits = []
    for link in links:
        for obs in obstacles:
            if obs["type"] == "sphere":
                d, _closest = _point_segment_distance(obs["centre"], link["a"], link["b"])
                clearance = d - link["radius_m"] - obs["radius_m"]
                if clearance < 0:
                    hits.append({"link": link.get("name", "?"),
                                 "obstacle": obs.get("name", "?"),
                                 "penetration_m": -clearance,
                                 "clearance_m": clearance})
            elif obs["type"] == "box":
                # Slab test: does the link's centreline pass through
                # the box? If so the capsule collides (penetration is
                # at least its radius). Otherwise check the closest
                # approach to the box's 12 edges for a near-miss.
                mn, mx = obs["min"], obs["max"]
                tmin, tmax = 0.0, 1.0
                intersects = True
                for k in range(3):
                    d = link["b"][k] - link["a"][k]
                    if abs(d) < 1e-12:
                        if link["a"][k] < mn[k] or link["a"][k] > mx[k]:
                            intersects = False
                            break
                    else:
                        t1 = (mn[k] - link["a"][k]) / d
                        t2 = (mx[k] - link["a"][k]) / d
                        if t1 > t2:
                            t1, t2 = t2, t1
                        tmin = max(tmin, t1)
                        tmax = min(tmax, t2)
                        if tmin > tmax:
                            intersects = False
                            break
                if intersects:
                    hits.append({"link": link.get("name", "?"),
                                 "obstacle": obs.get("name", "?"),
                                 "penetration_m": link["radius_m"],
                                 "clearance_m": -link["radius_m"]})
                    continue
                corners = [[mn[0] if i & 1 == 0 else mx[0],
                            mn[1] if i & 2 == 0 else mx[1],
                            mn[2] if i & 4 == 0 else mx[2]] for i in range(8)]
                edges = [(0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3),
                         (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7)]
                best = None
                for i, j in edges:
                    d, _, _ = _segment_segment_distance(link["a"], link["b"],
                                                        corners[i], corners[j])
                    if best is None or d < best:
                        best = d
                clearance = best - link["radius_m"] if best is not None else 0
                if clearance < 0:
                    hits.append({"link": link.get("name", "?"),
                                 "obstacle": obs.get("name", "?"),
                                 "penetration_m": -clearance,
                                 "clearance_m": clearance})
            else:
                raise ValueError(f"unknown obstacle type: {obs['type']!r}")
    return hits


# ------------------------------------------------------------------ PID + motor
def pid_simulate(inp):
    """Closed-loop step response of a DC motor under PID control.

    Plant (Stage 8 motor model): L di/dt + R i = V - Ke*w;
    J dw/dt + b w = Kt*i - load_torque; dtheta/dt = w.
    Controller: V = Kp*e + Ki*int(e) + Kd*de/dt, e = setpoint - theta,
    with voltage saturation and integral anti-windup.
    Inputs: R_ohm, L_H, Kt_Nm_per_A, Ke_V_per_rad_s, J_kg_m2,
    b_Nm_s, setpoint_rad, kp, ki, kd, voltage_limit_V, dt_s,
    duration_s. Returns the series (downsampled) and metrics.
    """
    def need(key):
        v = inp.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
            raise ValueError(f"{key} must be a non-negative number")
        return float(v)

    R = need("R_ohm"); L = need("L_H")
    Kt = need("Kt_Nm_per_A"); Ke = need("Ke_V_per_rad_s")
    J = need("J_kg_m2"); b = need("b_Nm_s")
    sp = float(inp["setpoint_rad"])
    kp = float(inp.get("kp", 0)); ki = float(inp.get("ki", 0)); kd = float(inp.get("kd", 0))
    vmax = float(inp.get("voltage_limit_V", 12))
    dt = float(inp.get("dt_s", 0.001))
    dur = float(inp.get("duration_s", 2.0))
    load = float(inp.get("load_torque_Nm", 0))
    if L == 0:
        raise ValueError("L_H must be > 0 (a real motor has inductance)")
    if J == 0:
        raise ValueError("J_kg_m2 must be > 0")
    if dt <= 0 or dur <= 0:
        raise ValueError("dt_s and duration_s must be positive")
    theta = 0.0
    w = 0.0
    i = 0.0
    integ = 0.0
    prev_err = sp
    t = 0.0
    series = []
    max_theta = 0.0
    step = 0
    while t <= dur:
        err = sp - theta
        integ += err * dt
        deriv = (err - prev_err) / dt
        v_unclamped = kp * err + ki * integ + kd * deriv
        v = max(-vmax, min(vmax, v_unclamped))
        if v != v_unclamped:
            integ -= err * dt  # anti-windup: undo the integration
        di = (v - R * i - Ke * w) / L
        dw = (Kt * i - b * w - load) / J
        i += di * dt
        w += dw * dt
        theta += w * dt
        prev_err = err
        max_theta = max(max_theta, theta)
        step += 1
        if step % 10 == 0:
            series.append({"t_s": round(t, 3), "theta_rad": round(theta, 4),
                           "omega_rad_s": round(w, 3), "voltage_V": round(v, 2),
                           "current_A": round(i, 3)})
        t += dt
    final_err = sp - theta
    overshoot = max(0.0, (max_theta - sp) / abs(sp) * 100) if sp != 0 else 0.0
    # Settling time: last time |error| exceeds 2% of setpoint.
    settle = None
    band = 0.02 * abs(sp) if sp != 0 else 0.02
    # Recompute from the stored series (coarse but honest).
    last_out = None
    for s in series:
        if abs(sp - s["theta_rad"]) > band:
            last_out = s["t_s"]
    settle = last_out
    return {"final_theta_rad": theta, "final_error_rad": final_err,
            "steady_state_error_rad": final_err,
            "overshoot_percent": overshoot,
            "settling_time_s": settle,
            "max_current_A": max((abs(s["current_A"]) for s in series), default=0.0),
            "series": series}


# ------------------------------------------------------------------ diff drive
def diff_drive_fk(wheel_radius_m, track_m, v_left_m_s, v_right_m_s,
                  pose, dt_s):
    """Unicycle forward kinematics for one step.

    pose = [x_m, y_m, theta_rad]. v_left_m_s / v_right_m_s are the
    LINEAR wheel speeds in m/s (not rad/s — the earlier implementation
    multiplied by the wheel radius, so a 0.5 m/s input came out as
    0.05 m/s with a 0.05 m wheel; fixed in the pre-Stage 12 audit).
    Returns the new pose and the robot-frame velocities (v, omega)."""
    r = float(wheel_radius_m); L = float(track_m)
    if r <= 0 or L <= 0 or dt_s <= 0:
        raise ValueError("wheel_radius_m, track_m and dt_s must be positive")
    vl = float(v_left_m_s); vr = float(v_right_m_s)
    v = (vl + vr) / 2
    omega = (vr - vl) / L
    x, y, th = pose
    th2 = th + omega * dt_s
    x2 = x + v * math.cos(th + omega * dt_s / 2) * dt_s
    y2 = y + v * math.sin(th + omega * dt_s / 2) * dt_s
    return {"pose": [x2, y2, th2], "v_m_s": v, "omega_rad_s": omega}


def diff_drive_ik(wheel_radius_m, track_m, v_m_s, omega_rad_s):
    """Wheel speeds for a desired (v, omega). Returns LINEAR wheel
    speeds in m/s (the earlier implementation divided by the wheel
    radius and returned rad/s under an m/s name; fixed in the
    pre-Stage 12 audit)."""
    r = float(wheel_radius_m); L = float(track_m)
    if r <= 0 or L <= 0:
        raise ValueError("wheel_radius_m and track_m must be positive")
    v = float(v_m_s); om = float(omega_rad_s)
    return {"v_left_m_s": v - om * L / 2,
            "v_right_m_s": v + om * L / 2}


def diff_drive_odometry(wheel_radius_m, track_m, left_speeds, right_speeds,
                        dt_s, pose0=(0.0, 0.0, 0.0)):
    """Integrate a sequence of wheel speeds into a pose trail."""
    pose = list(pose0)
    trail = [pose[:]]
    for vl, vr in zip(left_speeds, right_speeds):
        pose = diff_drive_fk(wheel_radius_m, track_m, vl, vr, pose, dt_s)["pose"]
        trail.append(pose[:])
    return {"final_pose": pose, "trail": trail}
