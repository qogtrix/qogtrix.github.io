"""Stage 6 tests — analytical solvers + simulation job API.

Stdlib only. Real backend on a temporary database, real HTTP.
Analytical results are checked against hand-computed reference
values (formulas in docs/VALIDATION_STAGE6.md).

Run:  cd backend && python3 test_stage6.py
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


def approx(a, b, rel=0.001):
    return a is not None and abs(a - b) <= rel * abs(b)


def main():
    tmp = tempfile.mkdtemp(prefix="aielab-stage6-test-")
    os.environ["AIELAB_DB"] = os.path.join(tmp, "test.db")
    os.environ["AIELAB_SECRET"] = "test-secret-for-stage6-only"
    conn = dbmod.connect(os.environ["AIELAB_DB"])
    dbmod.init_db(conn)
    conn.close()

    server = ThreadingHTTPServer(("127.0.0.1", 0), appmod.Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    # Material properties straight from the seeded Stage 4 database.
    props_steel = {"elastic_modulus_gpa": 200, "yield_strength_mpa": 355,
                   "poisson_ratio": 0.3, "density_kg_m3": 7850,
                   "thermal_conductivity_w_mk": 50,
                   "specific_heat_j_kgk": 490}
    rect = {"type": "rectangle", "b_m": 0.1, "h_m": 0.2}

    try:
        s, h = req(base, "GET", "/health")
        check("health endpoint (stage 6)", s == 200 and h.get("stage") in (6, 7, 8, 9), f"HTTP {s}")
        s, reg = req(base, "GET", "/api/v1/solvers")
        check("solver registry lists analytical + fea/cfd as not_implemented",
              s == 200 and reg["solvers"]["cantilever_beam"]["status"] == "available"
              and reg["solvers"]["fea"]["status"] == "not_implemented"
              and reg["solvers"]["rigid_body"]["status"] == "browser", "")

        # --- analytical solvers: hand-computed references ---
        r = solversmod.run_solver("cantilever_beam",
                                  {"length_m": 3, "load_N": 1000, "section": rect},
                                  props_steel)
        check("cantilever: deflection 0.675 mm (FL^3/3EI)",
              approx(r["deflection_m"], 0.000675), f"got {r['deflection_m']}")
        check("cantilever: max stress 4.5 MPa, SF 78.9",
              approx(r["max_stress_Pa"], 4.5e6) and approx(r["safety_factor"], 355 / 4.5),
              f"got {r['max_stress_Pa']}, SF {r['safety_factor']}")
        r = solversmod.run_solver("simply_supported_beam",
                                  {"length_m": 3, "load_N": 1000, "section": rect},
                                  props_steel)
        check("simply supported: deflection 0.0422 mm, stress 1.125 MPa",
              approx(r["deflection_m"], 4.21875e-5) and approx(r["max_stress_Pa"], 1.125e6),
              f"got {r['deflection_m']}, {r['max_stress_Pa']}")
        r = solversmod.run_solver("axial_bar",
                                  {"length_m": 1, "force_N": 10000,
                                   "section": {"type": "rectangle", "b_m": 0.1, "h_m": 0.01}},
                                  props_steel)
        check("axial bar: stress 10 MPa, elongation 0.05 mm",
              approx(r["stress_Pa"], 1e7) and approx(r["elongation_m"], 5e-5),
              f"got {r['stress_Pa']}, {r['elongation_m']}")
        r = solversmod.run_solver("torsion_shaft",
                                  {"length_m": 1, "torque_Nm": 100, "diameter_m": 0.02},
                                  props_steel)
        check("torsion: shear 63.66 MPa, angle 0.0828 rad",
              approx(r["shear_stress_Pa"], 6.366e7) and approx(r["angle_rad"], 0.0828, 0.002),
              f"got {r['shear_stress_Pa']}, {r['angle_rad']}")
        r = solversmod.run_solver("thermal_conduction",
                                  {"thickness_m": 0.01, "area_m2": 1,
                                   "t_hot_C": 100, "t_cold_C": 0},
                                  props_steel)
        check("thermal conduction: Q = 500 kW, R = 0.0002 K/W",
              approx(r["heat_flow_W"], 500000) and approx(r["thermal_resistance_K_W"], 0.0002),
              f"got {r['heat_flow_W']}, {r['thermal_resistance_K_W']}")
        check("thermal conduction: linear profile 100 -> 0 C",
              r["temperature_profile_C"][0]["t_C"] == 100
              and r["temperature_profile_C"][5]["t_C"] == 50
              and r["temperature_profile_C"][10]["t_C"] == 0, "")
        r = solversmod.run_solver("lumped_thermal",
                                  {"volume_m3": 0.001, "area_m2": 0.06,
                                   "h_W_m2K": 10, "t0_C": 100, "t_inf_C": 25,
                                   "duration_s": 3600},
                                  props_steel)
        check("lumped thermal: tau = 6411 s, T(3600 s) = 67.8 C",
              approx(r["time_constant_s"], 6410.8) and approx(r["final_temperature_C"], 67.8, 0.002),
              f"got {r['time_constant_s']}, {r['final_temperature_C']}")
        r = solversmod.run_solver("drag",
                                  {"velocity_m_s": 30, "area_m2": 1, "cd": 0.5,
                                   "cl": 0.3, "fluid": "air", "length_m": 1},
                                  {})
        check("drag: Fd = 275.6 N, Re = 2.03e6",
              approx(r["drag_N"], 275.625) and approx(r["reynolds"], 2.03e6, 0.01),
              f"got {r['drag_N']}, {r['reynolds']}")
        r = solversmod.run_solver("free_fall",
                                  {"height_m": 10, "mass_kg": 1, "g_m_s2": 9.81}, {})
        check("free fall: t = 1.428 s, v = 14.0 m/s, KE = 98.1 J",
              approx(r["fall_time_s"], 1.4278) and approx(r["impact_velocity_m_s"], 14.0)
              and approx(r["impact_kinetic_energy_J"], 98.1),
              f"got {r}")
        # I-beam section properties (same beam as the Stage 5 test model).
        area, I, _J, c = solversmod.section_properties(
            {"type": "ibeam", "height_m": 0.2, "flange_width_m": 0.1,
             "flange_thickness_m": 0.01, "web_thickness_m": 0.006})
        check("I-beam section: I = 2.098e-5 m4",
              approx(I, 2.098e-5, 0.005), f"got {I}")
        # Missing material property is an error, never a substitution.
        try:
            solversmod.run_solver("cantilever_beam",
                                  {"length_m": 3, "load_N": 1000, "section": rect},
                                  {"elastic_modulus_gpa": 200})
            check("missing yield strength is rejected (no substitution)", False, "no error raised")
        except ValueError as e:
            check("missing yield strength is rejected (no substitution)",
                  "yield_strength_mpa" in str(e), str(e))
        try:
            solversmod.run_solver("fea", {}, {})
            check("FEA solver refuses to run (not installed)", False, "no error raised")
        except ValueError as e:
            check("FEA solver refuses to run (not installed)",
                  "not implemented" in str(e), str(e))

        # --- users + project ---
        s, a = req(base, "POST", "/api/v1/auth/register",
                   body={"email": "alice@example.com", "username": "alice",
                         "password": "correct-horse-1", "name": "Alice"})
        alice = a.get("token", "")
        s, b = req(base, "POST", "/api/v1/auth/register",
                   body={"email": "bob@example.com", "username": "bob",
                         "password": "correct-horse-2", "name": "Bob"})
        bob = b.get("token", "")
        s, p = req(base, "POST", "/api/v1/projects", token=alice,
                   body={"name": "Beam Study", "description": "Stage 6 test",
                         "lab": "structural"})
        pid = p["project"]["id"]

        # --- job API: analytical job completes with real results ---
        s, job = req(base, "POST", "/api/v1/simulations", token=alice,
                     body={"project_id": pid, "solver": "cantilever_beam",
                           "inputs": {"length_m": 3, "load_N": 1000,
                                      "section": rect, "material_id": "steel-s355"}})
        check("cantilever job completes with analytical results",
              s in (200, 201) and job["status"] == "completed"
              and job["results"]["method"] == "analytical"
              and approx(job["results"]["values"]["deflection_m"], 0.000675),
              f"HTTP {s}, status {job.get('status')}")
        check("job results carry assumptions + engine",
              "assumptions" in job["results"] and "Euler-Bernoulli" in job["results"]["assumptions"][0], "")
        # Missing material property via the API: job recorded as failed.
        s, job2 = req(base, "POST", "/api/v1/simulations", token=alice,
                      body={"project_id": pid, "solver": "cantilever_beam",
                            "inputs": {"length_m": 3, "load_N": 1000,
                                       "section": rect, "material_id": "mineral-wool"}})
        check("job with missing material property is recorded failed, naming it",
              job2["status"] == "failed" and "is not on record" in str(job2["results"]),
              f"status {job2.get('status')}, results {job2.get('results')}")
        # FEA job: recorded, not faked.
        s, job3 = req(base, "POST", "/api/v1/simulations", token=alice,
                      body={"project_id": pid, "solver": "fea", "inputs": {}})
        check("FEA job recorded as not_implemented with no results",
              s in (200, 201) and job3["status"] == "not_implemented"
              and job3["results"] is None, f"HTTP {s}")
        # Rigid-body job: queued, then the browser posts results.
        s, job4 = req(base, "POST", "/api/v1/simulations", token=alice,
                      body={"project_id": pid, "solver": "rigid_body",
                            "inputs": {"gravity_m_s2": 9.81, "duration_s": 2}})
        check("rigid-body job is queued (runs in browser)",
              s in (200, 201) and job4["status"] == "queued", f"HTTP {s}")
        s, done = req(base, "POST", f"/api/v1/simulations/{job4['id']}/results",
                      token=alice,
                      body={"results": {"summary": {"final_y_m": 5.1, "max_speed_m_s": 9.8,
                                                    "contacts": 1},
                                        "series": [{"t": 0, "y": 10}, {"t": 1, "y": 5.1}]}})
        check("browser can post rigid-body results -> completed",
              s == 200 and done["status"] == "completed"
              and done["results"]["summary"]["final_y_m"] == 5.1, f"HTTP {s}")
        s, _ = req(base, "POST", f"/api/v1/simulations/{job4['id']}/results",
                   token=alice, body={"results": {"summary": {}}})
        check("results cannot be posted twice (400)", s == 400, f"HTTP {s}")
        # Ownership + listing + delete.
        s, _ = req(base, "GET", f"/api/v1/simulations/{job['id']}", token=bob)
        check("Bob cannot read Alice's simulation (404)", s == 404, f"HTTP {s}")
        s, _ = req(base, "POST", "/api/v1/simulations", token=bob,
                   body={"project_id": pid, "solver": "drag", "inputs": {}})
        check("Bob cannot create a job in Alice's project (404)", s == 404, f"HTTP {s}")
        s, _ = req(base, "POST", "/api/v1/simulations", token=alice,
                   body={"project_id": pid, "solver": "warp_drive", "inputs": {}})
        check("unknown solver rejected (400)", s == 400, f"HTTP {s}")
        s, lst = req(base, "GET", f"/api/v1/simulations?project_id={pid}", token=alice)
        check("list simulations for the project (4 jobs)",
              s == 200 and len(lst["simulations"]) == 4, f"got {len(lst.get('simulations', []))}")
        s, _ = req(base, "DELETE", f"/api/v1/simulations/{job3['id']}", token=alice)
        check("delete a simulation job", s == 200, f"HTTP {s}")
        s, lst = req(base, "GET", f"/api/v1/simulations?project_id={pid}", token=alice)
        check("deleted job is gone from the list",
              len(lst["simulations"]) == 3, "")

        # --- earlier stages still pass ---
        s, got = req(base, "GET", f"/api/v1/projects/{pid}/model", token=alice)
        check("Stage 5 model API still works",
              s == 200 and got["model"]["version"] == 0, f"HTTP {s}")
    finally:
        server.shutdown()
        server.server_close()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} tests passed")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
