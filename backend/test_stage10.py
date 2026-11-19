"""Stage 10 tests — aerospace + robotics modules, analytical solvers,
demo projects, and the aerospace/robotics API (including cross-lab
integration with Stages 8 and 9).

Stdlib only. Real backend on a temporary database, real HTTP.
Results are checked against hand-computed reference values.

Run:  cd backend && python3 test_stage10.py
Exit code 0 = all tests passed.
"""
import json
import math
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aerospace as aeromod  # noqa: E402
import app as appmod  # noqa: E402
import db as dbmod  # noqa: E402
import robotics as robotmod  # noqa: E402
import solvers as solversmod  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))


def req(base, method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def approx(a, b, rel=0.01):
    return a is not None and abs(a - b) <= rel * abs(b)


def abs_ok(a, b, tol):
    return a is not None and abs(a - b) <= tol


AIRCRAFT = {
    "mass_kg": 10, "wing_area_m2": 1, "span_m": 2.828, "oswald_e": 0.8,
    "cd0": 0.02, "k": 0.05, "cl_max": 1.4, "cruise_speed_m_s": 20,
    "battery_energy_Wh": 500,
    "components": [
        {"name": "wing", "mass_kg": 3, "x_m": 0.5},
        {"name": "fuselage", "mass_kg": 4, "x_m": 0.6},
        {"name": "tail", "mass_kg": 1, "x_m": 1.4},
        {"name": "battery", "mass_kg": 2, "x_m": 0.3},
    ],
    "mac_m": 0.35, "x_ac_wing_m": 0.55, "tail_volume": 0.5,
}
DH2 = [{"a": 1, "alpha": 0, "d": 0, "theta": 0, "type": "revolute"},
       {"a": 1, "alpha": 0, "d": 0, "theta": 0, "type": "revolute"}]
DH4 = [{"a": 0, "alpha": math.pi / 2, "d": 0.15, "theta": 0, "type": "revolute"},
       {"a": 0.4, "alpha": 0, "d": 0, "theta": 0, "type": "revolute"},
       {"a": 0.35, "alpha": 0, "d": 0, "theta": 0, "type": "revolute"},
       {"a": 0.15, "alpha": 0, "d": 0, "theta": 0, "type": "revolute"}]
MOTOR = {"R_ohm": 1.5, "L_H": 0.001, "Kt_Nm_per_A": 0.05,
         "Ke_V_per_rad_s": 0.05, "J_kg_m2": 0.01, "b_Nm_s": 0.001}


def main():
    tmp = tempfile.mkdtemp(prefix="aielab-stage10-test-")
    os.environ["AIELAB_DB"] = os.path.join(tmp, "test.db")
    os.environ["AIELAB_SECRET"] = "test-secret-for-stage10-only"
    conn = dbmod.connect(os.environ["AIELAB_DB"])
    dbmod.init_db(conn)
    dbmod.seed_materials(conn)
    conn.close()

    # ---------- aerospace module ----------
    check("ISA density at sea level is 1.225",
          approx(aeromod.isa_density(0), 1.225, 0.001))
    check("ISA density at 5000 m is 0.736",
          approx(aeromod.isa_density(5000), 0.736, 0.01))
    try:
        aeromod.isa_density(20000)
        check("ISA density rejects 20000 m", False)
    except ValueError:
        check("ISA density rejects 20000 m", True)

    check("NACA 2412 zero-lift angle is -2.1 deg (published)",
          abs(aeromod.alpha0_deg("naca2412") + 2.1) < 0.05)
    check("NACA 0012 zero-lift angle is 0 (symmetric)",
          abs(aeromod.alpha0_deg("naca0012")) < 0.01)
    ords = aeromod.naca4_ordinates("naca2412")
    check("NACA 2412 max thickness is 0.12 chord",
          approx(max(ords["yt"]) * 2, 0.12, 0.01))
    c = aeromod.airfoil_coefficients("naca2412", 0)
    check("NACA 2412 Cl at 0 deg is 0.23", approx(c["cl"], 0.23, 0.02))
    c = aeromod.airfoil_coefficients("naca2412", 5)
    check("NACA 2412 Cl at 5 deg is 0.78", approx(c["cl"], 0.779, 0.01))
    check("NACA 2412 Cd at 5 deg is 0.033", approx(c["cd"], 0.033, 0.02))
    check("NACA 2412 not stalled at 5 deg", c["stalled"] is False)
    c = aeromod.airfoil_coefficients("naca2412", 20)
    check("NACA 2412 stalled at 20 deg", c["stalled"] is True)
    try:
        aeromod.airfoil_coefficients("naca9999", 5)
        check("unknown airfoil without Cd0 raises", False)
    except ValueError as e:
        check("unknown airfoil without Cd0 raises", "Cd0" in str(e), str(e)[:60])

    w = aeromod.wing_coefficients(0.5, 5, 8, 0.8, airfoil_cd=0.01)
    check("finite wing Cl 0.381", approx(w["cl"], 0.381, 0.01))
    check("finite wing Cdi 0.0072", approx(w["cdi"], 0.0072, 0.01))
    check("finite wing Cd 0.0172", approx(w["cd"], 0.0172, 0.01))

    perf = aeromod.aircraft_performance(AIRCRAFT)
    check("aircraft stall speed 10.69 m/s", approx(perf["stall_speed_m_s"], 10.69, 0.01))
    check("aircraft L/D 11.12", approx(perf["lift_to_drag"], 11.12, 0.01))
    check("aircraft power required 176.3 W", approx(perf["power_required_W"], 176.3, 0.01))
    check("aircraft endurance 1.69 h", approx(perf["endurance_h"], 1.69, 0.02))
    check("aircraft CG 0.59 m", approx(perf["cg_x_m"], 0.59, 0.01))
    check("aircraft static margin 0.286", approx(perf["static_margin"], 0.286, 0.02))
    check("aircraft is statically stable", perf["statically_stable"] is True)
    bad = dict(AIRCRAFT, cruise_speed_m_s=5)
    try:
        aeromod.aircraft_performance(bad)
        check("cruise Cl above Clmax raises", False)
    except ValueError as e:
        check("cruise Cl above Clmax raises", "Clmax" in str(e), str(e)[:60])
    bad = dict(AIRCRAFT)
    bad["components"] = [{"name": "wing", "mass_kg": 1, "x_m": 0.5}]
    try:
        aeromod.aircraft_performance(bad)
        check("component masses must sum to mass_kg", False)
    except ValueError:
        check("component masses must sum to mass_kg", True)

    mr = aeromod.multirotor_hover({"mass_kg": 2, "n_rotors": 4,
                                   "rotor_diameter_m": 0.25, "battery_energy_Wh": 100})
    check("quad thrust per rotor 4.9 N", approx(mr["thrust_per_rotor_N"], 4.9, 0.01))
    check("quad hover power 178.9 W", approx(mr["hover_power_W"], 178.9, 0.01))
    check("quad hover endurance 28.5 min", approx(mr["hover_endurance_min"], 28.5, 0.02))

    r = aeromod.rocket_delta_v([{"isp_s": 300, "m0_kg": 1000, "mf_kg": 200}])
    check("single-stage delta-v 4735 m/s", approx(r["total_delta_v_m_s"], 4735, 0.001))
    r = aeromod.rocket_delta_v([{"isp_s": 300, "m0_kg": 1000, "mf_kg": 300},
                                {"isp_s": 320, "m0_kg": 300, "mf_kg": 100}])
    check("two-stage delta-v 6990 m/s", approx(r["total_delta_v_m_s"], 6990, 0.001))
    check("two-stage propellant 700 + 200 kg",
          r["stages"][0]["propellant_kg"] == 700 and r["stages"][1]["propellant_kg"] == 200)
    try:
        aeromod.rocket_delta_v([{"isp_s": 300, "m0_kg": 100, "mf_kg": 100}])
        check("stage with mf >= m0 raises", False)
    except ValueError:
        check("stage with mf >= m0 raises", True)
    th = aeromod.rocket_thrust({"mdot_kg_s": 10, "isp_s": 300})
    check("rocket thrust 29420 N", approx(th["thrust_N"], 29420, 0.001))
    check("rocket effective Isp 300 s", approx(th["effective_isp_s"], 300, 0.001))

    rocket_parts = [
        {"type": "nose", "shape": "conical", "length_m": 0.3, "diameter_m": 0.1, "x_base_m": 0.3},
        {"type": "fins", "n": 4, "root_chord_m": 0.15, "tip_chord_m": 0.07,
         "span_m": 0.08, "x_leading_m": 0.85, "body_diameter_m": 0.1},
    ]
    cp = aeromod.barrowman_cp(rocket_parts)
    check("Barrowman CP 0.636 m", approx(cp["cp_x_m"], 0.636, 0.01))
    check("Barrowman total Cn 6.24", approx(cp["total_cn_alpha"], 6.24, 0.01))
    st = aeromod.rocket_stability(rocket_parts, 0.55, 0.1)
    check("rocket stability 0.86 calibres", approx(st["stability_calibres"], 0.86, 0.02))
    check("rocket is stable (CP behind CG)", st["stable"] is True)
    check("rocket margin outside the 1.0-2.5 band is flagged", st["margin_ok"] is False)

    tr = aeromod.trajectory_2d({"mass_kg": 100, "diameter_m": 0.1, "cd": 0.0,
                                "launch_angle_deg": 90,
                                "thrust_profile": [{"t_start_s": 0, "t_end_s": 10,
                                                    "thrust_N": 2 * 100 * 9.80665,
                                                    "mdot_kg_s": 0}],
                                "dt_s": 0.05, "t_max_s": 60})
    check("trajectory apogee 980 m (no-drag analytic)",
          approx(tr["apogee_m"], 980, 0.01), str(tr["apogee_m"]))
    check("trajectory range is 0 for a vertical launch", abs(tr["range_m"]) < 1e-6)

    cg = aeromod.centre_of_gravity([{"name": "a", "mass_kg": 3, "x_m": 0.5},
                                    {"name": "b", "mass_kg": 1, "x_m": 1.4}])
    check("centre of gravity 0.725 m", approx(cg["cg"]["x_m"], 0.725, 0.001))

    # ---------- robotics module ----------
    fk = robotmod.fk_dh(DH2, [0, 0])
    check("FK 2R [0,0] -> (2,0,0)", fk["end_position"] == [2.0, 0.0, 0.0], str(fk["end_position"]))
    fk = robotmod.fk_dh(DH2, [math.pi / 2, 0])
    check("FK 2R [90,0] -> (0,2,0)",
          abs_ok(fk["end_position"][0], 0, 1e-9) and abs_ok(fk["end_position"][1], 2, 1e-9))
    fk = robotmod.fk_dh(DH2, [math.pi / 2, math.pi / 2])
    check("FK 2R [90,90] -> (-1,1,0)",
          abs_ok(fk["end_position"][0], -1, 1e-9) and abs_ok(fk["end_position"][1], 1, 1e-9))
    ik = robotmod.ik_2r(1, 1, [1, 1], elbow="up")
    check("IK 2R (1,1) elbow up is [0,90] deg",
          abs_ok(ik["joints"][0], 0, 1e-9) and abs_ok(ik["joints"][1], math.pi / 2, 1e-9))
    ik = robotmod.ik_2r(1, 1, [1, 1], elbow="down")
    check("IK 2R (1,1) elbow down is [90,-90] deg",
          abs_ok(ik["joints"][0], math.pi / 2, 1e-9) and abs_ok(ik["joints"][1], -math.pi / 2, 1e-9))
    try:
        robotmod.ik_2r(1, 1, [3, 0])
        check("IK 2R unreachable target raises", False)
    except ValueError as e:
        check("IK 2R unreachable target raises", "outside the 2R workspace" in str(e))
    sol = robotmod.ik_3r(1, 1, 0.5, [1.5, 0.5], 0)
    dh3 = DH2 + [{"a": 0.5, "alpha": 0, "d": 0, "theta": 0, "type": "revolute"}]
    fk = robotmod.fk_dh(dh3, sol["joints"])
    check("IK 3R round-trips through FK to (1.5,0.5)",
          abs_ok(fk["end_position"][0], 1.5, 1e-9) and abs_ok(fk["end_position"][1], 0.5, 1e-9))
    dh6 = [{"a": 0.5, "alpha": math.pi / 2, "d": 0.2, "theta": 0},
           {"a": 0.5, "alpha": 0, "d": 0, "theta": 0},
           {"a": 0.3, "alpha": 0, "d": 0, "theta": 0}]
    res = robotmod.ik_dls(dh6, [0.8, 0.4, 0.5], [0.3, 0.3, 0.3])
    check("DLS IK converges (residual < 1e-3)", res["converged"] and res["residual_m"] < 1e-3,
          str(res["residual_m"]))
    fk = robotmod.fk_dh(dh6, res["joints"])
    check("DLS IK FK matches the target",
          abs_ok(fk["end_position"][0], 0.8, 1e-3) and abs_ok(fk["end_position"][2], 0.5, 1e-3))
    check("joint limit violation is reported",
          len(robotmod.joint_limit_violations([0, 3.5, -1], [(-3, 3), (-3, 3), (-3, 3)])) == 1)
    check("clamp_joints clamps to the limits",
          robotmod.clamp_joints([0, 3.5, -4], [(-3, 3), (-3, 3), (-3, 3)]) == [0, 3, -3])
    check("2R workspace reach is 0-2 m",
          robotmod.workspace_reach(DH2)["max_reach_m"] == 2.0)

    trj = robotmod.cubic_trajectory([0, 0], [1, -0.5], 2.0, dt=0.1)
    check("cubic trajectory ends at q1",
          abs_ok(trj["q"][-1][0], 1, 1e-9) and abs_ok(trj["q"][-1][1], -0.5, 1e-9))
    check("cubic max velocity is 1.5*d/T",
          approx(trj["max_velocity"][0], 0.75, 0.001) and approx(trj["max_velocity"][1], 0.375, 0.001))
    check("cubic max acceleration is 6*d/T^2",
          approx(trj["max_acceleration"][0], 1.5, 0.001) and approx(trj["max_acceleration"][1], 0.75, 0.001))
    tp = robotmod.trapezoidal_profile(2, 1, 1, dt=0.05)
    check("trapezoidal T is 3 s", approx(tp["duration_s"], 3.0, 0.01))
    check("trapezoidal final x is 2 m", approx(tp["x"][-1], 2.0, 0.001))
    tp = robotmod.trapezoidal_profile(0.1, 1, 1, dt=0.01)
    check("short move is triangular (never reaches vmax)",
          tp["peak_velocity"] < 1.0, str(tp["peak_velocity"]))

    hits = robotmod.check_collisions(
        [{"a": [0, 0, 0], "b": [1, 0, 0], "radius_m": 0.05, "name": "link1"}],
        [{"type": "sphere", "centre": [0.5, 0.12, 0], "radius_m": 0.1, "name": "obs"}])
    check("capsule-sphere collision detected, penetration 0.03 m",
          len(hits) == 1 and approx(hits[0]["penetration_m"], 0.03, 0.01), str(hits))
    hits = robotmod.check_collisions(
        [{"a": [0, 0, 0], "b": [1, 0, 0], "radius_m": 0.05, "name": "link1"}],
        [{"type": "sphere", "centre": [0.5, 0.5, 0], "radius_m": 0.1, "name": "obs"}])
    check("far obstacle gives no collision", hits == [])
    hits = robotmod.check_collisions(
        [{"a": [0, 0, 0], "b": [1, 0, 0], "radius_m": 0.05, "name": "link1"}],
        [{"type": "box", "min": [0.4, -0.1, -0.1], "max": [0.6, 0.1, 0.1], "name": "box"}])
    check("capsule-box collision detected", len(hits) == 1, str(hits))

    pid = robotmod.pid_simulate({**MOTOR, "setpoint_rad": 1.0, "kp": 2, "ki": 0.5,
                                 "kd": 1.5, "voltage_limit_V": 12, "dt_s": 0.001,
                                 "duration_s": 5.0})
    check("PID overshoot below 20%", pid["overshoot_percent"] < 20, str(pid["overshoot_percent"]))
    check("PID final error below 0.1 rad", abs(pid["final_error_rad"]) < 0.1, str(pid["final_error_rad"]))
    pid_p = robotmod.pid_simulate({**MOTOR, "setpoint_rad": 1.0, "kp": 2, "ki": 0, "kd": 1.5,
                                   "voltage_limit_V": 12, "dt_s": 0.001, "duration_s": 8.0,
                                   "load_torque_Nm": 0.05})
    check("P-only + load: steady-state error 0.75 rad (R*T/(Kt*Kp))",
          approx(pid_p["final_error_rad"], 0.75, 0.05), str(pid_p["final_error_rad"]))
    pid_pi = robotmod.pid_simulate({**MOTOR, "setpoint_rad": 1.0, "kp": 2, "ki": 0.5,
                                    "kd": 1.5, "voltage_limit_V": 12, "dt_s": 0.001,
                                    "duration_s": 8.0, "load_torque_Nm": 0.05})
    check("PI + load: error nearly removed (< 0.1 rad)",
          abs(pid_pi["final_error_rad"]) < 0.1, str(pid_pi["final_error_rad"]))
    check("PI error is much smaller than P-only error",
          abs(pid_pi["final_error_rad"]) < abs(pid_p["final_error_rad"]))

    dd = robotmod.diff_drive_fk(0.05, 0.3, 10, 10, [0, 0, 0], 1.0)
    check("diff-drive straight: 0.5 m in 1 s",
          abs_ok(dd["pose"][0], 0.5, 1e-9) and abs_ok(dd["pose"][1], 0, 1e-9))
    dd = robotmod.diff_drive_fk(0.05, 0.3, -3, 3, [0, 0, 0], 1.0)
    check("diff-drive turn in place: 1 rad/s",
          approx(dd["omega_rad_s"], 1.0, 0.001) and abs_ok(dd["v_m_s"], 0, 1e-9))
    ik_dd = robotmod.diff_drive_ik(0.05, 0.3, 0.5, 0)
    check("diff-drive IK: 0.5 m/s needs 10 rad/s each",
          approx(ik_dd["v_left_m_s"], 10, 0.001) and approx(ik_dd["v_right_m_s"], 10, 0.001))
    odo = robotmod.diff_drive_odometry(0.05, 0.3, [10, 10, 10], [10, 10, 10], 1.0)
    check("odometry straight 3 s: x = 1.5 m",
          abs_ok(odo["final_pose"][0], 1.5, 1e-9), str(odo["final_pose"]))

    # ---------- solvers via run_solver ----------
    check("solver airfoil_lift: Cl 0.78 at 5 deg",
          approx(solversmod.run_solver("airfoil_lift", {"airfoil_code": "naca2412", "alpha_deg": 5}, {})["cl"], 0.779, 0.01))
    check("solver stall_speed: 10.69 m/s",
          approx(solversmod.run_solver("stall_speed", {"mass_kg": 10, "wing_area_m2": 1, "cl_max": 1.4}, {})["stall_speed_m_s"], 10.69, 0.01))
    check("solver rocket_delta_v: 4735 m/s",
          approx(solversmod.run_solver("rocket_delta_v", {"stages": [{"isp_s": 300, "m0_kg": 1000, "mf_kg": 200}]}, {})["total_delta_v_m_s"], 4735, 0.001))
    check("solver ik_2r: (1,1) down is [90,-90] deg",
          abs_ok(solversmod.run_solver("ik_2r", {"l1": 1, "l2": 1, "target": [1, 1]}, {})["joints"][0], math.pi / 2, 1e-9))
    check("solver forward_kinematics: (2,0,0)",
          solversmod.run_solver("forward_kinematics", {"dh": DH2, "joints": [0, 0]}, {})["end_position"] == [2.0, 0.0, 0.0])
    check("solver collision_check finds 1 hit",
          solversmod.run_solver("collision_check", {"links": [{"a": [0, 0, 0], "b": [1, 0, 0], "radius_m": 0.05}],
                                                    "obstacles": [{"type": "sphere", "centre": [0.5, 0.12, 0], "radius_m": 0.1}]}, {})["n_collisions"] == 1)
    check("solver diff_drive_fk: 0.5 m",
          abs_ok(solversmod.run_solver("diff_drive_fk", {"wheel_radius_m": 0.05, "track_m": 0.3, "v_left_m_s": 10, "v_right_m_s": 10, "pose": [0, 0, 0], "dt_s": 1.0}, {})["pose"][0], 0.5, 1e-9))
    pid = solversmod.run_solver("pid_control", {**MOTOR, "setpoint_rad": 1.0, "kp": 2, "ki": 0.5, "kd": 1.5, "voltage_limit_V": 12, "dt_s": 0.001, "duration_s": 5.0}, {})
    check("solver pid_control: overshoot below 20%", pid["overshoot_percent"] < 20)
    try:
        solversmod.run_solver("aero_aircraft", {}, {})
        check("aero_aircraft refuses the scalar endpoint", False)
    except ValueError as e:
        check("aero_aircraft refuses the scalar endpoint", "aerospace/analyze" in str(e))
    try:
        solversmod.run_solver("robot_arm", {}, {})
        check("robot_arm refuses the scalar endpoint", False)
    except ValueError as e:
        check("robot_arm refuses the scalar endpoint", "robotics/analyze" in str(e))
    reg = solversmod.SOLVER_REGISTRY
    check("registry lists the Stage 10 solvers",
          all(k in reg for k in ("airfoil_lift", "rocket_delta_v", "ik_dls",
                                 "pid_control", "aero_aircraft", "robot_arm",
                                 "aero_multirotor", "robot_control")))

    # ---------- demo files ----------
    demo_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                            "workspace", "test-aerospace")
    robot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                             "workspace", "test-robots")
    fw = json.load(open(os.path.join(demo_dir, "fixed_wing_aircraft.json")))
    exp = fw.pop("expected"); fw.pop("name")
    perf = aeromod.aircraft_performance(fw)
    check("demo fixed-wing: stall speed matches expected",
          approx(perf["stall_speed_m_s"], exp["stall_speed_m_s"], 0.01))
    check("demo fixed-wing: L/D matches expected",
          approx(perf["lift_to_drag"], exp["lift_to_drag"], 0.01))
    check("demo fixed-wing: statically stable", perf["statically_stable"] is True)
    mr = json.load(open(os.path.join(demo_dir, "multirotor_drone.json")))
    exp = mr.pop("expected"); mr.pop("name")
    hov = aeromod.multirotor_hover(mr)
    check("demo quad: hover power matches expected",
          approx(hov["hover_power_W"], exp["hover_power_W"], 0.01))
    check("demo quad: endurance matches expected",
          approx(hov["hover_endurance_min"], exp["hover_endurance_min"], 0.02))
    rk = json.load(open(os.path.join(demo_dir, "multistage_rocket.json")))
    exp = rk.pop("expected"); rk.pop("name")
    dv = aeromod.rocket_delta_v(rk["stages"])
    check("demo rocket: delta-v matches expected",
          approx(dv["total_delta_v_m_s"], exp["total_delta_v_m_s"], 0.001))
    st = aeromod.rocket_stability(rk["stability"]["components"],
                                  rk["stability"]["cg_x_m"], rk["stability"]["diameter_m"])
    check("demo rocket: CP matches expected", approx(st["cp_x_m"], exp["cp_x_m"], 0.01))
    check("demo rocket: stable", st["stable"] is True)
    tr = aeromod.trajectory_2d(rk["trajectory"])
    check("demo rocket: apogee above 5000 m", tr["apogee_m"] > exp["apogee_above_m"],
          str(round(tr["apogee_m"])))
    arm = json.load(open(os.path.join(robot_dir, "robot_arm.json")))
    exp = arm.pop("expected"); arm.pop("name")
    fk = robotmod.fk_dh(arm["dh"], arm["joints"])
    check("demo arm: FK matches expected",
          all(abs_ok(a, b, 0.01) for a, b in zip(fk["end_position"], exp["fk_end_position"])),
          str([round(v, 3) for v in fk["end_position"]]))
    ik = robotmod.ik_dls(arm["dh"], arm["target_pos"], arm["joints"], limits=arm["limits"])
    check("demo arm: IK converges", ik["converged"] is True and ik["residual_m"] < 1e-3)
    wr = json.load(open(os.path.join(robot_dir, "wheeled_robot.json")))
    st_test = wr["straight_test"]
    dd = robotmod.diff_drive_fk(wr["wheel_radius_m"], wr["track_m"],
                                st_test["v_left_m_s"], st_test["v_right_m_s"],
                                [0, 0, 0], st_test["dt_s"])
    check("demo wheeled robot: straight pose matches expected",
          all(abs_ok(a, b, 1e-9) for a, b in zip(dd["pose"], st_test["expected_pose"])))
    asm = json.load(open(os.path.join(robot_dir, "robot_assembly.json")))
    exp = asm.pop("expected"); asm.pop("name"); asm.pop("sensors")
    ik = robotmod.ik_dls(asm["dh"], asm["target_pos"], asm["joints"], limits=asm["limits"])
    check("demo assembly: IK converges", ik["converged"] is True)
    pid = robotmod.pid_simulate(asm["pid"])
    check("demo assembly: PID overshoot below 20%",
          pid["overshoot_percent"] < exp["pid_overshoot_below_percent"],
          str(round(pid["overshoot_percent"], 1)))

    # ---------- API ----------
    server = ThreadingHTTPServer(("127.0.0.1", 0), appmod.Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        status, body = req(base, "GET", "/health")
        check("health reports stage 11", body.get("stage") == 11, str(body))
        status, body = req(base, "POST", "/api/v1/auth/register",
                           body={"email": "alice@example.com", "username": "alice",
                                 "password": "correct-horse-battery", "name": "Alice"})
        check("register Alice", status == 201, str(status))
        alice = body["token"]
        status, body = req(base, "POST", "/api/v1/auth/register",
                           body={"email": "bob@example.com", "username": "bob",
                                 "password": "correct-horse-battery", "name": "Bob"})
        bob = body["token"]
        status, body = req(base, "POST", "/api/v1/projects", alice,
                           body={"name": "Aero demo", "description": "", "lab": "aerospace"})
        check("create aerospace project", status == 201, str(status))
        pid = body["project"]["id"]
        status, body = req(base, "GET", "/api/v1/aerospace/schema")
        check("aerospace schema lists analyses",
              status == 200 and "aircraft" in body.get("schema", {}).get("analyses", []), str(status))
        status, body = req(base, "GET", "/api/v1/robotics/schema")
        check("robotics schema lists analyses",
              status == 200 and "ik" in body.get("schema", {}).get("analyses", []), str(status))
        status, body = req(base, "POST", "/api/v1/aerospace/validate", alice,
                           body={"design": {"kind": "aircraft"}})
        check("aerospace validate: aircraft is valid",
              status == 200 and body.get("valid") is True, str(body))
        status, body = req(base, "POST", "/api/v1/robotics/validate", alice,
                           body={"design": {"kind": "plane"}})
        check("robotics validate: bad kind is invalid",
              status == 200 and body.get("valid") is False, str(body))

        # Aircraft analysis incl. Stage 9 spar check.
        fw = json.load(open(os.path.join(demo_dir, "fixed_wing_aircraft.json")))
        fw.pop("expected"); fw.pop("name")
        status, body = req(base, "POST", "/api/v1/aerospace/analyze", alice,
                           body={"project_id": pid, "design": fw, "analysis": {"type": "aircraft"}})
        check("aircraft analysis completes via API", status == 201, str(status))
        vals = body["results"]["values"]
        check("API aircraft: stall speed 10.69",
              approx(vals["stall_speed_m_s"], 10.69, 0.01))
        check("API aircraft: spar stress ~8.3 MPa (Stage 9 check)",
              approx(vals["spar_check"]["max_stress_Pa"] / 1e6, 8.3, 0.05),
              str(vals["spar_check"]))
        check("API aircraft: spar utilisation below 0.1",
              vals["spar_check"]["utilization"] < 0.1)
        # Multirotor.
        mr = json.load(open(os.path.join(demo_dir, "multirotor_drone.json")))
        mr.pop("expected"); mr.pop("name")
        status, body = req(base, "POST", "/api/v1/aerospace/analyze", alice,
                           body={"project_id": pid, "design": mr, "analysis": {"type": "multirotor"}})
        check("multirotor analysis completes via API", status == 201, str(status))
        check("API multirotor: hover power 178.9 W",
              approx(body["results"]["values"]["hover_power_W"], 178.9, 0.01))
        # Rocket + trajectory.
        rk = json.load(open(os.path.join(demo_dir, "multistage_rocket.json")))
        rk.pop("expected"); rk.pop("name")
        traj = rk.pop("trajectory")
        status, body = req(base, "POST", "/api/v1/aerospace/analyze", alice,
                           body={"project_id": pid, "design": rk, "analysis": {"type": "rocket"}})
        check("rocket analysis completes via API", status == 201, str(status))
        vals = body["results"]["values"]
        check("API rocket: delta-v 6990 m/s",
              approx(vals["delta_v"]["total_delta_v_m_s"], 6990, 0.001))
        check("API rocket: stability 0.86 calibres",
              approx(vals["stability"]["stability_calibres"], 0.86, 0.02))
        status, body = req(base, "POST", "/api/v1/aerospace/analyze", alice,
                           body={"project_id": pid, "design": traj, "analysis": {"type": "trajectory"}})
        check("trajectory analysis completes via API", status == 201, str(status))
        check("API trajectory: apogee above 5000 m",
              body["results"]["values"]["apogee_m"] > 5000,
              str(round(body["results"]["values"]["apogee_m"])))
        # Invalid aircraft: cruise Cl above Clmax -> failed job.
        bad = dict(fw, cruise_speed_m_s=5)
        status, body = req(base, "POST", "/api/v1/aerospace/analyze", alice,
                           body={"project_id": pid, "design": bad, "analysis": {"type": "aircraft"}})
        check("invalid aircraft is recorded failed",
              status == 200 and body.get("status") == "failed", str(status))
        # Bob cannot analyse Alice's project.
        status, body = req(base, "POST", "/api/v1/aerospace/analyze", bob,
                           body={"project_id": pid, "design": fw, "analysis": {"type": "aircraft"}})
        check("Bob gets 404 on Alice's project", status == 404, str(status))

        # Robot arm analysis incl. Stage 8 motor + Stage 9 link checks.
        arm = json.load(open(os.path.join(robot_dir, "robot_arm.json")))
        arm.pop("expected"); arm.pop("name")
        status, body = req(base, "POST", "/api/v1/robotics/analyze", alice,
                           body={"project_id": pid, "design": arm, "analysis": {"type": "arm"}})
        check("arm analysis completes via API", status == 201, str(status))
        vals = body["results"]["values"]
        check("API arm: FK end matches demo",
              all(abs_ok(a, b, 0.01) for a, b in zip(vals["fk"]["end_position"], [0.797, 0.247, 0.253])),
              str(vals["fk"]["end_position"]))
        check("API arm: IK converged", vals["ik"]["converged"] is True)
        check("API arm: motor check ~2177 rpm (Stage 8)",
              approx(vals["motor_check"]["speed_rpm"], 2177, 0.01),
              str(vals["motor_check"].get("speed_rpm")))
        check("API arm: link checks are below yield (Stage 9)",
              all(l["utilization"] < 1 for l in vals["link_check"]), str(vals["link_check"]))
        check("API arm: no collisions at this pose", vals["collisions"] == [])
        check("API arm: no limit violations", vals["limit_violations"] == [])
        # Control analysis: PID + trajectory.
        asm = json.load(open(os.path.join(robot_dir, "robot_assembly.json")))
        asm.pop("expected"); asm.pop("name"); asm.pop("sensors")
        status, body = req(base, "POST", "/api/v1/robotics/analyze", alice,
                           body={"project_id": pid, "design": asm, "analysis": {"type": "control"}})
        check("control analysis completes via API", status == 201, str(status))
        vals = body["results"]["values"]
        check("API control: PID overshoot below 20%",
              vals["pid"]["overshoot_percent"] < 20)
        check("API control: trajectory ends at q1",
              abs_ok(vals["trajectory"]["q"][-1][0], asm["trajectory"]["q1"][0], 1e-9))
        # Scalar solvers through the simulations endpoint.
        status, body = req(base, "POST", "/api/v1/simulations", alice,
                           body={"project_id": pid, "solver": "airfoil_lift",
                                 "inputs": {"airfoil_code": "naca2412", "alpha_deg": 5}})
        check("airfoil_lift job completes via API", status == 201, str(status))
        check("API airfoil_lift: Cl 0.779",
              approx(body["results"]["values"]["cl"], 0.779, 0.01))
        status, body = req(base, "POST", "/api/v1/simulations", alice,
                           body={"project_id": pid, "solver": "ik_dls",
                                 "inputs": {"dh": DH4, "target_pos": [0.45, 0.35, 0.45],
                                            "q0": [0.3, 0.5, -0.8, 0.4],
                                            "limits": [[-3.14, 3.14], [-2.5, 2.5], [-2.5, 2.5], [-3.14, 3.14]]}})
        check("ik_dls job completes via API", status == 201, str(status))
        check("API ik_dls: converged",
              body["results"]["values"]["converged"] is True)
        status, body = req(base, "POST", "/api/v1/simulations", alice,
                           body={"project_id": pid, "solver": "pid_control",
                                 "inputs": {**MOTOR, "setpoint_rad": 1.0, "kp": 2, "ki": 0.5,
                                            "kd": 1.5, "voltage_limit_V": 12, "dt_s": 0.001,
                                            "duration_s": 5.0}})
        check("pid_control job completes via API", status == 201, str(status))
        status, body = req(base, "POST", "/api/v1/simulations", alice,
                           body={"project_id": pid, "solver": "aero_aircraft", "inputs": {}})
        check("aero_aircraft via simulations is recorded failed with the pointer",
              status == 200 and body.get("status") == "failed"
              and "aerospace/analyze" in str(body.get("results", {})), str(body))
        # Design documents.
        status, body = req(base, "GET", "/api/v1/projects/" + pid + "/aerospace", alice)
        check("aerospace design starts empty (version 1)",
              status == 200 and body["design"]["version"] == 1, str(body))
        status, body = req(base, "PUT", "/api/v1/projects/" + pid + "/aerospace", alice,
                           body={"design": {**fw, "version": 1}, "base_version": 1})
        check("aerospace design saves to version 2",
              status == 200 and body["design"]["version"] == 2, str(body))
        status, body = req(base, "PUT", "/api/v1/projects/" + pid + "/aerospace", alice,
                           body={"design": {**fw, "version": 2}, "base_version": 1})
        check("aerospace design stale base_version is 409", status == 409, str(status))
        status, body = req(base, "PUT", "/api/v1/projects/" + pid + "/aerospace", bob,
                           body={"design": {**fw, "version": 2}, "base_version": 2})
        check("Bob PUT to Alice's aerospace design is 404", status == 404, str(status))
        status, body = req(base, "GET", "/api/v1/projects/" + pid + "/robot", alice)
        check("robot design starts empty (version 1)",
              status == 200 and body["design"]["version"] == 1, str(body))
        status, body = req(base, "PUT", "/api/v1/projects/" + pid + "/robot", alice,
                           body={"design": {**arm, "version": 1}, "base_version": 1})
        check("robot design saves to version 2",
              status == 200 and body["design"]["version"] == 2, str(body))
        status, body = req(base, "GET", "/api/v1/projects/" + pid + "/robot", alice)
        check("robot design round-trips",
              status == 200 and body["design"]["version"] == 2
              and body["design"]["kind"] == "arm", str(body))
        status, body = req(base, "GET", "/api/v1/solvers", alice)
        reg = body.get("solvers", {})
        check("solvers registry lists Stage 10 solvers",
              all(k in reg for k in ("airfoil_lift", "rocket_delta_v", "ik_dls",
                                     "pid_control", "aero_aircraft", "robot_arm")))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("FAILURES:")
        for name, _ok, detail in failed:
            print(f"  - {name} {detail}")
    sys.exit(1 if failed else 0)
