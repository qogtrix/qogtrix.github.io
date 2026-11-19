"""Stage 2 tests — two separate accounts, ownership isolation, persistence.

Stdlib only. Spins up the real backend on a temporary database and
port, then talks to it over real HTTP (urllib). No mocks for auth or
ownership — those are exactly what is being tested.

Run:  cd backend && python3 test_stage2.py
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
    tmp = tempfile.mkdtemp(prefix="aielab-stage2-test-")
    db_path = os.path.join(tmp, "test.db")
    os.environ["AIELAB_DB"] = db_path
    os.environ["AIELAB_SECRET"] = "test-secret-for-stage2-only"
    conn = dbmod.connect(db_path)
    dbmod.init_db(conn)
    conn.close()

    server = ThreadingHTTPServer(("127.0.0.1", 0), appmod.Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"

    try:
        s, body = req(base, "GET", "/health")
        check("health endpoint", s == 200 and body.get("stage") in (2, 3, 4, 5, 6, 7, 8, 9), f"HTTP {s}")

        # --- registration ---
        s, alice = req(base, "POST", "/api/v1/auth/register",
                       body={"email": "alice@example.com", "username": "alice", "password": "correct-horse-1", "name": "Alice"})
        check("register Alice", s == 201 and alice.get("token"), f"HTTP {s}")
        alice_tok = alice.get("token", "")
        s, bob = req(base, "POST", "/api/v1/auth/register",
                     body={"email": "bob@example.com", "username": "bob", "password": "correct-horse-2", "name": "Bob"})
        check("register Bob", s == 201 and bob.get("token"), f"HTTP {s}")
        bob_tok = bob.get("token", "")
        s, _ = req(base, "POST", "/api/v1/auth/register",
                   body={"email": "alice@example.com", "username": "alice2", "password": "correct-horse-1", "name": "Alice2"})
        check("duplicate email rejected (409)", s == 409, f"HTTP {s}")
        s, _ = req(base, "POST", "/api/v1/auth/register",
                   body={"email": "bad-email", "username": "xuser", "password": "correct-horse-1", "name": "X"})
        check("invalid email rejected (400)", s == 400, f"HTTP {s}")
        s, _ = req(base, "POST", "/api/v1/auth/register",
                   body={"email": "c@example.com", "username": "cuser", "password": "short", "name": "C"})
        check("short password rejected (400)", s == 400, f"HTTP {s}")

        # --- login / auth errors ---
        s, _ = req(base, "POST", "/api/v1/auth/login",
                   body={"email": "alice@example.com", "password": "wrong-password"})
        check("wrong password rejected (401)", s == 401, f"HTTP {s}")
        s, _ = req(base, "GET", "/api/v1/projects")
        check("no token rejected (401)", s == 401, f"HTTP {s}")
        s, _ = req(base, "GET", "/api/v1/projects", token="garbage.token")
        check("bad token rejected (401)", s == 401, f"HTTP {s}")
        s, me = req(base, "GET", "/api/v1/auth/me", token=alice_tok)
        check("Alice /me returns her profile", s == 200 and me["user"]["email"] == "alice@example.com", f"HTTP {s}")

        # --- both users create projects ---
        s, p1 = req(base, "POST", "/api/v1/projects", token=alice_tok,
                    body={"name": "Cantilever Beam", "description": "First beam study", "lab": "structural"})
        check("Alice creates project 1", s == 201, f"HTTP {s}")
        alice_p1 = p1["project"]["id"]
        s, p2 = req(base, "POST", "/api/v1/projects", token=alice_tok,
                    body={"name": "Robot Arm v1", "description": "3-segment arm", "lab": "robotics"})
        check("Alice creates project 2", s == 201, f"HTTP {s}")
        alice_p2 = p2["project"]["id"]
        s, p3 = req(base, "POST", "/api/v1/projects", token=bob_tok,
                    body={"name": "Bob's Circuit", "description": "Power supply", "lab": "electrical"})
        check("Bob creates project", s == 201, f"HTTP {s}")
        bob_p1 = p3["project"]["id"]

        # --- isolation: list ---
        s, lst = req(base, "GET", "/api/v1/projects", token=alice_tok)
        alice_ids = {p["id"] for p in lst["projects"]}
        check("Alice sees only her 2 projects", s == 200 and alice_ids == {alice_p1, alice_p2},
              f"got {len(lst['projects'])}")
        s, lst = req(base, "GET", "/api/v1/projects", token=bob_tok)
        check("Bob sees only his 1 project", s == 200 and [p["id"] for p in lst["projects"]] == [bob_p1],
              f"got {len(lst['projects'])}")

        # --- isolation: direct access ---
        s, _ = req(base, "GET", f"/api/v1/projects/{alice_p1}", token=bob_tok)
        check("Bob cannot GET Alice's project (404)", s == 404, f"HTTP {s}")
        s, _ = req(base, "PATCH", f"/api/v1/projects/{alice_p1}", token=bob_tok,
                   body={"name": "Hacked"})
        check("Bob cannot rename Alice's project (404)", s == 404, f"HTTP {s}")
        s, _ = req(base, "DELETE", f"/api/v1/projects/{alice_p1}", token=bob_tok)
        check("Bob cannot delete Alice's project (404)", s == 404, f"HTTP {s}")
        s, still = req(base, "GET", f"/api/v1/projects/{alice_p1}", token=alice_tok)
        check("Alice's project intact after Bob's attempts", s == 200 and still["project"]["name"] == "Cantilever Beam", f"HTTP {s}")
        s, _ = req(base, "POST", f"/api/v1/projects/{alice_p1}/duplicate", token=bob_tok)
        check("Bob cannot duplicate Alice's project (404)", s == 404, f"HTTP {s}")

        # --- rename / duplicate / search / save progress ---
        s, upd = req(base, "PATCH", f"/api/v1/projects/{alice_p1}", token=alice_tok,
                     body={"name": "Cantilever Beam — Revised", "payload": {"span_m": 2.5, "notes": "progress saved"}})
        check("Alice renames + saves progress", s == 200 and upd["project"]["name"].endswith("Revised")
              and upd["project"]["payload"].get("span_m") == 2.5, f"HTTP {s}")
        s, dup = req(base, "POST", f"/api/v1/projects/{alice_p2}/duplicate", token=alice_tok)
        check("Alice duplicates her own project", s == 201 and dup["project"]["id"] != alice_p2
              and dup["project"]["name"].endswith("(copy)"), f"HTTP {s}")
        s, lst = req(base, "GET", "/api/v1/projects?q=beam", token=alice_tok)
        check("Alice search finds beam project only", s == 200 and len(lst["projects"]) == 1, f"got {len(lst['projects'])}")
        s, lst = req(base, "GET", "/api/v1/projects?lab=robotics", token=alice_tok)
        check("Alice lab filter works", s == 200 and len(lst["projects"]) == 2, f"got {len(lst['projects'])}")

        # --- API key (Muse integration prep) ---
        s, key = req(base, "POST", "/api/v1/auth/api-keys", token=alice_tok, body={"name": "Muse agent"})
        check("Alice creates API key (shown once)", s == 201 and key.get("key", "").startswith("aielab_"), f"HTTP {s}")
        api_key = key.get("key", "")
        s, lst = req(base, "GET", "/api/v1/projects", token=api_key)
        check("API key lists owner's projects", s == 200 and len(lst["projects"]) == 3, f"got {len(lst.get('projects', []))}")
        s, _ = req(base, "GET", f"/api/v1/projects/{bob_p1}", token=api_key)
        check("API key cannot reach Bob's project (404)", s == 404, f"HTTP {s}")

        # --- delete with ownership ---
        s, _ = req(base, "DELETE", f"/api/v1/projects/{alice_p2}", token=alice_tok)
        check("Alice deletes her own project", s == 200, f"HTTP {s}")
        s, lst = req(base, "GET", "/api/v1/projects", token=alice_tok)
        check("Deleted project gone from Alice's list", s == 200 and alice_p2 not in {p["id"] for p in lst["projects"]}, "")

        # --- persistence across logout / login ---
        s, _ = req(base, "POST", "/api/v1/auth/logout", token=alice_tok)
        check("Alice logout succeeds", s == 200, f"HTTP {s}")
        s, _ = req(base, "GET", "/api/v1/auth/me", token=alice_tok)
        check("Old token rejected after logout (401)", s == 401, f"HTTP {s}")
        s, again = req(base, "POST", "/api/v1/auth/login",
                       body={"email": "alice@example.com", "password": "correct-horse-1"})
        check("Alice logs in again", s == 200 and again.get("token"), f"HTTP {s}")
        s, lst = req(base, "GET", "/api/v1/projects", token=again["token"])
        names = {p["name"] for p in lst["projects"]}
        check("Projects persist after logout + login", s == 200 and "Cantilever Beam — Revised" in names
              and "Robot Arm v1 (copy)" in names, f"got {sorted(names)}")
        s, _ = req(base, "POST", "/api/v1/projects", token=again["token"],
                   body={"name": "X", "lab": "not-a-lab"})
        check("invalid lab rejected (400)", s == 400, f"HTTP {s}")
    finally:
        server.shutdown()
        server.server_close()

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} tests passed")
    if failed:
        print("FAILED:", ", ".join(r[0] for r in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
