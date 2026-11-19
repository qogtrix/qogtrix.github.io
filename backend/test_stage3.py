"""Stage 3 tests — private/public visibility + unique usernames.

Stdlib only. Real backend on a temporary database, real HTTP.
Tests the exact A–G sequence from the Stage 3 spec, plus direct
URL / API / file-access checks and username uniqueness.

Run:  cd backend && python3 test_stage3.py
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
    tmp = tempfile.mkdtemp(prefix="aielab-stage3-test-")
    os.environ["AIELAB_DB"] = os.path.join(tmp, "test.db")
    os.environ["AIELAB_SECRET"] = "test-secret-for-stage3-only"
    conn = dbmod.connect(os.environ["AIELAB_DB"])
    dbmod.init_db(conn)
    conn.close()

    server = ThreadingHTTPServer(("127.0.0.1", 0), appmod.Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    try:
        # --- unique usernames ---
        s, a = req(base, "POST", "/api/v1/auth/register",
                   body={"email": "alice@example.com", "username": "alice", "password": "correct-horse-1", "name": "Alice"})
        check("register Alice (username alice)", s == 201 and a["user"]["username"] == "alice", f"HTTP {s}")
        alice_tok = a.get("token", "")
        s, _ = req(base, "POST", "/api/v1/auth/register",
                   body={"email": "alice2@example.com", "username": "Alice", "password": "correct-horse-1", "name": "Alice2"})
        check("duplicate username rejected (409, case-insensitive)", s == 409, f"HTTP {s}")
        s, _ = req(base, "POST", "/api/v1/auth/register",
                   body={"email": "bad@example.com", "username": "ab", "password": "correct-horse-1", "name": "Bad"})
        check("too-short username rejected (400)", s == 400, f"HTTP {s}")
        s, _ = req(base, "POST", "/api/v1/auth/register",
                   body={"email": "bad2@example.com", "username": "bad name!", "password": "correct-horse-1", "name": "Bad"})
        check("invalid username chars rejected (400)", s == 400, f"HTTP {s}")
        s, b = req(base, "POST", "/api/v1/auth/register",
                   body={"email": "bob@example.com", "username": "bob", "password": "correct-horse-2", "name": "Bob"})
        check("register Bob (username bob)", s == 201, f"HTTP {s}")
        bob_tok = b.get("token", "")
        s, login = req(base, "POST", "/api/v1/auth/login",
                       body={"username": "alice", "password": "correct-horse-1"})
        check("login by username works", s == 200 and login.get("token"), f"HTTP {s}")

        # --- A. Alice creates a private project (default) ---
        s, p = req(base, "POST", "/api/v1/projects", token=alice_tok,
                   body={"name": "Secret Beam", "description": "Top secret beam design",
                         "lab": "structural", "visibility": "public",
                         "payload": {"span_m": 3.0, "secret_note": "do-not-leak"}})
        check("A: Alice creates project — defaults to private even when client sends public",
              s == 201 and p["project"]["visibility"] == "private", f"HTTP {s}, visibility={p.get('project', {}).get('visibility')}")
        pid = p["project"]["id"]

        # --- B. Bob cannot find or open it ---
        s, pub = req(base, "GET", "/api/v1/public/projects")
        check("B: public gallery is empty (no auth needed)", s == 200 and pub["projects"] == [], f"HTTP {s}")
        s, pub = req(base, "GET", "/api/v1/public/projects?q=beam")
        check("B: public search finds nothing", s == 200 and pub["projects"] == [], "")
        s, _ = req(base, "GET", f"/api/v1/public/projects/{pid}")
        check("B: public detail URL for private project → 404", s == 404, f"HTTP {s}")
        s, _ = req(base, "GET", f"/api/v1/projects/{pid}", token=bob_tok)
        check("B: direct API access as Bob → 404", s == 404, f"HTTP {s}")
        s, lst = req(base, "GET", "/api/v1/projects", token=bob_tok)
        check("B: Bob's own list does not contain it", s == 200 and lst["projects"] == [], "")
        s, _ = req(base, "GET", f"/api/v1/projects/{pid}")
        check("B: unauthenticated direct access → 401", s == 401, f"HTTP {s}")

        # --- C. Alice publishes it ---
        s, upd = req(base, "POST", f"/api/v1/projects/{pid}/publish", token=alice_tok)
        check("C: Alice publishes (explicit publish endpoint)", s == 200 and upd["project"]["visibility"] == "public", f"HTTP {s}")
        s, _ = req(base, "POST", f"/api/v1/projects/{pid}/publish", token=bob_tok)
        check("C: Bob cannot publish Alice's project (404)", s == 404, f"HTTP {s}")

        # --- D. Bob can now view it (read-only) ---
        s, pub = req(base, "GET", "/api/v1/public/projects")
        check("D: public gallery now lists it", s == 200 and len(pub["projects"]) == 1
              and pub["projects"][0]["owner_username"] == "alice", f"got {len(pub.get('projects', []))}")
        check("D: public listing never exposes email or owner_id",
              "email" not in json.dumps(pub) and "owner_id" not in json.dumps(pub), "")
        s, pub = req(base, "GET", "/api/v1/public/projects?q=beam")
        check("D: public search finds it", s == 200 and len(pub["projects"]) == 1, "")
        s, det = req(base, "GET", f"/api/v1/public/projects/{pid}")
        check("D: Bob views public detail (name, owner, payload published)",
              s == 200 and det["project"]["name"] == "Secret Beam"
              and det["project"]["owner_username"] == "alice", f"HTTP {s}")

        # --- E. Bob cannot modify or delete it ---
        s, _ = req(base, "PATCH", f"/api/v1/projects/{pid}", token=bob_tok, body={"name": "Hacked"})
        check("E: Bob cannot rename public project (404)", s == 404, f"HTTP {s}")
        s, _ = req(base, "DELETE", f"/api/v1/projects/{pid}", token=bob_tok)
        check("E: Bob cannot delete public project (404)", s == 404, f"HTTP {s}")
        s, _ = req(base, "POST", f"/api/v1/projects/{pid}/unpublish", token=bob_tok)
        check("E: Bob cannot change its visibility (404)", s == 404, f"HTTP {s}")
        s, _ = req(base, "POST", f"/api/v1/projects/{pid}/duplicate", token=bob_tok)
        check("E: Bob cannot duplicate it (404)", s == 404, f"HTTP {s}")
        s, still = req(base, "GET", f"/api/v1/projects/{pid}", token=alice_tok)
        check("E: Alice's project unchanged after Bob's attempts", s == 200 and still["project"]["name"] == "Secret Beam", "")

        # --- F+G. Alice makes it private again; Bob loses access immediately ---
        s, upd = req(base, "POST", f"/api/v1/projects/{pid}/unpublish", token=alice_tok)
        check("F: Alice makes it private again", s == 200 and upd["project"]["visibility"] == "private", f"HTTP {s}")
        s, pub = req(base, "GET", "/api/v1/public/projects")
        check("G: public gallery empty again immediately", s == 200 and pub["projects"] == [], "")
        s, _ = req(base, "GET", f"/api/v1/public/projects/{pid}")
        check("G: public detail URL rejected again (404)", s == 404, f"HTTP {s}")
        s, pub = req(base, "GET", "/api/v1/public/projects?q=beam")
        check("G: public search finds nothing again", s == 200 and pub["projects"] == [], "")

        # --- extra: visibility via PATCH, duplicate stays private, username change ---
        s, upd = req(base, "PATCH", f"/api/v1/projects/{pid}", token=alice_tok, body={"visibility": "public"})
        check("owner can publish via PATCH visibility", s == 200 and upd["project"]["visibility"] == "public", f"HTTP {s}")
        s, dup = req(base, "POST", f"/api/v1/projects/{pid}/duplicate", token=alice_tok)
        check("duplicate of a public project is private by default",
              s == 201 and dup["project"]["visibility"] == "private", f"HTTP {s}")
        s, pub = req(base, "GET", "/api/v1/public/projects")
        check("duplicate does not leak into gallery", s == 200 and len(pub["projects"]) == 1, f"got {len(pub.get('projects', []))}")
        s, me = req(base, "PATCH", "/api/v1/auth/me", token=alice_tok, body={"username": "bob"})
        check("username change to taken name rejected (409)", s == 409, f"HTTP {s}")
        s, me = req(base, "PATCH", "/api/v1/auth/me", token=alice_tok, body={"username": "alice_engineer"})
        check("owner can change own username", s == 200 and me["user"]["username"] == "alice_engineer", f"HTTP {s}")
        s, pub = req(base, "GET", "/api/v1/public/projects")
        check("gallery shows updated username", s == 200 and pub["projects"][0]["owner_username"] == "alice_engineer", "")
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
