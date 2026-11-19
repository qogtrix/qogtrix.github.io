"""Stage 7 tests — mechanical solvers, new component kinds, demo models.

Stdlib only. Real backend on a temporary database, real HTTP.
Mechanical results are checked against hand-computed reference
values (formulas in docs/MECHANICAL.md).

Run:  cd backend && python3 test_stage7.py
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
import app as appmod  # noqa: E402
import db as dbmod  # noqa: E402
import model as modelmod  # noqa: E402
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
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def approx(a, b, rel=0.002):
    return a is not None and abs(a - b) <= rel * abs(b)


def run_solver(name, solver, inputs, props):
    return solversmod.run_solver(solver, inputs, props)


def main():
    tmp = tempfile.mkdtemp(prefix="aielab-stage7-test-")
    os.environ["AIELAB_DB"] = os.path.join(tmp, "test.db")
    os.environ["AIELAB_SECRET"] = "test-secret-for-stage7-only"
    conn = dbmod.connect(os.environ["AIELAB_DB"])
    dbmod.init_db(conn)
    conn.close()

    # -- material properties for the tests (steel-1045 from Stage 4 data) --
    conn = dbmod.connect(os.environ["AIELAB_DB"])
    dbmod.seed_materials(conn)
    steel = dbmod.fetch_material(conn, "steel-1045")
    conn.close()

    def props_of(mid):
        conn = dbmod.connect(os.environ["AIELAB_DB"])
        m = dbmod.fetch_material(conn, mid)
        conn.close()
        return m["properties"]

    s1045 = props_of("steel-1045")
    # sanity: the material the tests rely on must have what we need
    check("steel-1045 has E/nu/yield/tensile/fatigue/density",
          all(s1045.get(k) is not None for k in
              ("elastic_modulus_gpa", "poisson_ratio", "yield_strength_mpa",
               "tensile_strength_mpa", "fatigue_limit_mpa", "density_kg_m3")),
          str({k: s1045.get(k) for k in ("elastic_modulus_gpa", "yield_strength_mpa")}))

    # ---------- gear train ----------
    g = run_solver("gear", "gear_train",
                   {"z1": 20, "z2": 40, "module_mm": 2, "input_speed_rpm": 1500,
                    "input_torque_Nm": 10, "efficiency": 0.95,
                    "pressure_angle_deg": 20}, {})
    check("gear_train ratio 2", approx(g["gear_ratio"], 2))
    check("gear_train output speed 750 rpm", approx(g["output_speed_rpm"], 750))
    check("gear_train output torque 19 Nm", approx(g["output_torque_Nm"], 19))
    check("gear_train power in 1570.8 W", approx(g["power_in_W"], 1570.8))
    check("gear_train power out 1492.3 W", approx(g["power_out_W"], 1492.3))
    check("gear_train pitch diameters 0.04/0.08 m",
          approx(g["pitch_diameter_1_m"], 0.04) and approx(g["pitch_diameter_2_m"], 0.08))
    check("gear_train centre distance 0.06 m", approx(g["centre_distance_m"], 0.06))
    check("gear_train tangential force 500 N", approx(g["tangential_force_N"], 500))
    check("gear_train radial force 182.0 N", approx(g["radial_force_N"], 182.0))

    # ---------- shaft (combined bending + torsion) ----------
    s = run_solver("shaft", "shaft_combined",
                   {"diameter_m": 0.02, "length_m": 1, "torque_Nm": 100,
                    "bending_moment_Nm": 50, "material_id": "steel-1045"}, s1045)
    check("shaft bending stress 63.66 MPa", approx(s["bending_stress_Pa"], 63.66e6))
    check("shaft shear stress 63.66 MPa", approx(s["shear_stress_Pa"], 63.66e6))
    check("shaft von Mises 127.32 MPa", approx(s["von_mises_stress_Pa"], 127.32e6))
    check("shaft safety factor 2.435", approx(s["safety_factor"], 310 / 127.32))
    check("shaft twist 0.0821 rad", approx(s["angle_of_twist_rad"], 0.0821))
    check("shaft deflection 2.653 mm", approx(s["deflection_m"], 0.002653))

    # ---------- bearing ----------
    b = run_solver("bearing", "bearing_load",
                   {"radial_load_N": 5000, "axial_load_N": 1000,
                    "speed_rpm": 1500, "life_h": 10000}, {})
    check("bearing equivalent load 5000 N (Fa/Fr <= e)",
          approx(b["equivalent_load_N"], 5000))
    check("bearing life 900 M rev", approx(b["life_million_rev"], 900))
    check("bearing required rating 48276 N",
          approx(b["required_rating_N"], 5000 * 900 ** (1 / 3)))

    # ---------- belt drive ----------
    bd = run_solver("belt", "belt_drive",
                    {"d1_m": 0.1, "d2_m": 0.2, "centre_m": 0.5,
                     "input_speed_rpm": 1500, "power_W": 2000, "mu": 0.3}, {})
    check("belt ratio 2", approx(bd["gear_ratio"], 2))
    check("belt output speed 750 rpm", approx(bd["output_speed_rpm"], 750))
    check("belt speed 7.854 m/s", approx(bd["belt_speed_m_s"], 7.854))
    check("belt length 1.4762 m", approx(bd["belt_length_m"], 1.47624))
    check("belt wrap angle 2.9413 rad", approx(bd["wrap_angle_rad"], 2.94126))
    check("belt tension ratio 2.4166", approx(bd["tension_ratio"], 2.4166))
    check("belt tight tension 434.4 N", approx(bd["tight_tension_N"], 434.4))
    check("belt slack tension 179.8 N", approx(bd["slack_tension_N"], 179.8))

    # ---------- spring ----------
    sp = run_solver("spring", "spring_helical",
                    {"wire_d_m": 0.003, "coil_d_m": 0.03, "coils": 6,
                     "load_N": 100, "material_id": "steel-1045"}, s1045)
    check("spring rate 4845 N/m", approx(sp["spring_rate_N_m"], 4845))
    check("spring deflection 20.64 mm", approx(sp["deflection_m"], 0.02064))
    check("spring shear stress 323.9 MPa", approx(sp["shear_stress_Pa"], 323.9e6))
    check("spring Wahl factor 1.1448", approx(sp["wahl_factor"], 1.1448))
    check("spring solid length 18 mm", approx(sp["solid_length_m"], 0.018))

    # ---------- flywheel ----------
    fw = run_solver("flywheel", "flywheel",
                    {"outer_d_m": 0.2, "inner_d_m": 0, "thickness_m": 0.024,
                     "speed_rpm": 3000, "material_id": "steel-1045"}, s1045)
    check("flywheel mass 5.918 kg", approx(fw["mass_kg"], 5.918))
    check("flywheel inertia 0.02959 kg m2", approx(fw["inertia_kg_m2"], 0.02959))
    check("flywheel energy 1460.3 J", approx(fw["energy_J"], 1460.3))
    check("flywheel rim speed 31.42 m/s", approx(fw["rim_speed_m_s"], 31.42))
    check("flywheel rim stress 7.748 MPa", approx(fw["rim_stress_Pa"], 7.748e6))

    # ---------- hydraulic cylinder ----------
    hc = run_solver("hydraulic", "hydraulic_cylinder",
                    {"bore_d_m": 0.05, "rod_d_m": 0.025,
                     "pressure_Pa": 10e6, "flow_m3_s": 0.001}, {})
    check("hydraulic extend force 19635 N", approx(hc["extend_force_N"], 19635))
    check("hydraulic retract force 14726 N", approx(hc["retract_force_N"], 14726))
    check("hydraulic extend speed 0.5093 m/s", approx(hc["extend_speed_m_s"], 0.5093))
    check("hydraulic retract speed 0.6791 m/s", approx(hc["retract_speed_m_s"], 0.6791))

    # ---------- crank-slider ----------
    cs = run_solver("crank", "crank_slider",
                    {"crank_r_m": 0.025, "rod_l_m": 0.12, "speed_rpm": 3000}, {})
    check("crank stroke 50 mm", approx(cs["stroke_m"], 0.05))
    check("crank mean piston speed 5.0 m/s",
          approx(cs["mean_piston_speed_m_s"], 5.0))
    check("crank max velocity ~8.02 m/s", 7.9 < cs["max_velocity_m_s"] < 8.2,
          str(cs["max_velocity_m_s"]))
    check("crank max acceleration ~2981 m/s2", 2900 < cs["max_acceleration_m_s2"] < 3050,
          str(cs["max_acceleration_m_s2"]))
    check("crank series has 73 points", len(cs["series"]) == 73)
    check("crank position at 0 deg = r + l = 0.145 m",
          approx(cs["series"][0]["position_m"], 0.145))
    check("crank position at 180 deg = l - r = 0.095 m",
          approx(cs["series"][18]["position_m"], 0.095))

    # ---------- fatigue ----------
    fa = run_solver("fatigue", "fatigue_shaft",
                    {"diameter_m": 0.02, "bending_moment_Nm": 50,
                     "torque_Nm": 100, "material_id": "steel-1045"}, s1045)
    check("fatigue alternating stress 63.66 MPa",
          approx(fa["alternating_stress_Pa"], 63.66e6))
    check("fatigue mean stress 110.27 MPa", approx(fa["mean_stress_Pa"], 110.27e6))
    check("fatigue Goodman SF 2.405", approx(fa["goodman_safety_factor"], 2.405))
    check("fatigue static SF 2.435", approx(fa["static_safety_factor"], 310 / 127.32))

    # ---------- vibration / power ----------
    vb = run_solver("vib", "vibration_1dof",
                    {"stiffness_N_m": 4807, "mass_kg": 1}, {})
    check("vibration natural frequency 11.04 Hz",
          approx(vb["natural_frequency_Hz"], 11.04, rel=0.005))
    check("vibration critical speed 662 rpm",
          approx(vb["critical_speed_rpm"], 662.2, rel=0.005))
    pw = run_solver("power", "power_transmission",
                    {"torque_Nm": 10, "speed_rpm": 1500}, {})
    check("power 1570.8 W / 1.571 kW / 2.106 hp",
          approx(pw["power_W"], 1570.8) and approx(pw["power_kW"], 1.571)
          and approx(pw["power_hp"], 2.106))

    # ---------- missing properties are named errors, never substitutions ----------
    mineral = props_of("mineral-wool")
    try:
        run_solver("fatigue-missing", "fatigue_shaft",
                   {"diameter_m": 0.02, "bending_moment_Nm": 50,
                    "torque_Nm": 100, "material_id": "mineral-wool"}, mineral)
        check("fatigue with mineral-wool refuses", False, "no error raised")
    except ValueError as e:
        check("fatigue with mineral-wool refuses", "tensile_strength_mpa" in str(e)
              or "fatigue_limit_mpa" in str(e) or "yield_strength_mpa" in str(e),
              str(e))
    try:
        run_solver("crank-bad", "crank_slider",
                   {"crank_r_m": 0.12, "rod_l_m": 0.025, "speed_rpm": 1000}, {})
        check("crank-slider with rod shorter than crank refuses", False)
    except ValueError as e:
        check("crank-slider with rod shorter than crank refuses", True, str(e))

    # ---------- new component kinds: validation + volumes ----------
    def comp(kind, params):
        return {"id": "t1", "name": "T", "type": "component", "kind": kind,
                "params": params, "position": [0, 0, 0], "rotation": [0, 0, 0],
                "material_id": None, "visible": True, "parent_id": None,
                "tolerance_mm": 0.1}

    def valid_model(components):
        return modelmod.validate_model({"version": 1, "units": "mm",
                                        "components": components})

    new_kinds = {
        "crankshaft": {"main_diameter": 30, "crank_diameter": 24, "throw": 25, "length": 160, "journals": 3},
        "connecting_rod": {"big_diameter": 40, "small_diameter": 24, "length": 120, "width": 16},
        "flywheel": {"diameter": 200, "thickness": 24, "hub_diameter": 60, "bore_diameter": 30},
        "clutch": {"diameter": 180, "thickness": 12, "bore_diameter": 30, "plates": 2},
        "brake_disc": {"diameter": 220, "thickness": 20, "bore_diameter": 60, "hub_diameter": 100},
        "coupling": {"diameter": 90, "length": 60, "bore_diameter": 25, "bolts": 4},
        "pulley": {"diameter": 120, "width": 24, "bore_diameter": 25, "groove_depth": 4},
        "sprocket": {"teeth": 18, "pitch": 12.7, "thickness": 8, "bore_diameter": 25},
        "hydraulic_cylinder": {"bore_diameter": 50, "rod_diameter": 25, "stroke": 100, "barrel_length": 160},
        "valve": {"body_length": 90, "body_width": 60, "body_height": 50, "bonnet_diameter": 30, "handwheel_diameter": 80},
        "pump": {"housing_diameter": 120, "housing_length": 90, "impeller_diameter": 90, "vanes": 6},
    }
    for kind, params in new_kinds.items():
        errs = valid_model([comp(kind, params)])
        check(f"new kind {kind} validates", not errs, str(errs))
        v = modelmod.analytic_volume(comp(kind, params))
        check(f"new kind {kind} has a positive analytic volume",
              v["value"] is not None and v["value"] > 0, str(v))
    check("hydraulic cylinder with rod >= bore is rejected",
          bool(valid_model([comp("hydraulic_cylinder", {"bore_diameter": 25, "rod_diameter": 25, "stroke": 100, "barrel_length": 160})])))
    check("sprocket with 3 teeth is rejected",
          bool(valid_model([comp("sprocket", {"teeth": 3, "pitch": 12.7, "thickness": 8})])))
    check("crankshaft with 1 journal is rejected",
          bool(valid_model([comp("crankshaft", {"main_diameter": 30, "crank_diameter": 24, "throw": 25, "length": 160, "journals": 1})])))

    # ---------- demo models ----------
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("gear_transmission", "crank_slider", "rotating_shaft", "hydraulic_lift"):
        with open(os.path.join(repo, "workspace", "test-models", "mechanical", name + ".json")) as f:
            d = json.load(f)
        errs = modelmod.validate_model(d)
        check(f"demo model {name} validates", not errs, str(errs))
        vols = [modelmod.analytic_volume(c)["value"] for c in d["components"]]
        check(f"demo model {name} has all positive volumes",
              all(v is not None and v > 0 for v in vols), str(vols))

    # ---------- API: mechanical jobs via HTTP ----------
    server = ThreadingHTTPServer(("127.0.0.1", 0), appmod.Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        status, body = req(base, "GET", "/health")
        check("health reports stage 7", body.get("stage") in (7, 8, 9, 10), str(body))
        status, body = req(base, "POST", "/api/v1/auth/register",
                           body={"email": "alice@example.com", "username": "alice",
                                 "password": "correct-horse-battery", "name": "Alice"})
        check("register Alice", status == 201, str(status))
        token = body["token"]
        status, body = req(base, "POST", "/api/v1/projects", token,
                           body={"name": "Mech demo", "description": "", "lab": "mechanical"})
        check("create project", status == 201, str(status))
        pid = body["project"]["id"]
        status, body = req(base, "POST", "/api/v1/simulations", token,
                           body={"project_id": pid, "solver": "gear_train",
                                 "inputs": {"z1": 20, "z2": 40, "module_mm": 2,
                                            "input_speed_rpm": 1500,
                                            "input_torque_Nm": 10,
                                            "efficiency": 0.95}})
        check("gear_train job completes via API",
              status in (200, 201) and body.get("status") == "completed"
              and approx(body["results"]["values"]["output_torque_Nm"], 19),
              str(status) + " " + str(body.get("status")))
        status, body = req(base, "POST", "/api/v1/simulations", token,
                           body={"project_id": pid, "solver": "crank_slider",
                                 "inputs": {"crank_r_m": 0.025, "rod_l_m": 0.12,
                                            "speed_rpm": 3000}})
        check("crank_slider job completes via API",
              status in (200, 201) and body.get("status") == "completed"
              and len(body["results"]["values"]["series"]) == 73,
              str(status) + " " + str(body.get("status")))
        status, body = req(base, "POST", "/api/v1/simulations", token,
                           body={"project_id": pid, "solver": "fatigue_shaft",
                                 "inputs": {"diameter_m": 0.02,
                                            "bending_moment_Nm": 50,
                                            "torque_Nm": 100,
                                            "material_id": "mineral-wool"}})
        check("fatigue job with missing material data is recorded failed",
              body.get("status") == "failed"
              and "is not on record" in str(body["results"].get("error")),
              str(body.get("status")))
        # save a demo model into the project via the model API
        with open(os.path.join(repo, "workspace", "test-models", "mechanical",
                               "gear_transmission.json")) as f:
            demo = json.load(f)
        status, body = req(base, "PUT", f"/api/v1/projects/{pid}/model", token,
                           body={"model": demo, "base_version": 0})
        check("demo gear transmission saves via model API",
              status == 200 and body.get("model", {}).get("version") == 1, str(status))
        status, body = req(base, "POST", f"/api/v1/projects/{pid}/model/components",
                           token, body={"component": {
                               "id": "fly-1", "name": "Flywheel", "type": "component",
                               "kind": "flywheel",
                               "params": {"diameter": 160, "thickness": 20,
                                          "hub_diameter": 50, "bore_diameter": 20},
                               "position": [0, 0, 0], "rotation": [0, 0, 0],
                               "material_id": "steel-1045", "visible": True,
                               "parent_id": None, "tolerance_mm": 0.1}})
        check("flywheel component adds via model API",
              status == 201 and body.get("model", {}).get("version") == 2, str(status))
        status, body = req(base, "GET", "/api/v1/solvers")
        check("solvers registry lists the mechanical solvers",
              status == 200 and "gear_train" in body.get("solvers", {})
              and "crank_slider" in body.get("solvers", {}), str(status))
    finally:
        server.shutdown()
        server.server_close()

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} tests passed")
    if failed:
        for name, _, detail in failed:
            print("FAILED:", name, detail)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
