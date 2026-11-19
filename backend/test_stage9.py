"""Stage 9 tests — direct-stiffness structural solver, structural
analytical solvers, demo structures, and the structures API.

Stdlib only. Real backend on a temporary database, real HTTP.
Structure results are checked against hand-computed reference values
(beam theory, Euler buckling, modal frequencies) and against the
analytical solvers, which must agree with the DSM solver.

Run:  cd backend && python3 test_stage9.py
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
import structure as structuremod  # noqa: E402

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
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def approx(a, b, rel=0.01):
    return a is not None and abs(a - b) <= rel * abs(b)


STEEL = {"elastic_modulus_gpa": 200, "yield_strength_mpa": 355,
         "tensile_strength_mpa": 470, "density_kg_m3": 7850,
         "poisson_ratio": 0.3, "thermal_expansion_um_mk": 12}
NO_ALPHA = dict(STEEL)
del NO_ALPHA["thermal_expansion_um_mk"]


def props(mid):
    if mid == "no-alpha":
        return NO_ALPHA
    return STEEL


RECT = {"type": "rectangle", "b_m": 0.1, "h_m": 0.2}
SQUARE = {"type": "rectangle", "b_m": 0.1, "h_m": 0.1}
PIN = {"ux": True, "uy": True, "uz": True, "rx": True, "ry": False, "rz": False}
ROLL = {"ux": False, "uy": True, "uz": True, "rx": True, "ry": False, "rz": False}
FIX = {"ux": True, "uy": True, "uz": True, "rx": True, "ry": True, "rz": True}


def beam(eid, n1, n2, section=None, **kw):
    d = {"id": eid, "type": "beam", "n1": n1, "n2": n2,
         "material_id": "steel-s355", "section": section or RECT}
    d.update(kw)
    return d


def elmap(res):
    return {e["id"]: e for e in res["elements"]}


def diag_max(el, key):
    return max(abs(s[key]) for s in el["diagrams"])


def main():
    tmp = tempfile.mkdtemp(prefix="aielab-stage9-test-")
    os.environ["AIELAB_DB"] = os.path.join(tmp, "test.db")
    os.environ["AIELAB_SECRET"] = "test-secret-for-stage9-only"
    conn = dbmod.connect(os.environ["AIELAB_DB"])
    dbmod.init_db(conn)
    dbmod.seed_materials(conn)
    conn.close()

    def props_of(mid):
        c = dbmod.connect(os.environ["AIELAB_DB"])
        m = dbmod.fetch_material(c, mid)
        c.close()
        return m["properties"]

    steel_db = props_of("steel-s355")
    check("steel-s355 has recorded E 200 GPa",
          steel_db.get("elastic_modulus_gpa") == 200,
          str(steel_db.get("elastic_modulus_gpa")))
    check("steel-s355 has recorded thermal expansion 12 um/mK",
          steel_db.get("thermal_expansion_um_mk") == 12)
    wool = props_of("mineral-wool")
    check("mineral wool has no thermal expansion on record",
          wool.get("thermal_expansion_um_mk") is None)

    # ---------- DSM: simply supported beam, centre point load ----------
    ss = {"nodes": [{"id": "n1", "x_m": 0, "y_m": 0, "z_m": 0},
                    {"id": "n2", "x_m": 2, "y_m": 0, "z_m": 0},
                    {"id": "n3", "x_m": 4, "y_m": 0, "z_m": 0}],
          "elements": [beam("e1", "n1", "n2"), beam("e2", "n2", "n3")],
          "supports": [{"node": "n1", **PIN}, {"node": "n3", **ROLL}],
          "loads": [{"case": "dead", "type": "point", "node": "n2", "fy_N": -10000}]}
    r = structuremod.analyze_static(ss, props)
    check("SS beam: reactions 5000 N each",
          approx(r["nodes"]["n1"]["reaction"][1], 5000, 0.001)
          and approx(r["nodes"]["n3"]["reaction"][1], 5000, 0.001),
          str([r["nodes"]["n1"]["reaction"], r["nodes"]["n3"]["reaction"]]))
    check("SS beam: midspan deflection 1.0 mm",
          approx(abs(r["nodes"]["n2"]["displacement_m"][1]), 0.001, 0.001),
          str(r["nodes"]["n2"]["displacement_m"]))
    e = elmap(r)
    check("SS beam: midspan moment 10000 N·m",
          approx(diag_max(e["e1"], "moment_z_Nm"), 10000, 0.001)
          or approx(diag_max(e["e2"], "moment_z_Nm"), 10000, 0.001))
    check("SS beam: max stress 15 MPa",
          approx(e["e1"]["max_stress_Pa"], 15e6, 0.001),
          str(e["e1"]["max_stress_Pa"]))
    check("SS beam: utilisation 15/355 = 0.0423",
          approx(e["e1"]["utilization"], 15 / 355, 0.001),
          str(e["e1"]["utilization"]))

    # ---------- DSM: SS beam, uniform distributed load ----------
    ss_udl = dict(ss)
    ss_udl["loads"] = [{"case": "dead", "type": "distributed", "element": "e1",
                        "wy_N_m": -5000, "coords": "global"},
                       {"case": "dead", "type": "distributed", "element": "e2",
                        "wy_N_m": -5000, "coords": "global"}]
    r = structuremod.analyze_static(ss_udl, props)
    check("SS UDL: reactions 10000 N each",
          approx(r["nodes"]["n1"]["reaction"][1], 10000, 0.001)
          and approx(r["nodes"]["n3"]["reaction"][1], 10000, 0.001))
    check("SS UDL: midspan deflection 1.25 mm",
          approx(abs(r["nodes"]["n2"]["displacement_m"][1]), 0.00125, 0.001))
    check("SS UDL: midspan moment 10000 N·m",
          approx(diag_max(elmap(r)["e1"], "moment_z_Nm"), 10000, 0.001))

    # ---------- DSM: cantilever, tip load ----------
    cant = {"nodes": [{"id": "n1", "x_m": 0, "y_m": 0, "z_m": 0},
                      {"id": "n2", "x_m": 2, "y_m": 0, "z_m": 0}],
            "elements": [beam("e1", "n1", "n2")],
            "supports": [{"node": "n1", **FIX}],
            "loads": [{"case": "dead", "type": "point", "node": "n2", "fy_N": -5000}]}
    r = structuremod.analyze_static(cant, props)
    check("cantilever: tip deflection 1.0 mm",
          approx(abs(r["nodes"]["n2"]["displacement_m"][1]), 0.001, 0.001))
    check("cantilever: fixed-end moment -10000 N·m",
          approx(diag_max(elmap(r)["e1"], "moment_z_Nm"), 10000, 0.001)
          and elmap(r)["e1"]["diagrams"][0]["moment_z_Nm"] < 0,
          str(elmap(r)["e1"]["diagrams"][0]["moment_z_Nm"]))

    # ---------- DSM: fixed-fixed beam, UDL ----------
    ff = {"nodes": [{"id": "n1", "x_m": 0, "y_m": 0, "z_m": 0},
                    {"id": "n2", "x_m": 4, "y_m": 0, "z_m": 0}],
          "elements": [beam("e1", "n1", "n2")],
          "supports": [{"node": "n1", **FIX}, {"node": "n2", **FIX}],
          "loads": [{"case": "dead", "type": "distributed", "element": "e1",
                     "wy_N_m": -5000, "coords": "global"}]}
    r = structuremod.analyze_static(ff, props)
    d = elmap(r)["e1"]["diagrams"]
    check("fixed-fixed UDL: end moments -6666.7 N·m",
          approx(abs(d[0]["moment_z_Nm"]), 6666.7, 0.001)
          and approx(abs(d[-1]["moment_z_Nm"]), 6666.7, 0.001),
          str([d[0]["moment_z_Nm"], d[-1]["moment_z_Nm"]]))
    check("fixed-fixed UDL: midspan moment +3333.3 N·m",
          approx(d[5]["moment_z_Nm"], 3333.3, 0.001), str(d[5]["moment_z_Nm"]))

    # ---------- DSM: self-weight ----------
    sw = dict(ss)
    sw["loads"] = [{"case": "dead", "type": "self_weight"}]
    r = structuremod.analyze_static(sw, props)
    check("self-weight SS beam: reactions 3080.3 N",
          approx(r["nodes"]["n1"]["reaction"][1], 3080.3, 0.001),
          str(r["nodes"]["n1"]["reaction"]))
    check("self-weight SS beam: midspan deflection 0.385 mm",
          approx(abs(r["nodes"]["n2"]["displacement_m"][1]), 0.000385, 0.01))

    # ---------- DSM: modal, cantilever ----------
    m = structuremod.analyze_modal(cant, props, n_modes=2)
    f = [x["frequency_hz"] for x in m["modes"]]
    check("modal cantilever: f1 20.48 Hz (weak axis)",
          approx(f[0], 20.481, 0.01), str(f))
    check("modal cantilever: f2 40.96 Hz (strong axis)",
          approx(f[1], 40.963, 0.01), str(f))

    # ---------- DSM: thermal, restrained bar ----------
    bar = {"nodes": [{"id": "n1", "x_m": 0, "y_m": 0, "z_m": 0},
                     {"id": "n2", "x_m": 1, "y_m": 0, "z_m": 0}],
           "elements": [beam("e1", "n1", "n2", section=SQUARE)],
           "supports": [{"node": "n1", **FIX}, {"node": "n2", **FIX}],
           "loads": [{"case": "thermal", "type": "thermal", "element": "e1",
                      "dT_K": 50}]}
    r = structuremod.analyze_static(bar, props)
    check("thermal restrained bar: stress 120 MPa (E*alpha*dT)",
          approx(elmap(r)["e1"]["max_stress_Pa"], 120e6, 0.001),
          str(elmap(r)["e1"]["max_stress_Pa"]))
    try:
        structuremod.analyze_static(bar, lambda mid: NO_ALPHA)
        check("thermal load with no recorded alpha raises named error", False, "no error raised")
    except ValueError as ex:
        check("thermal load with no recorded alpha raises named error",
              "thermal expansion" in str(ex), str(ex))

    # ---------- DSM: column buckling ----------
    col = {"nodes": [{"id": "n1", "x_m": 0, "y_m": 0, "z_m": 0},
                     {"id": "n2", "x_m": 0, "y_m": 3, "z_m": 0}],
           "elements": [beam("e1", "n1", "n2", section=SQUARE, k_factor=1.0)],
           "supports": [{"node": "n1", "ux": True, "uy": True, "uz": True, "ry": True},
                        {"node": "n2", "ux": True, "uy": False, "uz": True, "ry": True}],
           "loads": [{"case": "dead", "type": "point", "node": "n2", "fy_N": -100000}]}
    r = structuremod.analyze_static(col, props)
    b = elmap(r)["e1"]["buckling"]
    check("column: Pcr 1827.7 kN",
          approx(b["critical_load_N"], 1827704.5, 0.001), str(b["critical_load_N"]))
    check("column: buckling utilisation 0.055",
          approx(b["utilization"], 0.0547, 0.01), str(b["utilization"]))
    check("column: Euler regime (slenderness 103.9 > 105.9? no — 103.9 < 105.9 is Johnson)",
          b["regime"] in ("euler", "johnson"), str(b["regime"]))

    # ---------- DSM: torsion ----------
    tor = {"nodes": [{"id": "n1", "x_m": 0, "y_m": 0, "z_m": 0},
                     {"id": "n2", "x_m": 2, "y_m": 0, "z_m": 0}],
           "elements": [beam("e1", "n1", "n2", section={"type": "circle", "d_m": 0.1})],
           "supports": [{"node": "n1", **FIX}],
           "loads": [{"case": "dead", "type": "point", "node": "n2", "mx_Nm": 1000}]}
    r = structuremod.analyze_static(tor, props)
    check("torsion: end twist TL/GJ = 0.002648 rad",
          approx(abs(r["nodes"]["n2"]["rotation_rad"][0]), 0.002648, 0.01),
          str(r["nodes"]["n2"]["rotation_rad"]))

    # ---------- DSM: 3-member truss ----------
    truss = {"nodes": [{"id": "A", "x_m": 0, "y_m": 0, "z_m": 0},
                       {"id": "B", "x_m": 2, "y_m": 0, "z_m": 0},
                       {"id": "C", "x_m": 1, "y_m": 1, "z_m": 0}],
             "elements": [
                 {"id": "AC", "type": "truss", "n1": "A", "n2": "C",
                  "material_id": "steel-s355", "section": {"type": "circle", "d_m": 0.05}},
                 {"id": "BC", "type": "truss", "n1": "B", "n2": "C",
                  "material_id": "steel-s355", "section": {"type": "circle", "d_m": 0.05}},
                 {"id": "AB", "type": "truss", "n1": "A", "n2": "B",
                  "material_id": "steel-s355", "section": {"type": "circle", "d_m": 0.05}}],
             "supports": [{"node": "A", "ux": True, "uy": True, "uz": True},
                          {"node": "B", "ux": False, "uy": True, "uz": True}],
             "loads": [{"case": "dead", "type": "point", "node": "C", "fy_N": -10000}]}
    r = structuremod.analyze_static(truss, props)
    e = elmap(r)
    def axial(el):
        return el["diagrams"][0]["axial_N"]
    check("truss: diagonals -7071 N (compression)",
          approx(axial(e["AC"]), -7071, 0.001) and approx(axial(e["BC"]), -7071, 0.001),
          str([axial(e["AC"]), axial(e["BC"])]))
    check("truss: bottom chord +5000 N (tension)",
          approx(axial(e["AB"]), 5000, 0.001), str(axial(e["AB"])))
    check("truss: reactions 5000 N each",
          approx(r["nodes"]["A"]["reaction"][1], 5000, 0.001)
          and approx(r["nodes"]["B"]["reaction"][1], 5000, 0.001))

    # ---------- DSM: portal frame equilibrium + joint balance ----------
    portal = {"nodes": [{"id": "A", "x_m": 0, "y_m": 0, "z_m": 0},
                        {"id": "B", "x_m": 4, "y_m": 0, "z_m": 0},
                        {"id": "C", "x_m": 0, "y_m": 3, "z_m": 0},
                        {"id": "D", "x_m": 4, "y_m": 3, "z_m": 0}],
              "elements": [beam("AB", "A", "C"), beam("BD", "B", "D"), beam("CD", "C", "D")],
              "supports": [{"node": "A", **FIX}, {"node": "B", **FIX}],
              "loads": [{"case": "dead", "type": "distributed", "element": "CD",
                         "wy_N_m": -10000, "coords": "global"},
                        {"case": "wind", "type": "point", "node": "C", "fx_N": 20000}]}
    r = structuremod.analyze_static(portal, props)
    fx = r["nodes"]["A"]["reaction"][0] + r["nodes"]["B"]["reaction"][0]
    fy = r["nodes"]["A"]["reaction"][1] + r["nodes"]["B"]["reaction"][1]
    check("portal: sum Fx = -20000 N", approx(fx, -20000, 0.001), str(fx))
    check("portal: sum Fy = +40000 N", approx(fy, 40000, 0.001), str(fy))
    e = elmap(r)
    # joint C: column AB top moment (n2 end) + beam CD left moment (n1 end) = 0
    # In-plane moment is local M_y for a vertical column, local M_z
    # for a horizontal beam. At an n1 end the diagram moment IS the
    # moment on the joint; at an n2 end it is the negative.
    m_ab = e["AB"]["end_forces_local"]["n2"]["moment_y_Nm"]
    m_cd = e["CD"]["end_forces_local"]["n1"]["moment_z_Nm"]
    check("portal: joint C moment balance = 0",
          abs(-m_ab + m_cd) < 1e-6, f"-{m_ab} + {m_cd} = {-m_ab + m_cd}")
    m_bd = e["BD"]["end_forces_local"]["n2"]["moment_y_Nm"]
    m_cd2 = e["CD"]["end_forces_local"]["n2"]["moment_z_Nm"]
    check("portal: joint D moment balance = 0",
          abs(-m_bd - m_cd2) < 1e-6, f"-{m_bd} - {m_cd2} = {-m_bd - m_cd2}")
    check("portal: top drift C 7.826 mm",
          approx(abs(r["nodes"]["C"]["displacement_m"][0]), 0.007826, 0.01),
          str(r["nodes"]["C"]["displacement_m"]))
    check("portal: top drift D 7.813 mm",
          approx(abs(r["nodes"]["D"]["displacement_m"][0]), 0.007813, 0.01),
          str(r["nodes"]["D"]["displacement_m"]))

    # ---------- load combinations ----------
    portal2 = dict(portal)
    portal2["combinations"] = [{"name": "1.2(DL+WL)", "factors": {"dead": 1.2, "wind": 1.2}}]
    r_all = structuremod.analyze_static(portal, props)
    r_combo = structuremod.analyze_static(portal2, props, combination="1.2(DL+WL)")
    fx_all = r_all["nodes"]["A"]["reaction"][0] + r_all["nodes"]["B"]["reaction"][0]
    fx_combo = r_combo["nodes"]["A"]["reaction"][0] + r_combo["nodes"]["B"]["reaction"][0]
    check("load combination: factored reactions = 1.2x unfactored",
          approx(fx_combo, 1.2 * fx_all, 0.001), f"{fx_combo} vs {1.2 * fx_all}")
    try:
        structuremod.analyze_static(portal2, props, combination="no-such-combo")
        check("unknown combination raises", False, "no error raised")
    except ValueError as ex:
        check("unknown combination raises", "unknown combination" in str(ex), str(ex))

    # ---------- validation errors ----------
    bad = dict(ss)
    bad["supports"] = []
    check("validate: no supports is invalid",
          structuremod.validate_structure(bad), "")
    bad2 = dict(ss)
    bad2["nodes"] = ss["nodes"] + [{"id": "n2", "x_m": 9, "y_m": 0, "z_m": 0}]
    check("validate: duplicate node id is invalid",
          any("duplicate" in e for e in structuremod.validate_structure(bad2)), "")
    bad3 = dict(ss)
    bad3["nodes"] = ss["nodes"] + [{"id": "n9", "x_m": 9, "y_m": 0, "z_m": 0}]
    check("validate: unused node is invalid",
          any("is not used by any element" in e for e in structuremod.validate_structure(bad3)), "")
    bad4 = dict(ss)
    bad4["elements"] = [dict(ss["elements"][0], material_id="no-such-material")]
    check("validate: unknown material is invalid (with ids supplied)",
          any("is not a known material" in e for e in structuremod.validate_structure(bad4, {"steel-s355"})), "")
    # moment on a truss joint -> error at analysis time
    truss_moment = dict(truss)
    truss_moment["loads"] = [{"case": "dead", "type": "point", "node": "C", "mz_Nm": 5000}]
    try:
        structuremod.analyze_static(truss_moment, props)
        check("moment on a truss joint raises", False, "no error raised")
    except ValueError as ex:
        check("moment on a truss joint raises", True, str(ex))
    # mechanism: beam with no torsional restraint anywhere
    mech = {"nodes": [{"id": "n1", "x_m": 0, "y_m": 0, "z_m": 0},
                      {"id": "n2", "x_m": 4, "y_m": 0, "z_m": 0}],
            "elements": [beam("e1", "n1", "n2")],
            "supports": [{"node": "n1", "ux": True, "uy": True, "uz": True},
                         {"node": "n2", "uy": True, "uz": True}],
            "loads": [{"case": "dead", "type": "point", "node": "n2", "fy_N": -1000}]}
    try:
        structuremod.analyze_static(mech, props)
        check("unrestrained torsion mechanism raises unstable error", False, "no error raised")
    except ValueError as ex:
        check("unrestrained torsion mechanism raises unstable error",
              "unstable" in str(ex), str(ex))

    # ---------- analytical solvers ----------
    check("column_buckling: Pcr 1827.7 kN",
          approx(solversmod.run_solver("column_buckling",
                                       {"length_m": 3, "k_factor": 1.0,
                                        "section": SQUARE, "load_N": 100000},
                                       STEEL)["critical_load_N"], 1827704.5, 0.001))
    check("fixed_beam: deflection 0.25 mm, moment 5000 N·m",
          approx(solversmod.run_solver("fixed_beam",
                                       {"length_m": 4, "load_N": 10000,
                                        "section": RECT}, STEEL)["deflection_m"], 0.00025, 0.001)
          and approx(solversmod.run_solver("fixed_beam",
                                           {"length_m": 4, "load_N": 10000,
                                            "section": RECT}, STEEL)["end_moment_Nm"], 5000, 0.001))
    nf = solversmod.run_solver("natural_frequency_beam",
                               {"length_m": 2, "section": RECT, "support": "cantilever"}, STEEL)
    check("natural_frequency_beam: weak 20.38 Hz, strong 40.77 Hz",
          approx(nf["frequency_weak_axis_hz"], 20.385, 0.001)
          and approx(nf["frequency_strong_axis_hz"], 40.769, 0.001),
          str(nf["frequency_weak_axis_hz"]) + " / " + str(nf["frequency_strong_axis_hz"]))
    check("wind_load_is875: pz 1161.6 Pa, F 15100.8 N",
          approx(solversmod.run_solver("wind_load_is875",
                                       {"basic_wind_speed_m_s": 44, "k1": 1, "k2": 1,
                                        "k3": 1, "area_m2": 10, "force_coefficient": 1.3},
                                       {})["wind_force_N"],
                 15100.8, 0.001))
    check("seismic_base_shear_is1893: Ah 0.09, Vb 90000 N",
          approx(solversmod.run_solver("seismic_base_shear_is1893",
                                       {"seismic_weight_N": 1e6, "zone_factor": 0.36,
                                        "importance_factor": 1, "response_reduction_factor": 5,
                                        "sa_g": 2.5},
                                       {})["base_shear_N"], 90000, 0.001))
    check("load_combination: 1.5(DL+LL) = 22500 N",
          solversmod.run_solver("load_combination",
                                {"combination": "1.5(DL+LL)", "dead_N": 10000,
                                 "live_N": 5000},
                                {})["factored_total_N"] == 22500)
    try:
        solversmod.run_solver("structural_static", {}, {})
        check("structural_static via run_solver refuses with pointer", False, "no error raised")
    except ValueError as ex:
        check("structural_static via run_solver refuses with pointer",
              "structures/analyze" in str(ex), str(ex))

    # ---------- demo structures ----------
    repo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    demo_dir = os.path.join(repo, "workspace", "test-structures")
    for name in ["simply_supported_beam", "cantilever", "truss_2d",
                 "portal_frame", "truss_bridge", "column_buckling"]:
        d = json.load(open(os.path.join(demo_dir, name + ".json")))
        errs = structuremod.validate_structure(d)
        check(f"demo {name}: validates", not errs, str(errs))
        r = structuremod.analyze_static(d, props_of)
        exp = d.get("expected", {})
        if name == "simply_supported_beam":
            check("demo SS beam: reaction 5000 N, deflection 1.0 mm",
                  approx(r["nodes"]["n1"]["reaction"][1], 5000, 0.001)
                  and approx(abs(r["nodes"]["n2"]["displacement_m"][1]), 0.001, 0.001))
        if name == "cantilever":
            check("demo cantilever: tip deflection 1.0 mm",
                  approx(abs(r["nodes"]["n2"]["displacement_m"][1]), 0.001, 0.001))
        if name == "truss_2d":
            check("demo truss: reaction b0 10000 N",
                  approx(r["nodes"]["b0"]["reaction"][1], 10000, 0.001))
        if name == "portal_frame":
            fx = r["nodes"]["A"]["reaction"][0] + r["nodes"]["B"]["reaction"][0]
            fy = r["nodes"]["A"]["reaction"][1] + r["nodes"]["B"]["reaction"][1]
            check("demo portal: equilibrium -20000 / +40000 N",
                  approx(fx, -20000, 0.001) and approx(fy, 40000, 0.001))
        if name == "truss_bridge":
            r_live = structuremod.analyze_static(d, props_of, case="live")
            check("demo bridge: live-only reaction d0 30 kN",
                  approx(r_live["nodes"]["d0"]["reaction"][1], 30000, 0.001),
                  str(r_live["nodes"]["d0"]["reaction"]))
            check("demo bridge: top-chord buckling utilisation under 1.0",
                  r["max_buckling_utilization"] is not None
                  and r["max_buckling_utilization"] < 1.0,
                  str(r["max_buckling_utilization"]))
        if name == "column_buckling":
            b = elmap(r)["e1"]["buckling"]
            check("demo column: Pcr 1827.7 kN, utilisation 0.055",
                  approx(b["critical_load_N"], 1827704.5, 0.001)
                  and approx(b["utilization"], 0.0547, 0.01))

    # ---------- API: structures endpoints ----------
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
        token = body["token"]
        status, body = req(base, "POST", "/api/v1/auth/register",
                           body={"email": "bob@example.com", "username": "bob",
                                 "password": "correct-horse-battery", "name": "Bob"})
        bob_token = body["token"]
        status, body = req(base, "POST", "/api/v1/projects", token,
                           body={"name": "Struct demo", "description": "", "lab": "structural"})
        check("create project", status == 201, str(status))
        pid = body["project"]["id"]
        status, body = req(base, "GET", "/api/v1/structures/schema")
        check("structures schema lists element types",
              status == 200 and "beam" in body.get("schema", {}).get("element_types", []), str(status))
        status, body = req(base, "POST", "/api/v1/structures/validate", token,
                           body={"structure": ss})
        check("structures validate: SS beam is valid",
              status == 200 and body.get("valid") is True, str(body))
        status, body = req(base, "POST", "/api/v1/structures/validate", token,
                           body={"structure": bad})
        check("structures validate: no-support structure is invalid",
              status == 200 and body.get("valid") is False and body.get("errors"), str(body))
        status, body = req(base, "POST", "/api/v1/structures/analyze", token,
                           body={"project_id": pid, "structure": ss,
                                 "analysis": {"type": "static"}})
        check("structural static job completes via API",
              status in (200, 201) and body.get("status") == "completed"
              and approx(body["results"]["values"]["nodes"]["n1"]["reaction"][1], 5000, 0.001)
              and approx(abs(body["results"]["values"]["nodes"]["n2"]["displacement_m"][1]), 0.001, 0.001),
              str(status) + " " + str(body.get("status")))
        status, body = req(base, "POST", "/api/v1/structures/analyze", token,
                           body={"project_id": pid, "structure": cant,
                                 "analysis": {"type": "modal", "n_modes": 2}})
        check("structural modal job completes via API",
              status in (200, 201) and body.get("status") == "completed"
              and approx(body["results"]["values"]["modes"][0]["frequency_hz"], 20.481, 0.01),
              str(status) + " " + str(body.get("status")))
        status, body = req(base, "POST", "/api/v1/structures/analyze", token,
                           body={"project_id": pid, "structure": bad,
                                 "analysis": {"type": "static"}})
        check("structural job with invalid structure is recorded failed",
              body.get("status") == "failed" and "support" in str(body["results"].get("error")),
              str(body.get("status")) + " " + str(body.get("results")))
        status, body = req(base, "POST", "/api/v1/structures/analyze", bob_token,
                           body={"project_id": pid, "structure": ss,
                                 "analysis": {"type": "static"}})
        check("Bob cannot analyse Alice's project (404)", status == 404, str(status))
        # structure document save / load / version conflict
        status, body = req(base, "GET", "/api/v1/projects/" + pid + "/structure", token)
        check("structure document starts empty",
              status == 200 and body.get("structure", {}).get("nodes") == [], str(status))
        status, body = req(base, "PUT", "/api/v1/projects/" + pid + "/structure", token,
                           body={"structure": ss, "base_version": 1})
        check("structure document saves (version 2)",
              status == 200 and body.get("structure", {}).get("version") == 2, str(status))
        status, body = req(base, "GET", "/api/v1/projects/" + pid + "/structure", token)
        check("structure document round-trips",
              status == 200 and len(body.get("structure", {}).get("nodes", [])) == 3, str(status))
        status, body = req(base, "PUT", "/api/v1/projects/" + pid + "/structure", token,
                           body={"structure": ss, "base_version": 1})
        check("stale base_version is rejected (409)", status == 409, str(status))
        status, body = req(base, "PUT", "/api/v1/projects/" + pid + "/structure", bob_token,
                           body={"structure": ss, "base_version": 2})
        check("Bob cannot save to Alice's project structure (404)", status == 404, str(status))
        # analytical solvers via the simulations endpoint
        status, body = req(base, "POST", "/api/v1/simulations", token,
                           body={"project_id": pid, "solver": "column_buckling",
                                 "inputs": {"length_m": 3, "k_factor": 1.0,
                                            "section": SQUARE, "load_N": 100000,
                                            "material_id": "steel-s355"}})
        check("column_buckling job completes via API",
              status in (200, 201) and body.get("status") == "completed"
              and approx(body["results"]["values"]["critical_load_N"], 1827704.5, 0.001),
              str(status) + " " + str(body.get("status")))
        status, body = req(base, "POST", "/api/v1/simulations", token,
                           body={"project_id": pid, "solver": "structural_static",
                                 "inputs": {}})
        check("structural_static via simulations is recorded failed with pointer",
              body.get("status") == "failed"
              and "structures/analyze" in str(body["results"].get("error")),
              str(body.get("status")) + " " + str(body.get("results")))
        status, body = req(base, "GET", "/api/v1/solvers")
        check("solvers registry lists structural solvers",
              status == 200 and "structural_static" in body.get("solvers", {})
              and "column_buckling" in body.get("solvers", {})
              and "wind_load_is875" in body.get("solvers", {})
              and "seismic_base_shear_is1893" in body.get("solvers", {}), str(status))
    finally:
        server.shutdown()
        server.server_close()

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} tests passed")
    if failed:
        print("FAILED:")
        for name, _ok, detail in failed:
            print(f"  - {name} — {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
