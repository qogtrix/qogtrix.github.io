"""Stage 4 tests — universal engineering material database.

Stdlib only. Real backend on a temporary database, real HTTP.
Covers: search, category + property filtering, unit consistency,
comparison, source attribution, missing-data handling, recommend,
favorites persistence, material selection for projects, and
database persistence (seed-once + restart).

Run:  cd backend && python3 test_stage4.py
Exit code 0 = all tests passed.
"""
import json
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


def main():
    tmp = tempfile.mkdtemp(prefix="aielab-stage4-test-")
    db_path = os.path.join(tmp, "test.db")
    os.environ["AIELAB_DB"] = db_path
    os.environ["AIELAB_SECRET"] = "test-secret-for-stage4-only"
    conn = dbmod.connect(db_path)
    dbmod.init_db(conn)
    conn.close()

    server = ThreadingHTTPServer(("127.0.0.1", 0), appmod.Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    try:
        # --- health + categories ---
        s, h = req(base, "GET", "/health")
        check("health endpoint (stage 4)", s == 200 and h.get("stage") in (4, 5), f"HTTP {s}")
        s, cats = req(base, "GET", "/api/v1/material-categories")
        check("10 material categories", s == 200 and len(cats["categories"]) == 10, f"got {len(cats.get('categories', []))}")
        check("category counts sum to 38",
              sum(c["count"] for c in cats["categories"]) == 38, "")

        # --- list + search ---
        s, allm = req(base, "GET", "/api/v1/materials")
        check("material list returns 38", s == 200 and allm["count"] == 38 and allm["total"] == 38,
              f"HTTP {s}, count={allm.get('count')}")
        check("list carries the data-quality notice",
              "datasheet" in allm.get("notice", ""), "")
        s, r = req(base, "GET", "/api/v1/materials?q=aluminium")
        check("search 'aluminium' finds 3 grades",
              s == 200 and r["count"] == 3, f"got {r.get('count')}")
        s, r = req(base, "GET", "/api/v1/materials?q=peek")
        check("search 'peek' finds PEEK",
              s == 200 and r["count"] == 1 and r["materials"][0]["id"] == "peek", "")
        s, r = req(base, "GET", "/api/v1/materials?q=nonexistentmaterial")
        check("search with no match returns empty list",
              s == 200 and r["count"] == 0, "")

        # --- category + property filtering ---
        s, r = req(base, "GET", "/api/v1/materials?category=polymers")
        check("category filter polymers = 7",
              s == 200 and r["count"] == 7, f"got {r.get('count')}")
        s, r = req(base, "GET", "/api/v1/materials?category=ceramics")
        check("category filter ceramics = 4",
              s == 200 and r["count"] == 4, f"got {r.get('count')}")
        s, r = req(base, "GET", "/api/v1/materials?min_tensile=500")
        ids = {m["id"] for m in r["materials"]}
        check("min_tensile=500 keeps 7075/Ti/Inconel, drops PLA",
              "alu-7075-t6" in ids and "ti-6al-4v" in ids and "pla" not in ids,
              f"got {sorted(ids)}")
        s, r = req(base, "GET", "/api/v1/materials?max_density=2000")
        ids = {m["id"] for m in r["materials"]}
        check("max_density=2000 keeps PLA, drops steel",
              "pla" in ids and "steel-s355" not in ids, "")
        s, r = req(base, "GET", "/api/v1/materials?min_melting=1500")
        check("min_melting=1500 keeps steel/tungsten, drops aluminium",
              s == 200 and "steel-s355" in {m["id"] for m in r["materials"]}
              and "alu-6061-t6" not in {m["id"] for m in r["materials"]}, "")
        s, r = req(base, "GET", "/api/v1/materials?category=metals&sort=strength_to_weight")
        check("sort by strength-to-weight puts 7075 first among metals",
              s == 200 and r["materials"][0]["id"] == "alu-7075-t6",
              f"first={r['materials'][0]['id'] if r.get('materials') else '?'}")

        # --- detail, units, source attribution, missing data ---
        s, d = req(base, "GET", "/api/v1/materials/alu-6061-t6")
        m = d.get("material", {})
        check("detail: 6061 has source, standard and confidence",
              s == 200 and m.get("source") and m.get("standard") and m.get("confidence") == "typical", "")
        check("detail: 6061 strength-to-weight is 114.8 kN·m/kg",
              abs(m["derived"]["strength_to_weight_kn_m_kg"] - 114.8) < 0.05, f"got {m['derived']}")
        check("detail: 6061 missing list flags compressive strength (not zero)",
              "compressive_strength_mpa" in m["missing_properties"]
              and m["properties"]["compressive_strength_mpa"] is None, "")
        s, d = req(base, "GET", "/api/v1/materials/mineral-wool")
        mw = d.get("material", {})
        check("missing-data: mineral wool has many nulls, all listed, none zero",
              s == 200 and len(mw["missing_properties"]) >= 8
              and all(mw["properties"][k] is None for k in mw["missing_properties"]), "")
        s, _ = req(base, "GET", "/api/v1/materials/no-such-material")
        check("unknown material id → 404", s == 404, f"HTTP {s}")

        # unit consistency across the whole library
        bad = []
        for mat in allm["materials"]:
            p = mat["properties"]
            if p["density_kg_m3"] is not None and not (1 <= p["density_kg_m3"] <= 25000):
                bad.append((mat["id"], "density"))
            if p["poisson_ratio"] is not None and not (0 <= p["poisson_ratio"] <= 0.5):
                bad.append((mat["id"], "poisson"))
            if p["elastic_modulus_gpa"] is not None and not (0.001 <= p["elastic_modulus_gpa"] <= 1000):
                bad.append((mat["id"], "modulus"))
            for k, v in p.items():
                if isinstance(v, (int, float)) and v < 0:
                    bad.append((mat["id"], k))
            if not mat.get("source") or mat.get("confidence") not in ("verified", "typical", "estimated"):
                bad.append((mat["id"], "source/confidence"))
        check("unit consistency + source attribution for all 38 materials",
              bad == [], f"bad={bad[:5]}")

        # --- comparison ---
        s, c = req(base, "GET", "/api/v1/materials/compare?ids=alu-6061-t6,ti-6al-4v,steel-s355")
        rows = {r["key"]: r for r in c.get("comparison", [])}
        check("compare returns 19 rows for 3 materials",
              s == 200 and len(c["comparison"]) == 19, f"got {len(c.get('comparison', []))}")
        check("compare: titanium wins strength-to-weight (best=1)",
              rows["strength_to_weight_kn_m_kg"]["best"] == 1
              and rows["strength_to_weight_kn_m_kg"]["values"][1] == 214.4, "")
        check("compare: 6061 is lightest (density best=0)",
              rows["density_kg_m3"]["best"] == 0, "")
        check("compare: missing values are null, not zero",
              rows["compressive_strength_mpa"]["values"] == [None, None, None], "")
        s, _ = req(base, "GET", "/api/v1/materials/compare?ids=alu-6061-t6")
        check("compare with 1 material → 400", s == 400, f"HTTP {s}")
        s, _ = req(base, "GET", "/api/v1/materials/compare?ids=alu-6061-t6,nope")
        check("compare with unknown id → 404", s == 404, f"HTTP {s}")

        # --- recommend (AI prep) ---
        s, rec = req(base, "POST", "/api/v1/materials/recommend",
                     body={"min_tensile_mpa": 500, "max_density_kg_m3": 3000,
                           "min_corrosion": 2, "limit": 3})
        cands = rec.get("candidates", [])
        check("recommend: carbon fibre/epoxy ranks first for light + strong",
              s == 200 and cands and cands[0]["material"]["id"] == "cf-epoxy"
              and "score" in cands[0] and cands[0]["reasons"], "")
        check("recommend: excluded count is honest (35 of 38)",
              rec.get("excluded") == 35, f"excluded={rec.get('excluded')}")
        check("recommend: trade-offs listed from stored data",
              any(c["trade_offs"] for c in cands), "")
        s, rec = req(base, "POST", "/api/v1/materials/recommend",
                     body={"min_tensile_mpa": 5000})
        check("recommend: impossible requirements return empty, not fake data",
              s == 200 and rec["candidates"] == [], "")

        # --- favorites (auth, per-user, persistent) ---
        s, a = req(base, "POST", "/api/v1/auth/register",
                   body={"email": "alice@example.com", "username": "alice",
                         "password": "correct-horse-1", "name": "Alice"})
        alice = a.get("token", "")
        s, b = req(base, "POST", "/api/v1/auth/register",
                   body={"email": "bob@example.com", "username": "bob",
                         "password": "correct-horse-2", "name": "Bob"})
        bob = b.get("token", "")
        s, _ = req(base, "POST", "/api/v1/materials/favorites", token=alice,
                   body={"material_id": "alu-6061-t6"})
        check("Alice favorites 6061", s == 201, f"HTTP {s}")
        s, _ = req(base, "POST", "/api/v1/materials/favorites", token=alice,
                   body={"material_id": "nope"})
        check("favorite unknown material → 404", s == 404, f"HTTP {s}")
        s, _ = req(base, "POST", "/api/v1/materials/favorites",
                   body={"material_id": "alu-6061-t6"})
        check("unauthenticated favorite → 401", s == 401, f"HTTP {s}")
        s, fav = req(base, "GET", "/api/v1/materials/favorites", token=alice)
        check("Alice's favorites list 6061",
              s == 200 and [f["id"] for f in fav["favorites"]] == ["alu-6061-t6"], "")
        s, fav = req(base, "GET", "/api/v1/materials/favorites", token=bob)
        check("Bob's favorites are empty (no leak from Alice)",
              s == 200 and fav["favorites"] == [], "")
        # persistence across logout + login
        req(base, "POST", "/api/v1/auth/logout", token=alice)
        s, login = req(base, "POST", "/api/v1/auth/login",
                       body={"username": "alice", "password": "correct-horse-1"})
        alice = login.get("token", "")
        s, fav = req(base, "GET", "/api/v1/materials/favorites", token=alice)
        check("favorite persists after logout + login",
              s == 200 and [f["id"] for f in fav["favorites"]] == ["alu-6061-t6"], "")
        s, _ = req(base, "DELETE", "/api/v1/materials/favorites/alu-6061-t6", token=alice)
        check("remove favorite works", s == 200, f"HTTP {s}")

        # --- material selection for projects ---
        s, p = req(base, "POST", "/api/v1/projects", token=alice,
                   body={"name": "Beam Study", "description": "Pick a beam material",
                         "lab": "structural"})
        pid = p["project"]["id"]
        s, upd = req(base, "POST", f"/api/v1/projects/{pid}/materials", token=alice,
                     body={"material_id": "alu-6061-t6"})
        check("select material for own project",
              s == 200 and upd["project"]["payload"].get("materials") == ["alu-6061-t6"],
              f"HTTP {s}")
        s, _ = req(base, "POST", f"/api/v1/projects/{pid}/materials", token=bob,
                   body={"material_id": "steel-s355"})
        check("Bob cannot add a material to Alice's project (404)", s == 404, f"HTTP {s}")
        s, _ = req(base, "POST", f"/api/v1/projects/{pid}/materials", token=alice,
                   body={"material_id": "nope"})
        check("select unknown material → 404", s == 404, f"HTTP {s}")
        req(base, "POST", "/api/v1/auth/logout", token=alice)
        s, login = req(base, "POST", "/api/v1/auth/login",
                       body={"username": "alice", "password": "correct-horse-1"})
        s, got = req(base, "GET", f"/api/v1/projects/{pid}", token=login.get("token", ""))
        check("material selection persists after logout + login",
              s == 200 and got["project"]["payload"].get("materials") == ["alu-6061-t6"], "")

        # --- database persistence: re-init does not duplicate materials ---
        conn2 = dbmod.connect(db_path)
        dbmod.init_db(conn2)
        n = conn2.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
        conn2.close()
        check("seed is idempotent: still 38 materials after re-init", n == 38, f"n={n}")
    finally:
        server.shutdown()
        server.server_close()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} tests passed")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
