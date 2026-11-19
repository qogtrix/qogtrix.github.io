"""Stage 8 tests — MNA circuit solver, electrical analytical solvers,
demo circuits, and the circuit API.

Stdlib only. Real backend on a temporary database, real HTTP.
Circuit results are checked against hand-computed reference values
(and against the analytical solvers, which must agree with the MNA
solver: RC tau, RLC resonance).

Run:  cd backend && python3 test_stage8.py
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
import circuit as circuitmod  # noqa: E402
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
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def approx(a, b, rel=0.01):
    return a is not None and abs(a - b) <= rel * abs(b)


DIVIDER = {"components": [
    {"id": "V1", "type": "voltage_source", "nodes": ["in", "0"], "params": {"value": 10}},
    {"id": "R1", "type": "resistor", "nodes": ["in", "out"], "params": {"value": 1000, "rating_W": 0.25}},
    {"id": "R2", "type": "resistor", "nodes": ["out", "0"], "params": {"value": 1000, "rating_W": 0.25}},
]}
RC = {"components": [
    {"id": "V1", "type": "voltage_source", "nodes": ["in", "0"], "params": {"value": 5, "waveform": "step", "amplitude": 5}},
    {"id": "R1", "type": "resistor", "nodes": ["in", "out"], "params": {"value": 1000}},
    {"id": "C1", "type": "capacitor", "nodes": ["out", "0"], "params": {"value": 1e-6}},
]}
RLC = {"components": [
    {"id": "V1", "type": "voltage_source", "nodes": ["in", "0"], "params": {"value": 1, "waveform": "sine", "amplitude": 1, "frequency": 5032.9}},
    {"id": "R1", "type": "resistor", "nodes": ["in", "a"], "params": {"value": 100}},
    {"id": "L1", "type": "inductor", "nodes": ["a", "b"], "params": {"value": 0.01}},
    {"id": "C1", "type": "capacitor", "nodes": ["b", "0"], "params": {"value": 100e-9}},
]}
RECT = {"components": [
    {"id": "V1", "type": "voltage_source", "nodes": ["in", "0"], "params": {"value": 0, "waveform": "sine", "amplitude": 10, "frequency": 50}},
    {"id": "D1", "type": "diode", "nodes": ["in", "out"], "params": {"is": 1e-14, "n": 1}},
    {"id": "R1", "type": "resistor", "nodes": ["out", "0"], "params": {"value": 1000}},
]}


def main():
    tmp = tempfile.mkdtemp(prefix="aielab-stage8-test-")
    os.environ["AIELAB_DB"] = os.path.join(tmp, "test.db")
    os.environ["AIELAB_SECRET"] = "test-secret-for-stage8-only"
    conn = dbmod.connect(os.environ["AIELAB_DB"])
    dbmod.init_db(conn)
    dbmod.seed_materials(conn)
    conn.close()

    def props_of(mid):
        conn = dbmod.connect(os.environ["AIELAB_DB"])
        m = dbmod.fetch_material(conn, mid)
        conn.close()
        return m["properties"]

    copper = props_of("copper-c110")
    wool = props_of("mineral-wool")
    check("copper has recorded resistivity 1.72e-8 ohm·m",
          copper.get("electrical_resistivity_ohm_m") == 1.72e-8,
          str(copper.get("electrical_resistivity_ohm_m")))
    check("mineral wool has no resistivity on record",
          wool.get("electrical_resistivity_ohm_m") is None)

    # ---------- MNA: DC ----------
    r = circuitmod.simulate_dc(DIVIDER)
    check("divider DC: Vout 5.0 V", approx(r["voltages"]["out"], 5.0, 0.001))
    check("divider DC: R1 dissipates 25 mW",
          approx(r["power"]["R1"], 0.025, 0.01))
    check("divider DC: source supplies 50 mW",
          approx(r["power"]["V1"], -0.05, 0.01))

    # ---------- MNA: transient RC ----------
    r = circuitmod.simulate_transient(RC, 0.005, 500)
    rc_v = r["voltages"]["out"]
    check("RC transient: Vout(0) = 0 (uncharged capacitor)",
          abs(rc_v[0]) < 1e-9, str(rc_v[0]))
    check("RC transient: Vout(1 ms) = 3.16 V (one tau)",
          approx(rc_v[100], 3.1606, 0.01), str(rc_v[100]))
    check("RC transient: Vout(5 ms) = 4.97 V (five tau)",
          approx(rc_v[500], 4.9663, 0.01), str(rc_v[500]))
    check("RC transient: 501 time points", len(r["t"]) == 501)

    # ---------- MNA: AC RLC ----------
    r = circuitmod.simulate_ac(RLC, 4000, 6000, 5)
    peak = max(r["magnitude_v"]["b"])
    check("RLC AC: peak |Vc| 3.16 near resonance",
          approx(peak, 3.162, 0.05), str(peak))
    check("RLC AC: |Vc| falls off resonance",
          r["magnitude_v"]["b"][0] < peak and r["magnitude_v"]["b"][-1] < peak)

    # ---------- MNA: rectifier ----------
    r = circuitmod.simulate_transient(RECT, 0.04, 400)
    v = r["voltages"]["out"]
    check("rectifier: peak 9.29 V", approx(max(v), 9.29, 0.01), str(max(v)))
    check("rectifier: mean 2.84 V over two cycles",
          approx(sum(v) / len(v), 2.84, 0.05), str(sum(v) / len(v)))
    check("rectifier: no negative output (half-wave)",
          min(v) >= -0.01, str(min(v)))

    # ---------- MNA: BJT / op-amp / MOSFET / switch ----------
    bjt = {"components": [
        {"id": "VCC", "type": "voltage_source", "nodes": ["vcc", "0"], "params": {"value": 12}},
        {"id": "VB", "type": "voltage_source", "nodes": ["vb", "0"], "params": {"value": 5}},
        {"id": "RB", "type": "resistor", "nodes": ["vb", "b"], "params": {"value": 100000}},
        {"id": "RC", "type": "resistor", "nodes": ["vcc", "c"], "params": {"value": 1000}},
        {"id": "Q1", "type": "npn", "nodes": ["c", "b", "0"], "params": {"is": 1e-15, "beta": 100}},
    ]}
    r = circuitmod.simulate_dc(bjt)
    check("BJT: collector 7.63 V", approx(r["voltages"]["c"], 7.633, 0.01), str(r["voltages"]["c"]))
    check("BJT: base 0.63 V", approx(r["voltages"]["b"], 0.633, 0.02), str(r["voltages"]["b"]))

    opamp = {"components": [
        {"id": "VIN", "type": "voltage_source", "nodes": ["in", "0"], "params": {"value": 0.5}},
        {"id": "OP", "type": "opamp", "nodes": ["out", "np", "nm", "vp", "vm"], "params": {"gain": 100000}},
        {"id": "R1", "type": "resistor", "nodes": ["nm", "0"], "params": {"value": 1000}},
        {"id": "R2", "type": "resistor", "nodes": ["out", "nm"], "params": {"value": 10000}},
        {"id": "W1", "type": "voltage_source", "nodes": ["np", "in"], "params": {"value": 0}},
        {"id": "VP", "type": "voltage_source", "nodes": ["vp", "0"], "params": {"value": 15}},
        {"id": "VM", "type": "voltage_source", "nodes": ["vm", "0"], "params": {"value": -15}},
    ]}
    r = circuitmod.simulate_dc(opamp)
    check("op-amp non-inverting gain 11: Vout 5.5 V",
          approx(r["voltages"]["out"], 5.5, 0.002), str(r["voltages"]["out"]))

    nmos = {"components": [
        {"id": "VDD", "type": "voltage_source", "nodes": ["vdd", "0"], "params": {"value": 5}},
        {"id": "VG", "type": "voltage_source", "nodes": ["g", "0"], "params": {"value": 3}},
        {"id": "RD", "type": "resistor", "nodes": ["vdd", "d"], "params": {"value": 1000}},
        {"id": "M1", "type": "nmos", "nodes": ["d", "g", "0"], "params": {"kp": 0.001, "vth": 1, "lambda": 0}},
    ]}
    r = circuitmod.simulate_dc(nmos)
    check("NMOS saturation: Vd 3.0 V", approx(r["voltages"]["d"], 3.0, 0.01), str(r["voltages"]["d"]))

    pmos = {"components": [
        {"id": "VDD", "type": "voltage_source", "nodes": ["vdd", "0"], "params": {"value": 5}},
        {"id": "VG", "type": "voltage_source", "nodes": ["g", "0"], "params": {"value": 2}},
        {"id": "RD", "type": "resistor", "nodes": ["d", "0"], "params": {"value": 1000}},
        {"id": "M1", "type": "pmos", "nodes": ["d", "g", "vdd"], "params": {"kp": 0.001, "vth": 1, "lambda": 0}},
    ]}
    r = circuitmod.simulate_dc(pmos)
    check("PMOS saturation: Vd 2.0 V", approx(r["voltages"]["d"], 2.0, 0.01), str(r["voltages"]["d"]))

    sw = {"components": [
        {"id": "V1", "type": "voltage_source", "nodes": ["in", "0"], "params": {"value": 5}},
        {"id": "S1", "type": "switch", "nodes": ["in", "out"], "params": {"closed": True}},
        {"id": "R1", "type": "resistor", "nodes": ["out", "0"], "params": {"value": 1000}},
    ]}
    check("switch closed: Vout 5 V",
          approx(circuitmod.simulate_dc(sw)["voltages"]["out"], 5.0, 0.001))
    sw["components"][1]["params"]["closed"] = False
    check("switch open: Vout ~0 V (5 uV through the 1 GOhm open switch)",
          abs(circuitmod.simulate_dc(sw)["voltages"]["out"]) < 1e-4)

    # ---------- MNA: editor-style wires (union-find) ----------
    wired = {"components": [
        {"id": "V1", "type": "voltage_source", "nodes": ["V1:0", "V1:1"], "params": {"value": 10}},
        {"id": "R1", "type": "resistor", "nodes": ["R1:0", "R1:1"], "params": {"value": 1000}},
        {"id": "R2", "type": "resistor", "nodes": ["R2:0", "R2:1"], "params": {"value": 1000}},
        {"id": "G1", "type": "ground", "nodes": ["G1:0"], "params": {}},
    ], "connections": [
        {"a": {"comp": "V1", "term": 0}, "b": {"comp": "R1", "term": 0}},
        {"a": {"comp": "R1", "term": 1}, "b": {"comp": "R2", "term": 0}},
        {"a": {"comp": "R2", "term": 1}, "b": {"comp": "V1", "term": 1}},
        {"a": {"comp": "V1", "term": 1}, "b": {"comp": "G1", "term": 0}},
    ]}
    check("editor wires: divider resolves to 5.0 V",
          approx(circuitmod.simulate_dc(wired)["voltages"]["n2"], 5.0, 0.001)
          if "n2" in circuitmod.simulate_dc(wired)["voltages"] else False,
          str(circuitmod.simulate_dc(wired)["voltages"]))

    # ---------- MNA: validation and safety ----------
    bad = {"components": [
        {"id": "V1", "type": "voltage_source", "nodes": ["in", "x"], "params": {"value": 5}},
        {"id": "R1", "type": "resistor", "nodes": ["in", "x"], "params": {"value": 100}},
    ]}
    errs = circuitmod.validate_circuit(bad)
    check("validation: circuit with no ground is rejected",
          any("ground" in e for e in errs), str(errs))
    dup = {"components": [
        {"id": "R1", "type": "resistor", "nodes": ["a", "0"], "params": {"value": 100}},
        {"id": "R1", "type": "resistor", "nodes": ["a", "0"], "params": {"value": 100}},
    ]}
    check("validation: duplicate id is rejected",
          any("duplicate" in e for e in circuitmod.validate_circuit(dup)))
    neg = {"components": [
        {"id": "R1", "type": "resistor", "nodes": ["a", "0"], "params": {"value": -5}},
    ]}
    check("validation: negative resistance is rejected",
          bool(circuitmod.validate_circuit(neg)))
    loop = {"components": [
        {"id": "V1", "type": "voltage_source", "nodes": ["a", "0"], "params": {"value": 5}},
        {"id": "V2", "type": "voltage_source", "nodes": ["a", "0"], "params": {"value": 5}},
    ]}
    try:
        circuitmod.simulate_dc(loop)
        check("voltage-source loop: refused (singular)", False, "no error raised")
    except ValueError as e:
        check("voltage-source loop: refused (singular)", "singular" in str(e), str(e))

    hot = {"components": [
        {"id": "V1", "type": "voltage_source", "nodes": ["in", "0"], "params": {"value": 100}},
        {"id": "R1", "type": "resistor", "nodes": ["in", "out"], "params": {"value": 1000}},
        {"id": "R2", "type": "resistor", "nodes": ["out", "0"], "params": {"value": 1000}},
    ]}
    r = circuitmod.simulate_dc(hot)
    check("safety: 100 V node is flagged hazardous",
          any("Hazardous" in w for w in r["warnings"]), str(r["warnings"]))
    overload = {"components": [
        {"id": "V1", "type": "voltage_source", "nodes": ["in", "0"], "params": {"value": 10}},
        {"id": "R1", "type": "resistor", "nodes": ["in", "0"], "params": {"value": 10, "rating_W": 0.25}},
    ]}
    r = circuitmod.simulate_dc(overload)
    check("safety: 10 W in a 0.25 W resistor is flagged",
          any("overheat" in w for w in r["warnings"]), str(r["warnings"]))

    # ---------- analytical electrical solvers ----------
    o = solversmod.run_solver("ohm_law", {"voltage_V": 12, "resistance_ohm": 4}, {})
    check("ohm_law: 12 V / 4 ohm = 3 A, 36 W",
          approx(o["current_A"], 3.0, 0.001) and approx(o["power_W"], 36.0, 0.001))
    try:
        solversmod.run_solver("ohm_law", {"voltage_V": 12}, {})
        check("ohm_law: one value only is refused", False)
    except ValueError:
        check("ohm_law: one value only is refused", True)
    rc = solversmod.run_solver("rc_time_constant",
                               {"resistance_ohm": 1000, "capacitance_F": 1e-6, "voltage_V": 5}, {})
    check("rc_time_constant: tau 1 ms, cutoff 159.15 Hz, V(tau) 3.16 V",
          approx(rc["tau_s"], 0.001, 0.001) and approx(rc["cutoff_hz"], 159.15, 0.001)
          and approx(rc["voltage_at_tau_V"], 3.1606, 0.001))
    check("analytical RC agrees with the MNA transient at one tau",
          approx(rc["voltage_at_tau_V"], rc_v[100], 0.01), str(rc_v[100]))
    rl = solversmod.run_solver("rlc_resonance",
                               {"resistance_ohm": 100, "inductance_H": 0.01, "capacitance_F": 100e-9}, {})
    check("rlc_resonance: f0 5032.9 Hz, Q 3.162",
          approx(rl["resonant_freq_hz"], 5032.9, 0.001) and approx(rl["quality_factor"], 3.162, 0.001))
    check("analytical RLC Q agrees with the MNA AC peak",
          approx(rl["quality_factor"], peak, 0.05), str(peak))
    ap = solversmod.run_solver("ac_power",
                               {"voltage_rms_V": 230, "current_rms_A": 5, "power_factor": 0.9}, {})
    check("ac_power: S 1150 VA, P 1035 W, Q 501 var",
          approx(ap["apparent_power_VA"], 1150, 0.001) and approx(ap["real_power_W"], 1035, 0.001)
          and approx(ap["reactive_power_var"], 501.27, 0.001))
    tf = solversmod.run_solver("transformer",
                               {"primary_voltage_V": 230, "turns_primary": 460,
                                "turns_secondary": 24, "efficiency": 0.95, "load_power_W": 100}, {})
    check("transformer: 230 V -> 12 V, secondary 8.33 A",
          approx(tf["secondary_voltage_V"], 12.0, 0.001) and approx(tf["secondary_current_A"], 8.333, 0.001))
    mo = solversmod.run_solver("dc_motor",
                               {"voltage_V": 12, "resistance_ohm": 1.5, "kt_Nm_per_A": 0.05,
                                "ke_V_per_rad_s": 0.05, "load_torque_Nm": 0.1}, {})
    check("dc_motor: stall 8 A / 0.4 Nm, no-load 2292 rpm",
          approx(mo["stall_current_A"], 8.0, 0.001) and approx(mo["stall_torque_Nm"], 0.4, 0.001)
          and approx(mo["no_load_speed_rpm"], 2291.8, 0.001))
    check("dc_motor: at 0.1 Nm -> 2 A, 1719 rpm, 75%",
          approx(mo["current_A"], 2.0, 0.001) and approx(mo["speed_rpm"], 1718.9, 0.001)
          and approx(mo["efficiency"], 0.75, 0.001))
    try:
        solversmod.run_solver("dc_motor",
                              {"voltage_V": 12, "resistance_ohm": 1.5, "kt_Nm_per_A": 0.05,
                               "ke_V_per_rad_s": 0.05, "load_torque_Nm": 1.0}, {})
        check("dc_motor: overload is refused", False)
    except ValueError:
        check("dc_motor: overload is refused", True)
    mg = solversmod.run_solver("motor_gearbox",
                               {"voltage_V": 12, "resistance_ohm": 1.5, "kt_Nm_per_A": 0.05,
                                "ke_V_per_rad_s": 0.05, "load_torque_Nm": 0.2,
                                "gear_ratio": 2, "gear_efficiency": 0.95}, {})
    check("motor+gearbox: output 844 rpm, 0.2 Nm, 70% overall",
          approx(mg["output_speed_rpm"], 844.4, 0.001) and approx(mg["output_torque_Nm"], 0.2, 0.001)
          and approx(mg["efficiency"], 0.70, 0.001))
    ba = solversmod.run_solver("battery_config",
                               {"cell_voltage_V": 3.7, "cell_capacity_Ah": 2.6,
                                "series": 4, "parallel": 2, "load_current_A": 2}, {})
    check("battery 4s2p: 14.8 V, 5.2 Ah, 76.96 Wh, 2.6 h",
          approx(ba["total_voltage_V"], 14.8, 0.001) and approx(ba["total_capacity_Ah"], 5.2, 0.001)
          and approx(ba["energy_Wh"], 76.96, 0.001) and approx(ba["runtime_h"], 2.6, 0.001))
    so = solversmod.run_solver("solenoid",
                               {"turns": 500, "length_m": 0.1, "area_m2": 1e-4,
                                "mu_r": 1, "current_A": 2}, {})
    check("solenoid: L 0.314 mH, B 12.57 mT",
          approx(so["inductance_H"], 0.00031416, 0.001) and approx(so["field_T"], 0.012566, 0.001))
    wr = solversmod.run_solver("wire_resistance",
                               {"material_id": "copper-c110", "length_m": 10,
                                "area_mm2": 1.5, "current_A": 5}, copper)
    check("wire_resistance (copper): 10 m / 1.5 mm2 = 0.115 ohm, 0.57 V drop",
          approx(wr["resistance_ohm"], 0.11467, 0.001) and approx(wr["voltage_drop_V"], 0.5733, 0.001))
    try:
        solversmod.run_solver("wire_resistance",
                              {"material_id": "mineral-wool", "length_m": 10,
                               "area_mm2": 1.5, "current_A": 5}, wool)
        check("wire_resistance: material without resistivity is refused", False)
    except ValueError as e:
        check("wire_resistance: material without resistivity is refused",
              "not on record" in str(e), str(e))
    sp = solversmod.run_solver("series_parallel",
                               {"kind": "resistor", "mode": "parallel", "values": [100, 100]}, {})
    check("series_parallel: 100 || 100 = 50 ohm", approx(sp["equivalent"], 50, 0.001))
    sp = solversmod.run_solver("series_parallel",
                               {"kind": "capacitor", "mode": "series", "values": [10e-6, 10e-6]}, {})
    check("series_parallel: 10uF in series with 10uF = 5uF", approx(sp["equivalent"], 5e-6, 0.001))

    # ---------- demo circuits ----------
    repo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    for name, kind in [("voltage_divider", "dc"), ("rc_circuit", "transient"),
                       ("rlc_circuit", "ac"), ("rectifier", "transient")]:
        with open(os.path.join(repo, "workspace", "test-circuits", name + ".json")) as f:
            d = json.load(f)
        check(f"demo circuit {name} validates", not circuitmod.validate_circuit(d),
              str(circuitmod.validate_circuit(d)))
    d = json.load(open(os.path.join(repo, "workspace", "test-circuits", "voltage_divider.json")))
    check("demo divider: Vout 5.0 V",
          approx(circuitmod.simulate_dc(d)["voltages"]["out"], 5.0, 0.001))
    d = json.load(open(os.path.join(repo, "workspace", "test-circuits", "rc_circuit.json")))
    check("demo RC: Vout(1 ms) 3.15 V",
          approx(circuitmod.simulate_transient(d, 0.005, 500)["voltages"]["out"][100], 3.15, 0.01))
    d = json.load(open(os.path.join(repo, "workspace", "test-circuits", "rlc_circuit.json")))
    check("demo RLC: AC peak 3.2 V",
          approx(max(circuitmod.simulate_ac(d, 4000, 6000, 5)["magnitude_v"]["b"]), 3.16, 0.05))
    d = json.load(open(os.path.join(repo, "workspace", "test-circuits", "rectifier.json")))
    check("demo rectifier: peak 9.29 V",
          approx(max(circuitmod.simulate_transient(d, 0.04, 400)["voltages"]["out"]), 9.29, 0.01))
    d = json.load(open(os.path.join(repo, "workspace", "test-circuits", "dc_motor.json")))
    check("demo dc_motor params: 75% at 0.1 Nm",
          approx(solversmod.run_solver(d["solver"], d["inputs"], {})["efficiency"], 0.75, 0.001))
    d = json.load(open(os.path.join(repo, "workspace", "test-circuits", "battery_pack.json")))
    check("demo battery pack: 76.96 Wh",
          approx(solversmod.run_solver(d["solver"], d["inputs"], {})["energy_Wh"], 76.96, 0.001))

    # ---------- API: circuit endpoints ----------
    server = ThreadingHTTPServer(("127.0.0.1", 0), appmod.Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        status, body = req(base, "GET", "/health")
        check("health reports stage 8 or later", body.get("stage") in (8, 9, 10, 11), str(body))
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
                           body={"name": "Elec demo", "description": "", "lab": "electrical"})
        check("create project", status == 201, str(status))
        pid = body["project"]["id"]
        status, body = req(base, "GET", "/api/v1/circuits/schema")
        check("circuit schema lists component types",
              status == 200 and "resistor" in body.get("schema", {}).get("component_types", []), str(status))
        status, body = req(base, "POST", "/api/v1/circuits/validate", token,
                           body={"circuit": DIVIDER})
        check("circuit validate: divider is valid",
              status == 200 and body.get("valid") is True, str(body))
        status, body = req(base, "POST", "/api/v1/circuits/validate", token,
                           body={"circuit": bad})
        check("circuit validate: no-ground circuit is invalid",
              status == 200 and body.get("valid") is False and body.get("errors"), str(body))
        status, body = req(base, "POST", "/api/v1/circuits/simulate", token,
                           body={"project_id": pid, "circuit": DIVIDER, "analysis": {"type": "dc"}})
        check("circuit DC job completes via API",
              status in (200, 201) and body.get("status") == "completed"
              and approx(body["results"]["values"]["voltages"]["out"], 5.0, 0.001),
              str(status) + " " + str(body.get("status")))
        status, body = req(base, "POST", "/api/v1/circuits/simulate", token,
                           body={"project_id": pid, "circuit": RC,
                                 "analysis": {"type": "transient", "duration": 0.005, "steps": 200}})
        check("circuit transient job completes via API",
              status in (200, 201) and body.get("status") == "completed"
              and len(body["results"]["values"]["t"]) == 201,
              str(status) + " " + str(body.get("status")))
        status, body = req(base, "POST", "/api/v1/circuits/simulate", token,
                           body={"project_id": pid, "circuit": RLC,
                                 "analysis": {"type": "ac", "f_start": 4000, "f_stop": 6000, "points": 5}})
        check("circuit AC job completes via API",
              status in (200, 201) and body.get("status") == "completed"
              and len(body["results"]["values"]["frequencies_hz"]) == 5,
              str(status) + " " + str(body.get("status")))
        status, body = req(base, "POST", "/api/v1/circuits/simulate", token,
                           body={"project_id": pid, "circuit": bad, "analysis": {"type": "dc"}})
        check("circuit job with no ground is recorded failed",
              body.get("status") == "failed" and "ground" in str(body["results"].get("error")),
              str(body.get("status")) + " " + str(body.get("results")))
        status, body = req(base, "POST", "/api/v1/circuits/simulate", bob_token,
                           body={"project_id": pid, "circuit": DIVIDER, "analysis": {"type": "dc"}})
        check("Bob cannot simulate on Alice's project (404)",
              status == 404, str(status))
        status, body = req(base, "POST", "/api/v1/simulations", token,
                           body={"project_id": pid, "solver": "dc_motor",
                                 "inputs": {"voltage_V": 12, "resistance_ohm": 1.5,
                                            "kt_Nm_per_A": 0.05, "ke_V_per_rad_s": 0.05,
                                            "load_torque_Nm": 0.1}})
        check("dc_motor job completes via API",
              status in (200, 201) and body.get("status") == "completed"
              and approx(body["results"]["values"]["efficiency"], 0.75, 0.001),
              str(status) + " " + str(body.get("status")))
        status, body = req(base, "POST", "/api/v1/simulations", token,
                           body={"project_id": pid, "solver": "wire_resistance",
                                 "inputs": {"material_id": "copper-c110", "length_m": 10,
                                            "area_mm2": 1.5, "current_A": 5}})
        check("wire_resistance job completes via API (copper)",
              status in (200, 201) and body.get("status") == "completed"
              and approx(body["results"]["values"]["resistance_ohm"], 0.11467, 0.001),
              str(status) + " " + str(body.get("status")))
        status, body = req(base, "POST", "/api/v1/simulations", token,
                           body={"project_id": pid, "solver": "wire_resistance",
                                 "inputs": {"material_id": "mineral-wool", "length_m": 10,
                                            "area_mm2": 1.5, "current_A": 5}})
        check("wire_resistance job with missing data is recorded failed",
              body.get("status") == "failed"
              and "is not on record" in str(body["results"].get("error")),
              str(body.get("status")))
        status, body = req(base, "GET", "/api/v1/solvers")
        check("solvers registry lists circuit and electrical solvers",
              status == 200 and "circuit_dc" in body.get("solvers", {})
              and "ohm_law" in body.get("solvers", {})
              and "motor_gearbox" in body.get("solvers", {}), str(status))
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
