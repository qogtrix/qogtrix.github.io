"""AI Engineering Laboratory — Backend, Stage 2 (real).

Stdlib only: no pip install needed. Run:
    cd backend && python3 app.py          # http://127.0.0.1:8001
    AIELAB_PORT=8001 AIELAB_DB=aielab.db python3 app.py

Auth: register / login / logout / me, PBKDF2 passwords, HMAC-signed
session tokens (7 days, revocable — logout deletes the session row),
plus scoped API keys for the future Muse agent (see docs/MUSE_INTEGRATION.md).
Projects: full CRUD, always scoped to the authenticated owner.
A project owned by someone else behaves as if it does not exist (404).

Simulation endpoints still return 501 — no solver in Stage 2 either.
"""
import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import auth as authmod
import db as dbmod

LABS = {"general", "mechanical", "electrical", "structural",
        "aerospace", "robotics", "materials"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,30}$")
# Lab names shown in the public gallery (Stage 3)
LAB_LABELS = {"general": "General", "mechanical": "Mechanical",
              "electrical": "Electrical", "structural": "Structural",
              "aerospace": "Aerospace", "robotics": "Robotics",
              "materials": "Materials"}
MAX_BODY = 1_000_000
LOGIN_LIMIT = 5  # failed attempts per 15 min, per email (in-memory)
_login_failures: dict[str, list[float]] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_data_file(name: str):
    path = os.path.join(dbmod.ROOT, "data", name)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    conn: sqlite3.Connection

    # -- plumbing ------------------------------------------------------
    def log_message(self, *args):  # keep test output clean
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers",
                         "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, PATCH, DELETE, OPTIONS")

    def _send(self, status: int, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError(413, "Request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except Exception:
            raise ApiError(400, "Request body is not valid JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "Request body must be a JSON object")
        return data

    # -- auth ----------------------------------------------------------
    def _bearer(self):
        h = self.headers.get("Authorization") or ""
        if not h.startswith("Bearer "):
            return None
        return h[len("Bearer "):].strip() or None

    def _current_user(self, required=True):
        """Return user row or raise 401. Accepts session tokens and
        aielab_ API keys. API keys are checked first (prefix match)."""
        token = self._bearer()
        if not token:
            if required:
                raise ApiError(401, "Authentication required — sign in first")
            return None
        if token.startswith("aielab_"):
            return self._user_from_api_key(token)
        payload = authmod.verify_token(authmod.get_secret(), token)
        if not payload:
            raise ApiError(401, "Session expired or invalid — sign in again")
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id=? AND user_id=?",
            (payload.get("sid"), payload.get("sub"))).fetchone()
        if not row:
            raise ApiError(401, "Session revoked — sign in again")
        if row["expires_at"] < now_iso():
            raise ApiError(401, "Session expired — sign in again")
        user = self.conn.execute("SELECT * FROM users WHERE id=?",
                                 (payload["sub"],)).fetchone()
        if not user:
            raise ApiError(401, "Account not found")
        self.conn.execute("UPDATE sessions SET last_used_at=? WHERE id=?",
                          (now_iso(), row["id"]))
        self.conn.commit()
        return user

    def _user_from_api_key(self, display_key: str):
        key_hash = hashlib.sha256(display_key.encode()).hexdigest()
        row = self.conn.execute(
            "SELECT * FROM api_keys WHERE key_hash=? AND revoked_at IS NULL",
            (key_hash,)).fetchone()
        if not row:
            raise ApiError(401, "Invalid API key")
        user = self.conn.execute("SELECT * FROM users WHERE id=?",
                                 (row["user_id"],)).fetchone()
        if not user:
            raise ApiError(401, "Account not found")
        self.conn.execute(
            "UPDATE api_keys SET last_used_at=? WHERE id=?",
            (now_iso(), row["id"]))
        self.conn.commit()
        return user

    def _login_rate_limited(self, email: str) -> bool:
        now = time.time()
        attempts = [t for t in _login_failures.get(email, [])
                    if now - t < 900]
        _login_failures[email] = attempts
        return len(attempts) >= LOGIN_LIMIT

    def _record_login_failure(self, email: str):
        _login_failures.setdefault(email, []).append(time.time())

    # -- routes --------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._route()

    def do_POST(self):
        self._route()

    def do_PATCH(self):
        self._route()

    def do_DELETE(self):
        self._route()

    def _route(self):
        self.conn = dbmod.connect()
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            method = self.command
            query = parse_qs(parsed.query)
            if path == "/health" and method == "GET":
                return self._send(200, {"status": "ok", "stage": 2,
                                        "solver_available": False})
            if path == "/api/v1/materials" and method == "GET":
                data = _load_data_file("materials.json") or {"materials": []}
                return self._send(200, data)
            if path == "/api/v1/components" and method == "GET":
                data = _load_data_file("components.json") or {"components": []}
                return self._send(200, data)
            if path.startswith("/api/v1/auth/"):
                return self._route_auth(path, method)
            if path.startswith("/api/v1/public/projects"):
                return self._route_public_projects(path, method, query)
            if path.startswith("/api/v1/projects"):
                return self._route_projects(path, method, query)
            if path.startswith("/api/v1/simulate/"):
                return self._send(501, {"status": "not_implemented",
                                        "stage": 3,
                                        "detail": "No simulation solver is "
                                        "implemented yet."})
            return self._send(404, {"error": "Not found"})
        except ApiError as e:
            self._send(e.status, {"error": e.message})
        except BrokenPipeError:
            pass
        except Exception as e:  # never leak internals to the client
            self._send(500, {"error": "Internal error: " + str(e)})
        finally:
            self.conn.close()

    # -- auth routes ---------------------------------------------------
    def _route_auth(self, path, method):
        if path == "/api/v1/auth/register" and method == "POST":
            data = self._read_json()
            email = str(data.get("email", "")).strip().lower()
            username = str(data.get("username", "")).strip().lower()
            name = str(data.get("name", "")).strip()
            password = str(data.get("password", ""))
            if not EMAIL_RE.match(email):
                raise ApiError(400, "Enter a valid email address")
            if not USERNAME_RE.match(username):
                raise ApiError(400, "Username must be 3–30 characters: lowercase letters, numbers and _ only")
            if len(name) < 2 or len(name) > 80:
                raise ApiError(400, "Name must be 2–80 characters")
            if len(password) < 8:
                raise ApiError(400, "Password must be at least 8 characters")
            if self.conn.execute("SELECT 1 FROM users WHERE email=?",
                                 (email,)).fetchone():
                raise ApiError(409, "An account with this email already exists")
            if self.conn.execute("SELECT 1 FROM users WHERE username=?",
                                 (username,)).fetchone():
                raise ApiError(409, "That username is already taken — choose another")
            uid = dbmod.new_id("user")
            self.conn.execute(
                "INSERT INTO users(id,email,username,name,password_hash,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (uid, email, username, name, authmod.hash_password(password),
                 now_iso(), now_iso()))
            token = self._new_session(uid)
            self.conn.commit()
            user = self.conn.execute("SELECT * FROM users WHERE id=?",
                                     (uid,)).fetchone()
            return self._send(201, {"user": dbmod.user_public(user),
                                    "token": token})
        if path == "/api/v1/auth/login" and method == "POST":
            data = self._read_json()
            # Identifier may be an email or a username (Stage 3).
            identifier = str(data.get("email", "") or data.get("username", "")).strip().lower()
            password = str(data.get("password", ""))
            if self._login_rate_limited(identifier):
                raise ApiError(429, "Too many failed sign-ins — try again in 15 minutes")
            user = self.conn.execute(
                "SELECT * FROM users WHERE email=? OR username=?",
                (identifier, identifier)).fetchone()
            if not user or not authmod.verify_password(password, user["password_hash"]):
                self._record_login_failure(identifier)
                raise ApiError(401, "Email or password is incorrect")
            if user["locked_until"] and user["locked_until"] > now_iso():
                raise ApiError(429, "Account temporarily locked — try again later")
            token = self._new_session(user["id"])
            self.conn.execute("UPDATE users SET failed_attempts=0 WHERE id=?",
                              (user["id"],))
            self.conn.commit()
            return self._send(200, {"user": dbmod.user_public(user),
                                    "token": token})
        if path == "/api/v1/auth/logout" and method == "POST":
            user = self._current_user()
            token = self._bearer()
            payload = authmod.verify_token(authmod.get_secret(), token or "")
            if payload:
                self.conn.execute("DELETE FROM sessions WHERE id=?",
                                  (payload.get("sid"),))
                self.conn.commit()
            return self._send(200, {"ok": True})
        if path == "/api/v1/auth/me" and method == "GET":
            return self._send(200, {"user": dbmod.user_public(self._current_user())})
        if path == "/api/v1/auth/me" and method == "PATCH":
            user = self._current_user()
            data = self._read_json()
            name = str(data.get("name", user["name"])).strip()
            username = str(data.get("username", user["username"] or "")).strip().lower()
            if len(name) < 2 or len(name) > 80:
                raise ApiError(400, "Name must be 2–80 characters")
            if username and not USERNAME_RE.match(username):
                raise ApiError(400, "Username must be 3–30 characters: lowercase letters, numbers and _ only")
            if username and username != (user["username"] or ""):
                if self.conn.execute("SELECT 1 FROM users WHERE username=? AND id!=?",
                                     (username, user["id"])).fetchone():
                    raise ApiError(409, "That username is already taken — choose another")
            self.conn.execute("UPDATE users SET name=?, username=?, updated_at=? WHERE id=?",
                              (name, username or user["username"], now_iso(), user["id"]))
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM users WHERE id=?",
                                    (user["id"],)).fetchone()
            return self._send(200, {"user": dbmod.user_public(row)})
        if path == "/api/v1/auth/change-password" and method == "POST":
            user = self._current_user()
            data = self._read_json()
            if not authmod.verify_password(str(data.get("current_password", "")),
                                           user["password_hash"]):
                raise ApiError(401, "Current password is incorrect")
            new = str(data.get("new_password", ""))
            if len(new) < 8:
                raise ApiError(400, "New password must be at least 8 characters")
            self.conn.execute(
                "UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
                (authmod.hash_password(new), now_iso(), user["id"]))
            self.conn.execute("DELETE FROM sessions WHERE user_id=? AND id != ?",
                              (user["id"], self._current_session_id()))
            self.conn.commit()
            return self._send(200, {"ok": True})
        if path == "/api/v1/auth/api-keys" and method == "POST":
            user = self._current_user()
            data = self._read_json()
            name = str(data.get("name", "Muse agent")).strip()[:80] or "Muse agent"
            display, prefix, key_hash = authmod.new_api_key()
            kid = dbmod.new_id("key")
            self.conn.execute(
                "INSERT INTO api_keys(id,user_id,name,key_prefix,key_hash,created_at)"
                " VALUES (?,?,?,?,?,?)",
                (kid, user["id"], name, prefix, key_hash, now_iso()))
            self.conn.commit()
            # The full key is shown ONCE — it is never stored in plain text.
            return self._send(201, {"id": kid, "name": name,
                                    "key_prefix": prefix, "key": display,
                                    "note": "Copy this key now — it will not be shown again."})
        if path == "/api/v1/auth/api-keys" and method == "GET":
            user = self._current_user()
            rows = self.conn.execute(
                "SELECT id,name,key_prefix,scopes,created_at,last_used_at,revoked_at"
                " FROM api_keys WHERE user_id=? ORDER BY created_at DESC",
                (user["id"],)).fetchall()
            return self._send(200, {"api_keys": [dict(r) for r in rows]})
        if path.startswith("/api/v1/auth/api-keys/") and method == "DELETE":
            user = self._current_user()
            kid = path.rsplit("/", 1)[-1]
            cur = self.conn.execute(
                "UPDATE api_keys SET revoked_at=? WHERE id=? AND user_id=?",
                (now_iso(), kid, user["id"]))
            self.conn.commit()
            if cur.rowcount == 0:
                raise ApiError(404, "API key not found")
            return self._send(200, {"ok": True})
        raise ApiError(404, "Not found")

    def _current_session_id(self):
        token = self._bearer() or ""
        payload = authmod.verify_token(authmod.get_secret(), token)
        return payload.get("sid") if payload else ""

    def _new_session(self, user_id: str) -> str:
        sid = dbmod.new_id("sess")
        token = authmod.create_token(authmod.get_secret(), user_id, sid)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires = (datetime.now(timezone.utc) + timedelta(seconds=authmod.TOKEN_TTL_SECONDS)).isoformat(timespec="seconds")
        self.conn.execute(
            "INSERT INTO sessions(id,user_id,token_hash,created_at,expires_at)"
            " VALUES (?,?,?,?,?)",
            (sid, user_id, token_hash, now_iso(), expires))
        return token

    # -- project routes ------------------------------------------------
    def _route_projects(self, path, method, query):
        user = self._current_user()
        parts = [p for p in path.split("/") if p]
        # /api/v1/projects[/<id>[/duplicate]]
        if len(parts) == 3 and method == "GET":
            q = (query.get("q", [""])[0] or "").strip().lower()
            lab = (query.get("lab", [""])[0] or "").strip()
            vis = (query.get("visibility", [""])[0] or "").strip()
            sql = dbmod.PROJECT_SELECT + " WHERE projects.owner_id=?"
            args: list = [user["id"]]
            if lab:
                if lab not in LABS:
                    raise ApiError(400, "Unknown laboratory: " + lab)
                sql += " AND projects.lab=?"
                args.append(lab)
            if vis:
                if vis not in ("private", "public"):
                    raise ApiError(400, "Unknown visibility: " + vis)
                sql += " AND projects.visibility=?"
                args.append(vis)
            if q:
                sql += " AND (lower(projects.name) LIKE ? OR lower(projects.description) LIKE ?)"
                args += ["%" + q + "%", "%" + q + "%"]
            sql += " ORDER BY projects.updated_at DESC, projects.created_at DESC"
            rows = self.conn.execute(sql, args).fetchall()
            return self._send(200, {"projects": [dbmod.project_public(r) for r in rows]})
        if len(parts) == 3 and method == "POST":
            data = self._read_json()
            name = str(data.get("name", "")).strip()
            description = str(data.get("description", "")).strip()
            lab = str(data.get("lab", "general")).strip() or "general"
            payload = data.get("payload") or {}
            if len(name) < 2 or len(name) > 120:
                raise ApiError(400, "Project name must be 2–120 characters")
            if lab not in LABS:
                raise ApiError(400, "Unknown laboratory: " + lab)
            if not isinstance(payload, dict):
                raise ApiError(400, "payload must be a JSON object")
            # Stage 3: new projects are ALWAYS private. A visibility value
            # sent by the client is deliberately ignored here — publishing
            # is an explicit, separate owner action (publish endpoint /
            # PATCH visibility), never a side effect of creation.
            pid = dbmod.new_id("proj")
            self.conn.execute(
                "INSERT INTO projects(id,owner_id,name,description,lab,visibility,payload,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (pid, user["id"], name, description, lab, "private",
                 json.dumps(payload), now_iso(), now_iso()))
            self.conn.commit()
            row = self.conn.execute(dbmod.PROJECT_SELECT + " WHERE projects.id=?",
                                    (pid,)).fetchone()
            return self._send(201, {"project": dbmod.project_public(row)})
        if len(parts) == 5 and parts[4] == "duplicate" and method == "POST":
            src = self._own_project(parts[3], user["id"])
            pid = dbmod.new_id("proj")
            # Copies are always private, even when the source is public.
            self.conn.execute(
                "INSERT INTO projects(id,owner_id,name,description,lab,visibility,payload,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (pid, user["id"], src["name"] + " (copy)", src["description"],
                 src["lab"], "private", src["payload"], now_iso(), now_iso()))
            self.conn.commit()
            row = self.conn.execute(dbmod.PROJECT_SELECT + " WHERE projects.id=?",
                                    (pid,)).fetchone()
            return self._send(201, {"project": dbmod.project_public(row)})
        if len(parts) == 5 and parts[4] in ("publish", "unpublish") and method == "POST":
            # Explicit visibility change. Only the owner reaches here:
            # _own_project enforces ownership and returns 404 otherwise.
            row = self._own_project(parts[3], user["id"])
            new_vis = "public" if parts[4] == "publish" else "private"
            self.conn.execute(
                "UPDATE projects SET visibility=?, updated_at=? WHERE id=? AND owner_id=?",
                (new_vis, now_iso(), parts[3], user["id"]))
            self.conn.commit()
            row = self.conn.execute(dbmod.PROJECT_SELECT + " WHERE projects.id=?",
                                    (parts[3],)).fetchone()
            return self._send(200, {"project": dbmod.project_public(row)})
        if len(parts) == 4 and method in ("GET", "PATCH", "DELETE"):
            pid = parts[3]
            if method == "GET":
                return self._send(200, {"project": dbmod.project_public(
                    self._own_project(pid, user["id"]))})
            if method == "DELETE":
                self._own_project(pid, user["id"])
                self.conn.execute("DELETE FROM projects WHERE id=? AND owner_id=?",
                                  (pid, user["id"]))
                self.conn.commit()
                return self._send(200, {"ok": True})
            data = self._read_json()
            row = self._own_project(pid, user["id"])
            name = str(data.get("name", row["name"])).strip()
            description = str(data.get("description", row["description"])).strip()
            lab = str(data.get("lab", row["lab"])).strip()
            visibility = str(data.get("visibility", row["visibility"] or "private")).strip()
            payload = data.get("payload", json.loads(row["payload"]))
            if len(name) < 2 or len(name) > 120:
                raise ApiError(400, "Project name must be 2–120 characters")
            if lab not in LABS:
                raise ApiError(400, "Unknown laboratory: " + lab)
            if visibility not in ("private", "public"):
                raise ApiError(400, "Visibility must be 'private' or 'public'")
            if not isinstance(payload, dict):
                raise ApiError(400, "payload must be a JSON object")
            self.conn.execute(
                "UPDATE projects SET name=?, description=?, lab=?, visibility=?, payload=?,"
                " updated_at=? WHERE id=? AND owner_id=?",
                (name, description, lab, visibility, json.dumps(payload), now_iso(),
                 pid, user["id"]))
            self.conn.commit()
            row = self.conn.execute(dbmod.PROJECT_SELECT + " WHERE projects.id=?",
                                    (pid,)).fetchone()
            return self._send(200, {"project": dbmod.project_public(row)})
        raise ApiError(404, "Not found")

    def _own_project(self, pid: str, owner_id: str):
        """Fetch a project only if the caller owns it; otherwise 404
        (deliberately — no existence leak for other users' projects)."""
        row = self.conn.execute(
            dbmod.PROJECT_SELECT + " WHERE projects.id=? AND projects.owner_id=?",
            (pid, owner_id)).fetchone()
        if not row:
            raise ApiError(404, "Project not found")
        return row

    # -- public gallery (Stage 3, no auth required) --------------------
    def _route_public_projects(self, path, method, query):
        if method != "GET":
            raise ApiError(404, "Not found")
        parts = [p for p in path.split("/") if p]
        # /api/v1/public/projects  (list)  or  /api/v1/public/projects/<id>
        if len(parts) == 4:
            q = (query.get("q", [""])[0] or "").strip().lower()
            lab = (query.get("lab", [""])[0] or "").strip()
            sql = dbmod.PROJECT_SELECT + " WHERE projects.visibility='public'"
            args: list = []
            if lab:
                if lab not in LABS:
                    raise ApiError(400, "Unknown laboratory: " + lab)
                sql += " AND projects.lab=?"
                args.append(lab)
            if q:
                sql += " AND (lower(projects.name) LIKE ? OR lower(projects.description) LIKE ?)"
                args += ["%" + q + "%", "%" + q + "%"]
            sql += " ORDER BY projects.updated_at DESC, projects.created_at DESC"
            rows = self.conn.execute(sql, args).fetchall()
            return self._send(200, {"projects": [dbmod.project_public_view(r) for r in rows]})
        if len(parts) == 5:
            row = self.conn.execute(
                dbmod.PROJECT_SELECT + " WHERE projects.id=? AND projects.visibility='public'",
                (parts[4],)).fetchone()
            if not row:
                # Private or nonexistent — same answer, no leak.
                raise ApiError(404, "Project not found")
            return self._send(200, {"project": dbmod.project_public_view(row)})
        raise ApiError(404, "Not found")


def main():
    port = int(os.environ.get("AIELAB_PORT", "8001"))
    conn = dbmod.connect()
    dbmod.init_db(conn)
    conn.close()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"AI Engineering Laboratory API — Stage 2")
    print(f"Listening on http://127.0.0.1:{port}  (health: /health)")
    print("Set AIELAB_SECRET in production; AIELAB_DB to change the database file.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
