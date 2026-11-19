"""Stage 5 tests — 3D modelling: model API, validation, volumes,
version-aware saves, material assignment, test-model files.

Stdlib only. Real backend on a temporary database, real HTTP.

Run:  cd backend && python3 test_stage5.py
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


def box_model():
    return {"version": 1, "units": "mm", "components": [
        {"id": "b1", "name": "Block", "type": "primitive", "kind": "box",
         "params": {"length": 10, "width": 20, "height": 30},
         "position": [0, 0, 0], "rotation": [0, 0, 0],
         "material_id": "steel-s355", "visible": True,
         "parent_id": None, "tolerance_mm": 0.1}]}


def main():
    tmp = tempfile.mkdtemp(prefix="aielab-stage5-test-")
    os.environ["AIELAB_DB"] = os.path.join(tmp, "test.db")
    os.environ["AIELAB_SECRET"] = "test-secret-for-stage5-only"
    conn = dbmod.connect(os.environ["AIELAB_DB"])
    dbmod.init_db(conn)
    conn.close()

    server = ThreadingHTTPServer(("127.0.0.1", 0), appmod.Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    test_models_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "workspace", "test-models")

    try:
        # --- schema + health ---
        s, h = req(base, "GET", "/health")
        check("health endpoint (stage 5)", s == 200 and h.get("stage") in (5, 6), f"HTTP {s}")
        s, sc = req(base, "GET", "/api/v1/model/schema")
        check("model schema lists primitives, components, units",
              s == 200 and "box" in sc["schema"]["primitive_kinds"]
              and "gear" in sc["schema"]["component_kinds"]
              and "in" in sc["schema"]["units"], "")

        # --- analytic volumes (pure math) ---
        v = modelmod.analytic_volume({"kind": "box", "params": {"length": 10, "width": 20, "height": 30}})
        check("analytic volume: box 10x20x30 = 6000 mm3",
              v["value"] == 6000 and v["exact"], f"got {v}")
        v = modelmod.analytic_volume({"kind": "cylinder", "params": {"radius": 5, "height": 20}})
        check("analytic volume: cylinder r5 h20 = 500pi",
              abs(v["value"] - 500 * math.pi) < 0.01 and v["exact"], f"got {v['value']}")
        v = modelmod.analytic_volume({"kind": "sphere", "params": {"radius": 10}})
        check("analytic volume: sphere r10 = 4000pi/3",
              abs(v["value"] - 4000 * math.pi / 3) < 0.01, f"got {v['value']}")
        v = modelmod.analytic_volume({"kind": "extrude",
                                      "params": {"profile": [[0, 0], [10, 0], [10, 10], [0, 10]], "depth": 5}})
        check("analytic volume: extrude 10x10 square x5 = 500",
              v["value"] == 500, f"got {v['value']}")
        v = modelmod.analytic_volume({"kind": "revolve",
                                      "params": {"profile": [[0, 0], [10, 0], [10, 10], [0, 10]], "angle": 360}})
        check("analytic volume: revolve square (Pappus) = 1000pi",
              abs(v["value"] - 1000 * math.pi) < 0.01, f"got {v['value']}")
        v = modelmod.analytic_volume({"kind": "boolean", "params": {"op": "subtract", "operands": ["a", "b"]}})
        check("analytic volume: boolean returns null (needs mesh)",
              v["value"] is None and not v["exact"], "")
        check("unit conversion: 1 inch = 25.4 mm",
              abs(modelmod.convert(1, "in", "mm") - 25.4) < 1e-9, "")

        # --- validation errors ---
        bad = box_model()
        bad["components"][0]["params"]["length"] = -5
        check("validation: negative dimension rejected",
              bool(modelmod.validate_model(bad)), "")
        bad = box_model()
        bad["components"][0]["kind"] = "pyramid"
        check("validation: unknown kind rejected",
              bool(modelmod.validate_model(bad)), "")
        bad = box_model()
        bad["components"][0]["material_id"] = "unobtainium"
        check("validation: unknown material rejected",
              bool(modelmod.validate_model(bad, {"steel-s355"})), "")
        bad = box_model()
        bad["components"].append({"id": "bool1", "name": "Cut", "type": "boolean", "kind": "boolean",
                                  "params": {"op": "subtract", "operands": ["b1", "missing"]}})
        check("validation: boolean with missing operand rejected",
              bool(modelmod.validate_model(bad)), "")
        bad = box_model()
        bad["components"][0]["parent_id"] = "b1"
        check("validation: parent cycle rejected",
              bool(modelmod.validate_model(bad)), "")
        check("validation: valid box model passes",
              modelmod.validate_model(box_model(), {"steel-s355"}) == [], "")

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
                   body={"name": "Shaft Study", "description": "Stage 5 test",
                         "lab": "mechanical"})
        pid = p["project"]["id"]

        # --- model save / reopen / version ---
        s, got = req(base, "GET", f"/api/v1/projects/{pid}/model", token=alice)
        check("new project has empty model (version 0)",
              s == 200 and got["model"]["version"] == 0 and got["model"]["components"] == [], "")
        s, saved = req(base, "PUT", f"/api/v1/projects/{pid}/model", token=alice,
                       body={"model": box_model(), "base_version": 0})
        check("save box model → version 1",
              s == 200 and saved["model"]["version"] == 1, f"HTTP {s}")
        check("saved model reports volume 6000 + mass from steel density",
              s == 200 and saved["volumes"][0]["volume_mm3"] == 6000
              and abs(saved["volumes"][0]["mass_kg"] - 6000 / 1e9 * 7850) < 1e-9, "")
        s, got = req(base, "GET", f"/api/v1/projects/{pid}/model", token=alice)
        check("reopen returns the saved model",
              s == 200 and got["model"]["components"][0]["id"] == "b1", "")
        s, _ = req(base, "PUT", f"/api/v1/projects/{pid}/model", token=alice,
                   body={"model": box_model(), "base_version": 0})
        check("stale base_version → 409 conflict",
              s == 409, f"HTTP {s}")
        s, _ = req(base, "PUT", f"/api/v1/projects/{pid}/model", token=bob,
                   body={"model": box_model(), "base_version": 1})
        check("Bob cannot save into Alice's project (404)", s == 404, f"HTTP {s}")
        s, _ = req(base, "PUT", f"/api/v1/projects/{pid}/model",
                   body={"model": box_model(), "base_version": 1})
        check("unauthenticated model save → 401", s == 401, f"HTTP {s}")
        bad_model = box_model()
        bad_model["components"][0]["params"]["length"] = 0
        s, _ = req(base, "PUT", f"/api/v1/projects/{pid}/model", token=alice,
                   body={"model": bad_model, "base_version": 1})
        check("invalid model rejected with 400 (no save)",
              s == 400, f"HTTP {s}")
        s, got = req(base, "GET", f"/api/v1/projects/{pid}/model", token=alice)
        check("rejected save did not change the stored model",
              got["model"]["version"] == 1, "")

        # --- validate endpoint (no save) ---
        s, val = req(base, "POST", f"/api/v1/projects/{pid}/model/validate", token=alice,
                     body={"model": box_model()})
        check("validate endpoint: valid model, volumes included",
              s == 200 and val["valid"] and val["volumes"][0]["volume_mm3"] == 6000, "")
        s, val = req(base, "POST", f"/api/v1/projects/{pid}/model/validate", token=alice,
                     body={"model": bad_model})
        check("validate endpoint: invalid model lists errors",
              s == 200 and not val["valid"] and val["errors"], "")

        # --- component add / patch / delete ---
        gear = {"id": "g1", "name": "Gear 24T", "type": "component", "kind": "gear",
                "params": {"module": 2, "teeth": 24, "thickness": 12, "bore_diameter": 10},
                "material_id": "steel-1045"}
        s, added = req(base, "POST", f"/api/v1/projects/{pid}/model/components", token=alice,
                       body={"component": gear})
        check("add gear component → version 2",
              s == 201 and added["model"]["version"] == 2
              and len(added["model"]["components"]) == 2, f"HTTP {s}")
        s, patched = req(base, "PATCH", f"/api/v1/projects/{pid}/model/components/g1",
                         token=alice, body={"params": {"module": 2, "teeth": 24, "thickness": 15, "bore_diameter": 10}})
        check("modify gear thickness 12→15",
              s == 200 and patched["component"]["params"]["thickness"] == 15
              and patched["model"]["version"] == 3, f"HTTP {s}")
        s, _ = req(base, "PATCH", f"/api/v1/projects/{pid}/model/components/g1",
                   token=alice, body={"params": {"module": 2, "teeth": 3, "thickness": 15}})
        check("invalid patch (teeth 3) rejected 400",
              s == 400, f"HTTP {s}")
        s, _ = req(base, "PATCH", f"/api/v1/projects/{pid}/model/components/g1",
                   token=bob, body={"params": {"module": 2, "teeth": 24, "thickness": 15}})
        check("Bob cannot patch Alice's component (404)", s == 404, f"HTTP {s}")
        s, deleted = req(base, "DELETE", f"/api/v1/projects/{pid}/model/components/g1", token=alice)
        check("delete gear component → version 4",
              s == 200 and deleted["model"]["version"] == 4
              and len(deleted["model"]["components"]) == 1, f"HTTP {s}")
        s, _ = req(base, "DELETE", f"/api/v1/projects/{pid}/model/components/nope", token=alice)
        check("delete unknown component → 404", s == 404, f"HTTP {s}")

        # --- material assignment persists ---
        s, patched = req(base, "PATCH", f"/api/v1/projects/{pid}/model/components/b1",
                         token=alice, body={"material_id": "alu-6061-t6"})
        check("assign material 6061-T6 to the box",
              s == 200 and patched["component"]["material_id"] == "alu-6061-t6", "")
        s, got = req(base, "GET", f"/api/v1/projects/{pid}/model", token=alice)
        check("material assignment persists after reopen",
              got["model"]["components"][0]["material_id"] == "alu-6061-t6", "")
        check("mass uses the new material density (2700)",
              abs(got["volumes"][0]["mass_kg"] - 6000 / 1e9 * 2700) < 1e-9, "")

        # --- duplicate project preserves the model ---
        s, dup = req(base, "POST", f"/api/v1/projects/{pid}/duplicate", token=alice)
        dup_id = dup["project"]["id"]
        s, got = req(base, "GET", f"/api/v1/projects/{dup_id}/model", token=alice)
        check("duplicate project keeps the model + material",
              s == 200 and got["model"]["components"][0]["material_id"] == "alu-6061-t6"
              and got["model"]["version"] == 5, "")

        # --- export (JSON) ---
        s, exp = req(base, "GET", f"/api/v1/projects/{pid}/model/export?format=json", token=alice)
        check("export JSON returns model + volumes",
              s == 200 and exp["model"]["components"][0]["id"] == "b1"
              and exp["volumes"][0]["volume_mm3"] == 6000, "")
        s, _ = req(base, "GET", f"/api/v1/projects/{pid}/model/export?format=step", token=alice)
        check("STEP export honestly refused (400, browser formats only)",
              s == 400, f"HTTP {s}")

        # --- the 5 test-model files: valid + volumes sane ---
        for name in ("shaft", "gear", "gearbox", "beam", "multi-component"):
            with open(os.path.join(test_models_dir, name + ".json")) as f:
                m = json.load(f)
            errors = modelmod.validate_model(m, None)
            vols = [modelmod.analytic_volume(c)["value"] for c in m["components"]]
            check(f"test model '{name}' is valid",
                  not errors, f"errors={errors}")
            check(f"test model '{name}' has computable volumes",
                  all(v is not None and v > 0 for v in vols), f"vols={vols}")
            # Save + reopen each test model through the API.
            s, saved = req(base, "PUT", f"/api/v1/projects/{pid}/model", token=alice,
                           body={"model": m, "base_version": got["model"]["version"]})
            ok = s == 200 and len(saved["model"]["components"]) == len(m["components"])
            check(f"test model '{name}' saves via API",
                  ok, f"HTTP {s}")
            got = saved
        # Gearbox assembly structure: gears parented to shafts.
        with open(os.path.join(test_models_dir, "gearbox.json")) as f:
            gb = json.load(f)
        parents = {c["id"]: c.get("parent_id") for c in gb["components"]}
        check("gearbox: gears are children of shafts (hierarchy)",
              parents.get("gear-in") == "shaft-in" and parents.get("gear-out") == "shaft-out", "")
        # Beam: 3 m I-beam volume sanity (9.24e6 mm3, ~72.5 kg steel).
        with open(os.path.join(test_models_dir, "beam.json")) as f:
            beam = json.load(f)
        bv = modelmod.analytic_volume(beam["components"][0])
        check("beam: I-beam volume 9.24e6 mm3, mass ~72.5 kg",
              abs(bv["value"] - 9240000) < 1
              and abs(modelmod.mass_kg(bv["value"], 7850) - 72.534) < 0.01, f"got {bv['value']}")

        # --- earlier stages still pass ---
        s, lst = req(base, "GET", "/api/v1/materials?category=metals", token=alice)
        check("Stage 4 materials API still works",
              s == 200 and lst["count"] == 12, f"count={lst.get('count')}")
    finally:
        server.shutdown()
        server.server_close()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} tests passed")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
