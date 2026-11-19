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
import model as modelmod
import solvers as solversmod
import circuit as circuitmod
import structure as structuremod
import aerospace as aeromod
import robotics as robotmod
import assistant as assistmod

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


def ctx_project_id(conv):
    """Project id attached to a conversation (or None)."""
    return conv["project_id"] if isinstance(conv, dict) else conv["project_id"]



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

    def do_PUT(self):
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
                return self._send(200, {"status": "ok", "stage": 11,
                                        "solver_available": False})
            if path == "/api/v1/material-categories" and method == "GET":
                cats = _load_data_file("material_categories.json") or {"categories": []}
                counts = {r["category"]: r["n"] for r in self.conn.execute(
                    "SELECT category, COUNT(*) n FROM materials GROUP BY category")}
                out = []
                for c in cats.get("categories", []):
                    out.append({**c, "count": counts.get(c["id"], 0)})
                return self._send(200, {"categories": out})
            if path.startswith("/api/v1/materials"):
                return self._route_materials(path, method, query)
            if path == "/api/v1/components" and method == "GET":
                data = _load_data_file("components.json") or {"components": []}
                return self._send(200, data)
            if path.startswith("/api/v1/auth/"):
                return self._route_auth(path, method)
            if path == "/api/v1/model/schema" and method == "GET":
                return self._send(200, {"schema": modelmod.MODEL_SCHEMA})
            if path.startswith("/api/v1/public/projects"):
                return self._route_public_projects(path, method, query)
            if "/model" in path and path.startswith("/api/v1/projects/"):
                return self._route_model(path, method, query)
            if "/structure" in path and path.startswith("/api/v1/projects/"):
                return self._route_project_structure(path, method, query)
            if "/aerospace" in path and path.startswith("/api/v1/projects/"):
                return self._route_project_aerospace(path, method, query)
            if "/robot" in path and path.startswith("/api/v1/projects/"):
                return self._route_project_robot(path, method, query)
            if path.startswith("/api/v1/projects"):
                return self._route_projects(path, method, query)
            if path == "/api/v1/solvers" and method == "GET":
                return self._send(200, {"solvers": solversmod.SOLVER_REGISTRY})
            if path.startswith("/api/v1/simulations"):
                return self._route_simulations(path, method, query)
            if path.startswith("/api/v1/circuits"):
                return self._route_circuits(path, method, query)
            if path.startswith("/api/v1/structures"):
                return self._route_structures(path, method, query)
            if path.startswith("/api/v1/aerospace"):
                return self._route_aerospace(path, method, query)
            if path.startswith("/api/v1/robotics"):
                return self._route_robotics(path, method, query)
            if path.startswith("/api/v1/assistant"):
                return self._route_assistant(path, method, query)
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

    # -- material database (Stage 4) -----------------------------------
    def _route_materials(self, path, method, query):
        parts = [p for p in path.split("/") if p]
        # /api/v1/materials/favorites — auth required, per-user, private.
        if len(parts) == 4 and parts[3] == "favorites":
            user = self._current_user()
            if method == "GET":
                rows = self.conn.execute(
                    "SELECT material_id FROM material_favorites"
                    " WHERE user_id=? ORDER BY created_at",
                    (user["id"],)).fetchall()
                mats = [dbmod.fetch_material(self.conn, r["material_id"])
                        for r in rows]
                return self._send(200, {"favorites": [m for m in mats if m]})
            if method == "POST":
                data = self._read_json()
                mid = str(data.get("material_id", "")).strip()
                if not dbmod.fetch_material(self.conn, mid):
                    raise ApiError(404, "Material not found")
                self.conn.execute(
                    "INSERT OR IGNORE INTO material_favorites"
                    "(user_id, material_id, created_at) VALUES (?,?,?)",
                    (user["id"], mid, now_iso()))
                self.conn.commit()
                return self._send(201, {"ok": True, "material_id": mid})
            raise ApiError(404, "Not found")
        if len(parts) == 5 and parts[3] == "favorites" and method == "DELETE":
            user = self._current_user()
            cur = self.conn.execute(
                "DELETE FROM material_favorites WHERE user_id=? AND material_id=?",
                (user["id"], parts[4]))
            self.conn.commit()
            if cur.rowcount == 0:
                raise ApiError(404, "Favorite not found")
            return self._send(200, {"ok": True})
        # /api/v1/materials/recommend — public, rule-based, transparent.
        if len(parts) == 4 and parts[3] == "recommend" and method == "POST":
            return self._recommend_materials()
        # /api/v1/materials/compare?ids=a,b,c — public, 2–4 materials.
        if len(parts) == 4 and parts[3] == "compare" and method == "GET":
            ids = [i.strip() for i in (query.get("ids", [""])[0] or "").split(",")
                   if i.strip()]
            if not 2 <= len(ids) <= 4:
                raise ApiError(400, "Compare needs 2–4 material ids (ids=a,b,c)")
            mats = [dbmod.fetch_material(self.conn, i) for i in ids]
            if any(m is None for m in mats):
                raise ApiError(404, "One of the materials was not found")
            return self._send(200, {"materials": mats,
                                    "comparison": _comparison_table(mats)})
        # /api/v1/materials/<id> — public detail.
        if len(parts) == 4 and method == "GET":
            m = dbmod.fetch_material(self.conn, parts[3])
            if not m:
                raise ApiError(404, "Material not found")
            return self._send(200, {"material": m})
        # /api/v1/materials — public list with search and filters.
        if len(parts) == 3 and method == "GET":
            q = (query.get("q", [""])[0] or "").strip().lower()
            category = (query.get("category", [""])[0] or "").strip()
            sort = (query.get("sort", ["name"])[0] or "name").strip()

            def _f(name):
                v = (query.get(name, [""])[0] or "").strip()
                try:
                    return float(v) if v else None
                except ValueError:
                    raise ApiError(400, f"Invalid number for {name}: {v}")
            min_tensile = _f("min_tensile")
            max_density = _f("max_density")
            min_melting = _f("min_melting")
            max_cost = _f("max_cost")
            min_corrosion = _f("min_corrosion")
            mats = dbmod.fetch_materials(self.conn)
            out = []
            for m in mats:
                p = m["properties"]
                if q and q not in (m["name"] + " " + (m["grade"] or "") + " " +
                                   m["category"]).lower():
                    continue
                if category and m["category"] != category:
                    continue
                if min_tensile is not None and (p["tensile_strength_mpa"] is None
                                                or p["tensile_strength_mpa"] < min_tensile):
                    continue
                if max_density is not None and (p["density_kg_m3"] is None
                                                or p["density_kg_m3"] > max_density):
                    continue
                if min_melting is not None and (p["melting_point_c"] is None
                                                or p["melting_point_c"] < min_melting):
                    continue
                if max_cost is not None and (m["cost_index"] is None
                                             or m["cost_index"] > max_cost):
                    continue
                if min_corrosion is not None and (m["corrosion_resistance"] is None
                                                  or m["corrosion_resistance"] < min_corrosion):
                    continue
                out.append(m)
            if sort == "strength_to_weight":
                out.sort(key=lambda m: m["derived"].get("strength_to_weight_kn_m_kg") or -1,
                         reverse=True)
            elif sort == "density":
                out.sort(key=lambda m: m["properties"]["density_kg_m3"] or 1e18)
            elif sort == "tensile":
                out.sort(key=lambda m: m["properties"]["tensile_strength_mpa"] or -1,
                         reverse=True)
            elif sort == "cost":
                out.sort(key=lambda m: m["cost_index"] or 99)
            else:
                out.sort(key=lambda m: m["name"])
            return self._send(200, {"materials": out, "count": len(out),
                                    "total": len(mats),
                                    "notice": "Typical published values for "
                                    "education and early-stage design only — "
                                    "verify against the datasheet."})
        raise ApiError(404, "Not found")

    def _recommend_materials(self):
        """Transparent rule-based recommendation (Stage 4, AI prep).
        Hard filters first, then a documented score:
        50% strength-to-weight + 30% specific stiffness + 20% low cost.
        Every candidate comes back with the reasons it fits and its
        trade-offs, computed from its stored data — nothing invented."""
        data = self._read_json()

        def _num(key):
            v = data.get(key)
            if v is None or v == "":
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                raise ApiError(400, f"Invalid number for {key}: {v}")
        min_tensile = _num("min_tensile_mpa")
        max_density = _num("max_density_kg_m3")
        min_melting = _num("min_melting_point_c")
        max_cost = _num("max_cost_index")
        min_corrosion = _num("min_corrosion")
        category = str(data.get("category", "") or "").strip()
        limit = data.get("limit", 5)
        try:
            limit = max(1, min(10, int(limit)))
        except (TypeError, ValueError):
            limit = 5
        mats = dbmod.fetch_materials(self.conn)
        candidates, excluded = [], 0
        for m in mats:
            p = m["properties"]
            if category and m["category"] != category:
                excluded += 1
                continue
            if min_tensile is not None and (p["tensile_strength_mpa"] is None
                                            or p["tensile_strength_mpa"] < min_tensile):
                excluded += 1
                continue
            if max_density is not None and (p["density_kg_m3"] is None
                                            or p["density_kg_m3"] > max_density):
                excluded += 1
                continue
            if min_melting is not None and (p["melting_point_c"] is None
                                            or p["melting_point_c"] < min_melting):
                excluded += 1
                continue
            if max_cost is not None and (m["cost_index"] is None
                                         or m["cost_index"] > max_cost):
                excluded += 1
                continue
            if min_corrosion is not None and (m["corrosion_resistance"] is None
                                              or m["corrosion_resistance"] < min_corrosion):
                excluded += 1
                continue
            candidates.append(m)
        if not candidates:
            return self._send(200, {"candidates": [], "excluded": excluded,
                                    "note": "No material in the current "
                                    "library meets all requirements — relax "
                                    "a constraint and try again."})
        max_stw = max((m["derived"].get("strength_to_weight_kn_m_kg") or 0)
                      for m in candidates) or 1
        max_ss = max((m["derived"].get("specific_stiffness") or 0)
                     for m in candidates) or 1
        ranked = []
        for m in candidates:
            stw = (m["derived"].get("strength_to_weight_kn_m_kg") or 0) / max_stw
            ss = (m["derived"].get("specific_stiffness") or 0) / max_ss
            cheap = 1 - ((m["cost_index"] or 3) - 1) / 4
            score = round(0.5 * stw + 0.3 * ss + 0.2 * cheap, 3)
            reasons, tradeoffs = [], []
            if m["derived"].get("strength_to_weight_kn_m_kg"):
                reasons.append(
                    f"Strength-to-weight {m['derived']['strength_to_weight_kn_m_kg']} kN·m/kg")
            if m["properties"]["tensile_strength_mpa"]:
                reasons.append(
                    f"Tensile strength {m['properties']['tensile_strength_mpa']} MPa")
            if m["properties"]["melting_point_c"]:
                reasons.append(
                    f"Melting point {m['properties']['melting_point_c']} °C")
            if (m["cost_index"] or 99) <= 2:
                reasons.append("Low relative cost")
            if (m["cost_index"] or 0) >= 4:
                tradeoffs.append("Expensive (cost index 4–5)")
            if (m["corrosion_resistance"] or 5) <= 2:
                tradeoffs.append("Needs corrosion protection")
            if (m["properties"]["thermal_conductivity_w_mk"] or 99) < 1:
                tradeoffs.append("Poor heat conductor")
            if m["properties"]["melting_point_c"] is None:
                tradeoffs.append("No melting point on record")
            ranked.append({"material": m, "score": score,
                           "reasons": reasons, "trade_offs": tradeoffs})
        ranked.sort(key=lambda r: r["score"], reverse=True)
        return self._send(200, {
            "candidates": ranked[:limit], "excluded": excluded,
            "total_considered": len(mats),
            "scoring": "50% strength-to-weight + 30% specific stiffness "
                       "+ 20% low cost, each normalized to the best "
                       "candidate in this result set."})

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

    # -- 3D model API (Stage 5) -----------------------------------------
    def _material_ids(self):
        try:
            return {r["id"] for r in self.conn.execute("SELECT id FROM materials")}
        except Exception:
            return set()

    def _model_of(self, row):
        payload = json.loads(row["payload"]) if row["payload"] else {}
        model = payload.get("model") or {}
        return payload, {
            "version": model.get("version", 0),
            "units": model.get("units", "mm"),
            "components": model.get("components", []),
        }

    def _save_model(self, pid, owner_id, payload, model):
        payload["model"] = model
        self.conn.execute(
            "UPDATE projects SET payload=?, updated_at=? WHERE id=? AND owner_id=?",
            (json.dumps(payload), now_iso(), pid, owner_id))
        self.conn.commit()

    def _model_volumes(self, model):
        densities = {}
        try:
            for r in self.conn.execute(
                    "SELECT m.id, p.value_num FROM materials m JOIN material_properties p"
                    " ON p.material_id = m.id AND p.property_key = 'density_kg_m3'"):
                densities[r["id"]] = r["value_num"]
        except Exception:
            pass
        out = []
        for c in model.get("components", []):
            vol = modelmod.analytic_volume(c)
            mass = modelmod.mass_kg(vol["value"], densities.get(c.get("material_id")))
            out.append({"id": c.get("id"), "volume_mm3": vol["value"],
                        "exact": vol["exact"], "note": vol["note"],
                        "mass_kg": mass})
        return out

    def _route_model(self, path, method, query):
        parts = [p for p in path.split("/") if p]
        # /api/v1/projects/<pid>/model[/components[/<cid>]|/validate|/export]
        if len(parts) < 5 or parts[4] != "model":
            raise ApiError(404, "Not found")
        user = self._current_user()
        pid = parts[3]
        row = self._own_project(pid, user["id"])
        payload, model = self._model_of(row)
        # GET /api/v1/projects/<pid>/model/export?format=json
        if len(parts) == 6 and parts[5] == "export" and method == "GET":
            fmt = (query.get("format", ["json"])[0] or "json").strip()
            if fmt != "json":
                raise ApiError(400, "Server-side export supports JSON only. "
                                    "STL/OBJ/GLB export runs in the browser "
                                    "workspace (three.js exporters).")
            return self._send(200, {"project_id": pid, "model": model,
                                    "volumes": self._model_volumes(model)})
        # POST /api/v1/projects/<pid>/model/validate — no save.
        if len(parts) == 6 and parts[5] == "validate" and method == "POST":
            data = self._read_json()
            candidate = data.get("model")
            if not isinstance(candidate, dict):
                raise ApiError(400, "Body must contain a model object")
            errors = modelmod.validate_model(candidate, self._material_ids())
            return self._send(200, {"valid": not errors, "errors": errors,
                                    "volumes": self._model_volumes(candidate)
                                    if not errors else []})
        # GET / PUT /api/v1/projects/<pid>/model
        if len(parts) == 5:
            if method == "GET":
                return self._send(200, {"project_id": pid, "model": model,
                                        "volumes": self._model_volumes(model)})
            if method == "PUT":
                data = self._read_json()
                candidate = data.get("model")
                if not isinstance(candidate, dict):
                    raise ApiError(400, "Body must contain a model object")
                base_version = data.get("base_version")
                if base_version is not None and base_version != model["version"]:
                    raise ApiError(409, "This model was changed elsewhere "
                                        f"(current version {model['version']}, "
                                        f"you based your edit on {base_version}). "
                                        "Reload the model and re-apply your change.")
                errors = modelmod.validate_model(candidate, self._material_ids())
                if errors:
                    raise ApiError(400, "Invalid model: " + "; ".join(errors))
                candidate["version"] = model["version"] + 1
                self._save_model(pid, user["id"], payload, candidate)
                return self._send(200, {"project_id": pid, "model": candidate,
                                        "volumes": self._model_volumes(candidate)})
            raise ApiError(404, "Not found")
        # POST /api/v1/projects/<pid>/model/components
        if len(parts) == 6 and parts[5] == "components" and method == "POST":
            data = self._read_json()
            comp = data.get("component")
            if not isinstance(comp, dict):
                raise ApiError(400, "Body must contain a component object")
            candidate = {"version": model["version"], "units": model["units"],
                         "components": model["components"] + [comp]}
            errors = modelmod.validate_model(candidate, self._material_ids())
            if errors:
                raise ApiError(400, "Invalid component: " + "; ".join(errors))
            candidate["version"] = model["version"] + 1
            self._save_model(pid, user["id"], payload, candidate)
            return self._send(201, {"project_id": pid, "model": candidate,
                                    "component": comp})
        # PATCH / DELETE /api/v1/projects/<pid>/model/components/<cid>
        if len(parts) == 7 and parts[5] == "components":
            cid = parts[6]
            comps = model["components"]
            idx = next((i for i, c in enumerate(comps) if c.get("id") == cid), None)
            if idx is None:
                raise ApiError(404, "Component not found")
            if method == "DELETE":
                referenced = [c["id"] for c in comps
                             if (c.get("parent_id") == cid)
                             or (c.get("type") == "boolean"
                                 and cid in (c.get("params") or {}).get("operands", []))]
                if referenced:
                    raise ApiError(400, "Cannot delete: still referenced by "
                                        + ", ".join(referenced))
                candidate = {"version": model["version"], "units": model["units"],
                             "components": [c for c in comps if c.get("id") != cid]}
                candidate["version"] = model["version"] + 1
                self._save_model(pid, user["id"], payload, candidate)
                return self._send(200, {"project_id": pid, "model": candidate})
            if method == "PATCH":
                data = self._read_json()
                updated = dict(comps[idx])
                for key in ("name", "kind", "type", "params", "position",
                            "rotation", "scale", "material_id", "color",
                            "visible", "parent_id", "tolerance_mm", "constraints"):
                    if key in data:
                        updated[key] = data[key]
                new_comps = list(comps)
                new_comps[idx] = updated
                candidate = {"version": model["version"], "units": model["units"],
                             "components": new_comps}
                errors = modelmod.validate_model(candidate, self._material_ids())
                if errors:
                    raise ApiError(400, "Invalid component: " + "; ".join(errors))
                candidate["version"] = model["version"] + 1
                self._save_model(pid, user["id"], payload, candidate)
                return self._send(200, {"project_id": pid, "model": candidate,
                                        "component": updated})
            raise ApiError(404, "Not found")
        raise ApiError(404, "Not found")

    # -- simulation jobs (Stage 7) --------------------------------------
    def _material_props(self, material_id):
        props = {}
        try:
            for r in self.conn.execute(
                    "SELECT property_key, value_num FROM material_properties"
                    " WHERE material_id=?", (material_id,)):
                props[r["property_key"]] = r["value_num"]
        except Exception:
            pass
        return props

    def _own_simulation(self, sid, user_id):
        row = self.conn.execute(
            "SELECT * FROM simulations WHERE id=? AND owner_id=?",
            (sid, user_id)).fetchone()
        if not row:
            raise ApiError(404, "Simulation not found")
        return row

    @staticmethod
    def _sim_public(row):
        return {"id": row["id"], "project_id": row["project_id"],
                "solver": row["solver"],
                "solver_version": row["solver_version"],
                "status": row["status"],
                "inputs": json.loads(row["inputs"]) if row["inputs"] else {},
                "results": json.loads(row["results"]) if row["results"] else None,
                "created_at": row["created_at"]}

    def _route_simulations(self, path, method, query):
        parts = [p for p in path.split("/") if p]
        user = self._current_user()
        # POST /api/v1/simulations — create + run (analytical solvers
        # run synchronously; rigid_body waits for the browser; fea/cfd
        # are recorded as not_implemented, never faked).
        if len(parts) == 3 and method == "POST":
            data = self._read_json()
            solver = str(data.get("solver", "")).strip()
            if solver not in solversmod.SOLVER_REGISTRY:
                raise ApiError(400, "Unknown solver: " + solver)
            meta = solversmod.SOLVER_REGISTRY[solver]
            pid = str(data.get("project_id", "")).strip()
            if not pid:
                raise ApiError(400, "project_id is required")
            self._own_project(pid, user["id"])
            inputs = data.get("inputs") or {}
            if not isinstance(inputs, dict):
                raise ApiError(400, "inputs must be an object")
            sid = dbmod.new_id("sim")
            if meta["status"] == "not_implemented":
                self.conn.execute(
                    "INSERT INTO simulations(id, project_id, owner_id, solver,"
                    " solver_version, status, inputs, results, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (sid, pid, user["id"], solver, meta["engine"],
                     "not_implemented", json.dumps(inputs), None, now_iso()))
                self.conn.commit()
                row = self._own_simulation(sid, user["id"])
                return self._send(201, {**self._sim_public(row),
                                        "note": meta["assumptions"][0]})
            if meta["status"] == "browser":
                self.conn.execute(
                    "INSERT INTO simulations(id, project_id, owner_id, solver,"
                    " solver_version, status, inputs, results, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (sid, pid, user["id"], solver, meta["engine"],
                     "queued", json.dumps(inputs), None, now_iso()))
                self.conn.commit()
                return self._send(201, self._sim_public(
                    self._own_simulation(sid, user["id"])))
            # Analytical solver: run now, synchronously.
            material_id = inputs.get("material_id")
            props = self._material_props(material_id) if material_id else {}
            try:
                results = solversmod.run_solver(solver, inputs, props)
            except ValueError as e:
                self.conn.execute(
                    "INSERT INTO simulations(id, project_id, owner_id, solver,"
                    " solver_version, status, inputs, results, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (sid, pid, user["id"], solver, meta["engine"],
                     "failed", json.dumps(inputs),
                     json.dumps({"error": str(e)}), now_iso()))
                self.conn.commit()
                return self._send(200, {**self._sim_public(
                    self._own_simulation(sid, user["id"])),
                    "note": "Solver failed: " + str(e)})
            self.conn.execute(
                "INSERT INTO simulations(id, project_id, owner_id, solver,"
                " solver_version, status, inputs, results, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, pid, user["id"], solver, meta["engine"],
                 "completed", json.dumps(inputs),
                 json.dumps({"method": meta["method"],
                             "engine": meta["engine"],
                             "assumptions": meta["assumptions"],
                             "values": results}), now_iso()))
            self.conn.commit()
            return self._send(201, self._sim_public(
                self._own_simulation(sid, user["id"])))
        # GET /api/v1/simulations?project_id=
        if len(parts) == 3 and method == "GET":
            pid = (query.get("project_id", [""])[0] or "").strip()
            if pid:
                self._own_project(pid, user["id"])
                rows = self.conn.execute(
                    "SELECT * FROM simulations WHERE owner_id=? AND project_id=?"
                    " ORDER BY created_at DESC", (user["id"], pid)).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM simulations WHERE owner_id=?"
                    " ORDER BY created_at DESC", (user["id"],)).fetchall()
            return self._send(200, {"simulations": [self._sim_public(r) for r in rows]})
        # GET / DELETE /api/v1/simulations/<id>
        if len(parts) == 4:
            sid = parts[3]
            row = self._own_simulation(sid, user["id"])
            if method == "GET":
                return self._send(200, self._sim_public(row))
            if method == "DELETE":
                self.conn.execute("DELETE FROM simulations WHERE id=?", (sid,))
                self.conn.commit()
                return self._send(200, {"ok": True})
            raise ApiError(404, "Not found")
        # POST /api/v1/simulations/<id>/results — browser posts
        # rigid-body results for a queued job.
        if len(parts) == 5 and parts[4] == "results" and method == "POST":
            sid = parts[3]
            row = self._own_simulation(sid, user["id"])
            if row["status"] not in ("queued", "running"):
                raise ApiError(400, "This simulation is already "
                                    f"{row['status']}; results cannot be posted")
            data = self._read_json()
            results = data.get("results")
            if not isinstance(results, dict) or "summary" not in results:
                raise ApiError(400, "results must be an object with a summary")
            self.conn.execute(
                "UPDATE simulations SET status='completed', results=?"
                " WHERE id=?", (json.dumps(results), sid))
            self.conn.commit()
            return self._send(200, self._sim_public(
                self._own_simulation(sid, user["id"])))
        raise ApiError(404, "Not found")

    # -- project routes ------------------------------------------------

    def _route_circuits(self, path, method, query):
        parts = [p for p in path.split("/") if p]
        # GET /api/v1/circuits/schema — public.
        if len(parts) == 4 and parts[3] == "schema" and method == "GET":
            return self._send(200, {"schema": circuitmod.CIRCUIT_SCHEMA})
        user = self._current_user()
        # POST /api/v1/circuits/validate — auth, no project needed.
        if len(parts) == 4 and parts[3] == "validate" and method == "POST":
            data = self._read_json()
            circuit = data.get("circuit")
            if not isinstance(circuit, dict):
                raise ApiError(400, "circuit is required")
            errors = circuitmod.validate_circuit(circuit)
            return self._send(200, {"valid": not errors, "errors": errors})
        # POST /api/v1/circuits/simulate — auth, owner-scoped project.
        if len(parts) == 4 and parts[3] == "simulate" and method == "POST":
            data = self._read_json()
            pid = str(data.get("project_id", "")).strip()
            if not pid:
                raise ApiError(400, "project_id is required")
            self._own_project(pid, user["id"])
            circuit = data.get("circuit")
            if not isinstance(circuit, dict):
                raise ApiError(400, "circuit is required")
            analysis = data.get("analysis") or {}
            if not isinstance(analysis, dict):
                raise ApiError(400, "analysis must be an object")
            atype = str(analysis.get("type", "dc")).strip()
            if atype not in ("dc", "transient", "ac"):
                raise ApiError(400, "analysis.type must be dc, transient or ac")
            solver = "circuit_" + atype
            meta = solversmod.SOLVER_REGISTRY[solver]
            inputs = {"circuit": circuit, "analysis": analysis}
            sid = dbmod.new_id("sim")
            try:
                if atype == "dc":
                    result = circuitmod.simulate_dc(circuit)
                elif atype == "transient":
                    result = circuitmod.simulate_transient(
                        circuit,
                        float(analysis.get("duration", 0.005)),
                        int(analysis.get("steps", 200)),
                        analysis.get("output_nodes"))
                else:
                    result = circuitmod.simulate_ac(
                        circuit,
                        float(analysis.get("f_start", 10)),
                        float(analysis.get("f_stop", 100000)),
                        int(analysis.get("points", 20)),
                        analysis.get("output_node"))
            except (ValueError, TypeError) as e:
                self.conn.execute(
                    "INSERT INTO simulations(id, project_id, owner_id, solver,"
                    " solver_version, status, inputs, results, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (sid, pid, user["id"], solver, meta["engine"],
                     "failed", json.dumps(inputs),
                     json.dumps({"error": str(e)}), now_iso()))
                self.conn.commit()
                return self._send(200, {**self._sim_public(
                    self._own_simulation(sid, user["id"])),
                    "note": "Circuit simulation failed: " + str(e)})
            self.conn.execute(
                "INSERT INTO simulations(id, project_id, owner_id, solver,"
                " solver_version, status, inputs, results, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, pid, user["id"], solver, meta["engine"],
                 "completed", json.dumps(inputs),
                 json.dumps({"method": meta["method"],
                             "engine": meta["engine"],
                             "assumptions": meta["assumptions"],
                             "values": result}), now_iso()))
            self.conn.commit()
            return self._send(201, self._sim_public(
                self._own_simulation(sid, user["id"])))
        raise ApiError(404, "Not found")

    # -- structural model + analysis (Stage 9) -------------------------

    def _structure_of(self, row):
        payload = json.loads(row["payload"] or "{}")
        structure = payload.get("structure") or {
            "version": 1, "nodes": [], "elements": [],
            "supports": [], "loads": [], "combinations": []}
        return payload, structure

    def _save_structure(self, pid, owner_id, payload, structure):
        payload["structure"] = structure
        self.conn.execute(
            "UPDATE projects SET payload=? WHERE id=? AND owner_id=?",
            (json.dumps(payload), pid, owner_id))
        self.conn.commit()

    def _route_project_structure(self, path, method, query):
        parts = [p for p in path.split("/") if p]
        # /api/v1/projects/<pid>/structure
        if len(parts) < 5 or parts[4] != "structure":
            raise ApiError(404, "Not found")
        user = self._current_user()
        pid = parts[3]
        row = self._own_project(pid, user["id"])
        payload, structure = self._structure_of(row)
        if len(parts) == 5:
            if method == "GET":
                return self._send(200, {"project_id": pid,
                                        "structure": structure})
            if method == "PUT":
                data = self._read_json()
                candidate = data.get("structure")
                if not isinstance(candidate, dict):
                    raise ApiError(400, "Body must contain a structure object")
                base_version = data.get("base_version")
                if base_version is not None and base_version != structure["version"]:
                    raise ApiError(409, "This structure was changed elsewhere "
                                        f"(current version {structure['version']}, "
                                        f"you based your edit on {base_version}). "
                                        "Reload the structure and re-apply your change.")
                errors = structuremod.validate_structure(
                    candidate, self._material_ids())
                if errors:
                    raise ApiError(400, "Invalid structure: " + "; ".join(errors))
                candidate["version"] = structure["version"] + 1
                self._save_structure(pid, user["id"], payload, candidate)
                return self._send(200, {"project_id": pid,
                                        "structure": candidate})
            raise ApiError(404, "Not found")
        raise ApiError(404, "Not found")

    def _route_structures(self, path, method, query):
        parts = [p for p in path.split("/") if p]
        # GET /api/v1/structures/schema — public.
        if len(parts) == 4 and parts[3] == "schema" and method == "GET":
            return self._send(200, {"schema": structuremod.STRUCTURE_SCHEMA})
        user = self._current_user()
        # POST /api/v1/structures/validate — auth, no project needed.
        if len(parts) == 4 and parts[3] == "validate" and method == "POST":
            data = self._read_json()
            structure = data.get("structure")
            if not isinstance(structure, dict):
                raise ApiError(400, "Body must contain a structure object")
            errors = structuremod.validate_structure(
                structure, self._material_ids())
            return self._send(200, {"valid": not errors, "errors": errors})
        # POST /api/v1/structures/analyze — auth, owner-scoped project.
        if len(parts) == 4 and parts[3] == "analyze" and method == "POST":
            data = self._read_json()
            pid = str(data.get("project_id", "")).strip()
            if not pid:
                raise ApiError(400, "project_id is required")
            self._own_project(pid, user["id"])
            structure = data.get("structure")
            if not isinstance(structure, dict):
                raise ApiError(400, "Body must contain a structure object")
            analysis = data.get("analysis") or {}
            if not isinstance(analysis, dict):
                raise ApiError(400, "analysis must be an object")
            atype = str(analysis.get("type", "static")).strip()
            if atype not in ("static", "modal", "buckling"):
                raise ApiError(400, "analysis.type must be static, modal or buckling")
            solver = "structural_" + atype
            meta = solversmod.SOLVER_REGISTRY[solver]
            inputs = {"structure": structure, "analysis": analysis}
            sid = dbmod.new_id("sim")

            def props_fn(mid):
                return self._material_props(mid)

            try:
                if atype == "static":
                    result = structuremod.analyze_static(
                        structure, props_fn,
                        combination=analysis.get("combination"),
                        case=analysis.get("case"))
                elif atype == "modal":
                    result = structuremod.analyze_modal(
                        structure, props_fn,
                        n_modes=int(analysis.get("n_modes", 5)))
                else:  # buckling: static analysis, buckling fields included
                    result = structuremod.analyze_static(
                        structure, props_fn,
                        combination=analysis.get("combination"),
                        case=analysis.get("case"))
                    result["analysis"] = "buckling"
            except (ValueError, TypeError) as e:
                self.conn.execute(
                    "INSERT INTO simulations(id, project_id, owner_id, solver,"
                    " solver_version, status, inputs, results, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (sid, pid, user["id"], solver, meta["engine"],
                     "failed", json.dumps(inputs),
                     json.dumps({"error": str(e)}), now_iso()))
                self.conn.commit()
                return self._send(200, {**self._sim_public(
                    self._own_simulation(sid, user["id"])),
                    "note": "Structural analysis failed: " + str(e)})
            self.conn.execute(
                "INSERT INTO simulations(id, project_id, owner_id, solver,"
                " solver_version, status, inputs, results, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, pid, user["id"], solver, meta["engine"],
                 "completed", json.dumps(inputs),
                 json.dumps({"method": meta["method"],
                             "engine": meta["engine"],
                             "assumptions": meta["assumptions"],
                             "values": result}), now_iso()))
            self.conn.commit()
            return self._send(201, self._sim_public(
                self._own_simulation(sid, user["id"])))
        raise ApiError(404, "Not found")

    # --- Stage 10: aerospace / robotics design documents --------
    def _aerospace_of(self, row):
        payload = json.loads(row["payload"] or "{}")
        design = payload.get("aerospace") or {"version": 1, "kind": "aircraft"}
        return payload, design

    def _save_aerospace(self, pid, owner_id, payload, design):
        payload["aerospace"] = design
        self.conn.execute(
            "UPDATE projects SET payload=? WHERE id=? AND owner_id=?",
            (json.dumps(payload), pid, owner_id))
        self.conn.commit()

    def _robot_of(self, row):
        payload = json.loads(row["payload"] or "{}")
        design = payload.get("robot") or {"version": 1, "kind": "arm",
                                          "dh": [], "joints": []}
        return payload, design

    def _save_robot(self, pid, owner_id, payload, design):
        payload["robot"] = design
        self.conn.execute(
            "UPDATE projects SET payload=? WHERE id=? AND owner_id=?",
            (json.dumps(payload), pid, owner_id))
        self.conn.commit()

    def _validate_aerospace_design(self, design):
        if not isinstance(design, dict):
            return ["design must be an object"]
        kind = design.get("kind")
        if kind not in ("aircraft", "rocket", "multirotor"):
            return [f"design.kind must be aircraft, rocket or multirotor (got {kind!r})"]
        return []

    def _validate_robot_design(self, design):
        if not isinstance(design, dict):
            return ["design must be an object"]
        kind = design.get("kind")
        if kind not in ("arm", "mobile"):
            return [f"design.kind must be arm or mobile (got {kind!r})"]
        errors = []
        for i, row in enumerate(design.get("dh") or []):
            for k in ("a", "alpha", "d", "theta"):
                if k not in row or not isinstance(row[k], (int, float)):
                    errors.append(f"dh[{i}].{k} must be a number")
        return errors

    def _route_project_aerospace(self, path, method, query):
        parts = [p for p in path.split("/") if p]
        if len(parts) < 5 or parts[4] != "aerospace":
            raise ApiError(404, "Not found")
        user = self._current_user()
        pid = parts[3]
        row = self._own_project(pid, user["id"])
        payload, design = self._aerospace_of(row)
        if len(parts) == 5:
            if method == "GET":
                return self._send(200, {"project_id": pid, "design": design})
            if method == "PUT":
                data = self._read_json()
                candidate = data.get("design")
                if not isinstance(candidate, dict):
                    raise ApiError(400, "Body must contain a design object")
                base_version = data.get("base_version")
                if base_version is not None and base_version != design["version"]:
                    raise ApiError(409, "This design was changed elsewhere "
                                        f"(current version {design['version']}, "
                                        f"you based your edit on {base_version}). "
                                        "Reload the design and re-apply your change.")
                errors = self._validate_aerospace_design(candidate)
                if errors:
                    raise ApiError(400, "Invalid design: " + "; ".join(errors))
                candidate["version"] = design["version"] + 1
                self._save_aerospace(pid, user["id"], payload, candidate)
                return self._send(200, {"project_id": pid, "design": candidate})
            raise ApiError(404, "Not found")
        raise ApiError(404, "Not found")

    def _route_project_robot(self, path, method, query):
        parts = [p for p in path.split("/") if p]
        if len(parts) < 5 or parts[4] != "robot":
            raise ApiError(404, "Not found")
        user = self._current_user()
        pid = parts[3]
        row = self._own_project(pid, user["id"])
        payload, design = self._robot_of(row)
        if len(parts) == 5:
            if method == "GET":
                return self._send(200, {"project_id": pid, "design": design})
            if method == "PUT":
                data = self._read_json()
                candidate = data.get("design")
                if not isinstance(candidate, dict):
                    raise ApiError(400, "Body must contain a design object")
                base_version = data.get("base_version")
                if base_version is not None and base_version != design["version"]:
                    raise ApiError(409, "This design was changed elsewhere "
                                        f"(current version {design['version']}, "
                                        f"you based your edit on {base_version}). "
                                        "Reload the design and re-apply your change.")
                errors = self._validate_robot_design(candidate)
                if errors:
                    raise ApiError(400, "Invalid design: " + "; ".join(errors))
                candidate["version"] = design["version"] + 1
                self._save_robot(pid, user["id"], payload, candidate)
                return self._send(200, {"project_id": pid, "design": candidate})
            raise ApiError(404, "Not found")
        raise ApiError(404, "Not found")

    def _spar_check(self, spar, props_fn):
        """Stage 9 structural check of a wing spar: one cantilever
        beam carrying the lift at its tip. Returns the Stage 9
        summary fields."""
        length = float(spar["length_m"])
        lift = float(spar["lift_N"])
        structure = {
            "nodes": [{"id": "root", "x_m": 0, "y_m": 0, "z_m": 0},
                      {"id": "tip", "x_m": length, "y_m": 0, "z_m": 0}],
            "elements": [{"id": "spar", "type": "beam", "n1": "root",
                          "n2": "tip", "section": spar["section"],
                          "material_id": spar["material_id"]}],
            "supports": [{"node": "root", "ux": True, "uy": True, "uz": True,
                          "rx": True, "ry": True, "rz": True}],
            "loads": [{"case": "lift", "type": "point", "node": "tip",
                       "fy_N": lift}],
            "combinations": []}
        res = structuremod.analyze_static(structure, props_fn, case="lift")
        el = res["elements"][0]
        return {"max_stress_Pa": el["max_stress_Pa"],
                "utilization": el["utilization"],
                "max_displacement_m": res["max_displacement_m"],
                "warnings": res["warnings"],
                "assumption": "Spar modelled as a cantilever beam from the "
                              "fuselage, carrying the full lift at its tip "
                              "(conservative); self-weight ignored"}

    def _link_check(self, links, props_fn):
        """Stage 9 structural check of robot arm links: each link as
        a cantilever beam carrying the payload at its tip."""
        out = []
        for i, link in enumerate(links):
            length = float(link["length_m"])
            payload = float(link.get("payload_N", 0))
            structure = {
                "nodes": [{"id": "base", "x_m": 0, "y_m": 0, "z_m": 0},
                          {"id": "tip", "x_m": length, "y_m": 0, "z_m": 0}],
                "elements": [{"id": "link", "type": "beam", "n1": "base",
                              "n2": "tip", "section": link["section"],
                              "material_id": link["material_id"]}],
                "supports": [{"node": "base", "ux": True, "uy": True, "uz": True,
                              "rx": True, "ry": True, "rz": True}],
                "loads": [{"case": "payload", "type": "point", "node": "tip",
                           "fy_N": -payload}],
                "combinations": []}
            res = structuremod.analyze_static(structure, props_fn, case="payload")
            el = res["elements"][0]
            out.append({"link": i, "name": link.get("name", f"link {i + 1}"),
                        "max_stress_Pa": el["max_stress_Pa"],
                        "utilization": el["utilization"],
                        "max_displacement_m": res["max_displacement_m"]})
        return out

    def _store_job(self, pid, user_id, solver, inputs, result, error=None):
        meta = solversmod.SOLVER_REGISTRY[solver]
        sid = dbmod.new_id("sim")
        if error is not None:
            self.conn.execute(
                "INSERT INTO simulations(id, project_id, owner_id, solver,"
                " solver_version, status, inputs, results, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, pid, user_id, solver, meta["engine"],
                 "failed", json.dumps(inputs),
                 json.dumps({"error": str(error)}), now_iso()))
            self.conn.commit()
            return self._send(200, {**self._sim_public(
                self._own_simulation(sid, user_id)),
                "note": "Analysis failed: " + str(error)})
        self.conn.execute(
            "INSERT INTO simulations(id, project_id, owner_id, solver,"
            " solver_version, status, inputs, results, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (sid, pid, user_id, solver, meta["engine"],
             "completed", json.dumps(inputs),
             json.dumps({"method": meta["method"],
                         "engine": meta["engine"],
                         "assumptions": meta["assumptions"],
                         "values": result}), now_iso()))
        self.conn.commit()
        return self._send(201, self._sim_public(
            self._own_simulation(sid, user_id)))

    def _route_aerospace(self, path, method, query):
        parts = [p for p in path.split("/") if p]
        if len(parts) == 4 and parts[3] == "schema" and method == "GET":
            return self._send(200, {"schema": aeromod.AEROSPACE_SCHEMA})
        user = self._current_user()
        if len(parts) == 4 and parts[3] == "validate" and method == "POST":
            data = self._read_json()
            design = data.get("design")
            if not isinstance(design, dict):
                raise ApiError(400, "Body must contain a design object")
            errors = self._validate_aerospace_design(design)
            return self._send(200, {"valid": not errors, "errors": errors})
        if len(parts) == 4 and parts[3] == "analyze" and method == "POST":
            data = self._read_json()
            pid = str(data.get("project_id", "")).strip()
            if not pid:
                raise ApiError(400, "project_id is required")
            self._own_project(pid, user["id"])
            design = data.get("design")
            if not isinstance(design, dict):
                raise ApiError(400, "Body must contain a design object")
            analysis = data.get("analysis") or {}
            if not isinstance(analysis, dict):
                raise ApiError(400, "analysis must be an object")
            atype = str(analysis.get("type", "aircraft")).strip()
            if atype not in ("aircraft", "rocket", "trajectory", "multirotor"):
                raise ApiError(400, "analysis.type must be aircraft, rocket, "
                                    "trajectory or multirotor")
            solver = {"aircraft": "aero_aircraft", "rocket": "aero_rocket",
                      "trajectory": "aero_trajectory",
                      "multirotor": "aero_multirotor"}[atype]
            inputs = {"design": design, "analysis": analysis}

            def props_fn(mid):
                return self._material_props(mid)

            try:
                if atype == "aircraft":
                    result = aeromod.aircraft_performance(design)
                    if design.get("spar"):
                        result["spar_check"] = self._spar_check(
                            design["spar"], props_fn)
                elif atype == "rocket":
                    result = {"delta_v": aeromod.rocket_delta_v(design["stages"])}
                    if design.get("stability"):
                        st = design["stability"]
                        result["stability"] = aeromod.rocket_stability(
                            st["components"], float(st["cg_x_m"]),
                            float(st["diameter_m"]))
                elif atype == "trajectory":
                    result = aeromod.trajectory_2d(design)
                else:  # multirotor
                    result = aeromod.multirotor_hover(design)
            except (ValueError, TypeError) as e:
                return self._store_job(pid, user["id"], solver, inputs, None, error=e)
            return self._store_job(pid, user["id"], solver, inputs, result)
        raise ApiError(404, "Not found")

    def _route_robotics(self, path, method, query):
        parts = [p for p in path.split("/") if p]
        if len(parts) == 4 and parts[3] == "schema" and method == "GET":
            return self._send(200, {"schema": robotmod.ROBOTICS_SCHEMA})
        user = self._current_user()
        if len(parts) == 4 and parts[3] == "validate" and method == "POST":
            data = self._read_json()
            design = data.get("design")
            if not isinstance(design, dict):
                raise ApiError(400, "Body must contain a design object")
            errors = self._validate_robot_design(design)
            return self._send(200, {"valid": not errors, "errors": errors})
        if len(parts) == 4 and parts[3] == "analyze" and method == "POST":
            data = self._read_json()
            pid = str(data.get("project_id", "")).strip()
            if not pid:
                raise ApiError(400, "project_id is required")
            self._own_project(pid, user["id"])
            design = data.get("design")
            if not isinstance(design, dict):
                raise ApiError(400, "Body must contain a design object")
            analysis = data.get("analysis") or {}
            if not isinstance(analysis, dict):
                raise ApiError(400, "analysis must be an object")
            atype = str(analysis.get("type", "arm")).strip()
            if atype not in ("arm", "control"):
                raise ApiError(400, "analysis.type must be arm or control")
            solver = "robot_arm" if atype == "arm" else "robot_control"
            inputs = {"design": design, "analysis": analysis}

            def props_fn(mid):
                return self._material_props(mid)

            try:
                if atype == "arm":
                    dh = design["dh"]
                    joints = [float(q) for q in design["joints"]]
                    result = {"fk": robotmod.fk_dh(dh, joints)}
                    result["limit_violations"] = robotmod.joint_limit_violations(
                        joints, design.get("limits"))
                    if design.get("target_pos"):
                        result["ik"] = robotmod.ik_dls(
                            dh, [float(v) for v in design["target_pos"]],
                            joints, limits=design.get("limits"))
                    if design.get("motor"):
                        # Stage 8 motor check (steady state).
                        result["motor_check"] = solversmod.run_solver(
                            "dc_motor", design["motor"], {})
                    if design.get("links"):
                        # Stage 9 structural check of the links.
                        result["link_check"] = self._link_check(
                            design["links"], props_fn)
                    if design.get("obstacles"):
                        positions = result["fk"]["positions"]
                        caps = []
                        for i in range(len(dh)):
                            caps.append({"a": positions[i], "b": positions[i + 1],
                                         "radius_m": float(
                                             design.get("link_radius_m", 0.05)),
                                         "name": f"link {i + 1}"})
                        result["collisions"] = robotmod.check_collisions(
                            caps, design["obstacles"])
                else:  # control
                    result = {}
                    if design.get("pid"):
                        result["pid"] = robotmod.pid_simulate(design["pid"])
                    if design.get("trajectory"):
                        tr = design["trajectory"]
                        result["trajectory"] = robotmod.cubic_trajectory(
                            [float(v) for v in tr["q0"]],
                            [float(v) for v in tr["q1"]],
                            float(tr["duration_s"]),
                            dt=float(tr.get("dt", 0.05)))
                    if not result:
                        raise ValueError("control analysis needs a pid and/or "
                                         "trajectory design")
            except (ValueError, TypeError, KeyError) as e:
                return self._store_job(pid, user["id"], solver, inputs, None, error=e)
            return self._store_job(pid, user["id"], solver, inputs, result)
        raise ApiError(404, "Not found")

    # -- AI Engineering Assistant (Stage 11) ---------------------------
    def _asst_conv(self, cid, user_id):
        """Fetch a conversation only if the caller owns it (404 otherwise)."""
        row = self.conn.execute(
            "SELECT * FROM assistant_conversations WHERE id=? AND user_id=?",
            (cid, user_id)).fetchone()
        if not row:
            raise ApiError(404, "Conversation not found")
        return row

    def _asst_project_ctx(self, conv, user_id):
        """(project row, payload) for the conversation's attached project,
        owner-verified on every call. (None, None) when none is attached."""
        pid = conv["project_id"]
        if not pid:
            return None, None
        row = self._own_project(pid, user_id)
        return row, json.loads(row["payload"] or "{}")

    def _asst_record_usage(self, user_id, conv_id, provider, model,
                           prompt_tokens, completion_tokens, status, ms):
        self.conn.execute(
            "INSERT INTO assistant_usage (id, user_id, conversation_id, "
            "provider, model, prompt_tokens, completion_tokens, cost_usd, "
            "status, duration_ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (dbmod.new_id("use"), user_id, conv_id, provider, model,
             int(prompt_tokens), int(completion_tokens),
             assistmod.cost_usd(provider, prompt_tokens, completion_tokens),
             status, int(ms)))
        self.conn.commit()

    def _asst_store_message(self, conv_id, user_id, role, content,
                            tool_calls=None, provenance=None):
        mid = dbmod.new_id("msg")
        self.conn.execute(
            "INSERT INTO assistant_messages (id, conversation_id, user_id, "
            "role, content, tool_calls, provenance) VALUES (?,?,?,?,?,?,?)",
            (mid, conv_id, user_id, role, content,
             json.dumps(tool_calls) if tool_calls is not None else None,
             provenance))
        self.conn.execute(
            "UPDATE assistant_conversations SET updated_at=datetime('now') "
            "WHERE id=?", (conv_id,))
        self.conn.commit()
        return mid

    def _asst_msg_out(self, row):
        return {"id": row["id"], "role": row["role"], "content": row["content"],
                "tool_calls": json.loads(row["tool_calls"]) if row["tool_calls"] else [],
                "provenance": row["provenance"],
                "created_at": row["created_at"]}

    def _asst_handle_message(self, conv, user, content):
        """The assistant's reply pipeline. Returns the assistant message
        dict. Every number in the reply comes from a real solver or the
        materials database, or is labelled as an estimate/guidance."""
        import time as _time
        t0 = _time.time()
        content = (content or "").strip()
        if not content:
            raise ApiError(400, "Message must not be empty")
        if len(content) > 4000:
            raise ApiError(400, "Message is too long (4000 characters maximum)")
        limit = assistmod.check_rate_limit(user["id"])
        if limit:
            self._asst_record_usage(user["id"], conv["id"], "local",
                                    "local-engine", 0, 0, "rate_limited",
                                    int((_time.time() - t0) * 1000))
            raise ApiError(429, limit)
        cfg = assistmod.get_provider_config()
        self._asst_store_message(conv["id"], user["id"], "user", content)
        project, payload = self._asst_project_ctx(conv, user["id"])
        ctx = {"conn": self.conn, "user_id": user["id"],
               "project": dict(project) if project else None,
               "project_payload": payload}
        pending = json.loads(conv["pending_json"]) if conv["pending_json"] else None
        reply = None
        tool_calls = []
        provenance = "general guidance"
        provider_used = "local"
        provider_status = "ok"
        prompt_tokens = assistmod.estimate_tokens(content)
        completion_tokens = 0

        def _ask_missing(tool_def, inputs, missing):
            asked = "\n".join(
                f"- {m['label']}" + (f" ({m['unit']})" if m.get("unit") else "")
                for m in missing)
            sugg = assistmod.SUGGESTED_DEFAULTS.get(tool_def["name"], {})
            sugg_txt = ""
            if sugg:
                sugg_txt = (" If that is fine, reply 'yes' — otherwise give me "
                            "your own values. Suggested: " +
                            ", ".join(f"{k} = {v}" for k, v in sugg.items()) + ".")
            return (f"To run **{tool_def['label']}** I still need:\n{asked}\n"
                    f"Give me those values and I will run it — I will not "
                    f"guess them.{sugg_txt}")

        # 1. Resume a pending clarification, when the reply answers it.
        resumed = False
        if pending:
            tool_def = next((x for x in assistmod.TOOL_DEFS
                             if x["name"] == pending["tool"]), None)
            low = content.lower()
            confirmed = any(w in low for w in
                            ("yes", "ok", "okay", "sure", "go ahead", "use those",
                             "use that", "fine", "do it"))
            if tool_def is not None:
                # Extract only for the params that are still missing —
                # re-extracting all of them would let a follow-up number
                # overwrite a value the user already gave.
                missing_keys = {m["key"] for m in pending["missing"]}
                missing_specs = [s for s in tool_def["params"]
                                 if s["key"] in missing_keys]
                new_inputs, still_missing = assistmod._extract_params(
                    content, missing_specs)
                merged = dict(pending.get("inputs") or {})
                for k, v in new_inputs.items():
                    if v is not None:
                        merged[k] = v
                if confirmed:
                    for k, v in assistmod.SUGGESTED_DEFAULTS.get(
                            tool_def["name"], {}).items():
                        merged.setdefault(k, v)
                    still_missing = [m for m in pending["missing"]
                                     if merged.get(m["key"]) is None]
                else:
                    still_missing = [m for m in pending["missing"]
                                     if merged.get(m["key"]) is None]
                if not still_missing:
                    resumed = True
                    pending = None
                    inputs = merged
                    try:
                        result = assistmod.execute_tool(ctx, tool_def, inputs, content)
                        reply, tool_calls, provenance = self._asst_tool_reply(
                            conv, user, tool_def, result)
                    except assistmod.ToolInputError as e:
                        reply = str(e) or "I could not run that with the values given."
                        tool_calls = [{"tool": tool_def["name"], "status": "failed",
                                       "error": reply}]
                    except (ValueError, TypeError, KeyError) as e:
                        reply = f"The {tool_def['label']} calculation could not run: {e}"
                        tool_calls = [{"tool": tool_def["name"], "status": "failed",
                                       "error": str(e)}]
                elif confirmed or new_inputs:
                    pending = {"tool": tool_def["name"], "inputs": merged,
                               "missing": still_missing}
                    reply = _ask_missing(tool_def, merged, still_missing)
                    resumed = True
        # 2. Fresh request (an unrelated message abandons the old
        #    pending clarification instead of answering it twice).
        if not resumed and reply is None:
            pending = None
            tool_def, _score = assistmod.select_tool(content)
            if tool_def is not None:
                inputs, missing = assistmod._extract_params(content, tool_def["params"])
                if missing:
                    pending = {"tool": tool_def["name"], "inputs": inputs,
                               "missing": missing}
                    reply = _ask_missing(tool_def, inputs, missing)
                else:
                    try:
                        result = assistmod.execute_tool(ctx, tool_def, inputs, content)
                        reply, tool_calls, provenance = self._asst_tool_reply(
                            conv, user, tool_def, result)
                    except assistmod.ToolInputError as e:
                        reply = str(e) or "I could not run that with the values given."
                        tool_calls = [{"tool": tool_def["name"], "status": "failed",
                                       "error": reply}]
                    except (ValueError, TypeError, KeyError) as e:
                        reply = f"The {tool_def['label']} calculation could not run: {e}"
                        tool_calls = [{"tool": tool_def["name"], "status": "failed",
                                       "error": str(e)}]
            else:
                explanation = assistmod.explain_topic(content)
                if explanation is not None:
                    reply = explanation
                elif cfg["provider"] != "local":
                    # External provider: free-text explanation ONLY.
                    # It never selects tools and never supplies numbers.
                    # A named provider is always attempted, so a missing
                    # key or an outage is reported honestly instead of
                    # silently falling back.
                    provider_used = cfg["provider"]
                    try:
                        reply = assistmod.provider_explain(
                            content, system="You are a concise engineering "
                            "assistant. Explain the concept in plain language. "
                            "Do not invent numbers, material properties, test "
                            "results or standards.")
                        completion_tokens = assistmod.estimate_tokens(reply)
                    except assistmod.ProviderError as e:
                        provider_status = "provider_error"
                        reply = ("My external AI provider is unavailable right "
                                 f"now ({e}). Here is what I can do without it: "
                                 + assistmod.KNOWLEDGE["help"])
                else:
                    reply = ("I can help with engineering calculations, material "
                             "lookups, and your projects — but I do not have an "
                             "answer for that question. Try one of these:\n"
                             "- 'gear train 20 and 40 teeth, 1000 rpm, 10 Nm'\n"
                             "- 'voltage divider 10 V, R1 1k, R2 1k'\n"
                             "- 'column buckling 3 m, 100x100 mm square'\n"
                             "- 'properties of steel S355'\n"
                             "- 'what is torque?'")
        # 3. Persist the pending state and the assistant message.
        self.conn.execute(
            "UPDATE assistant_conversations SET pending_json=? WHERE id=?",
            (json.dumps(pending) if pending else None, conv["id"]))
        self.conn.commit()
        mid = self._asst_store_message(conv["id"], user["id"], "assistant",
                                       reply, tool_calls, provenance)
        completion_tokens = completion_tokens or assistmod.estimate_tokens(reply)
        self._asst_record_usage(user["id"], conv["id"], provider_used,
                                cfg["model"] if provider_used != "local" else "local-engine",
                                prompt_tokens, completion_tokens, provider_status,
                                int((_time.time() - t0) * 1000))
        row = self.conn.execute(
            "SELECT * FROM assistant_messages WHERE id=?", (mid,)).fetchone()
        return self._asst_msg_out(row)

    def _asst_tool_reply(self, conv, user, tool_def, result):
        """Turn a tool result into a reply. A proposal is stored for
        approval, never applied here."""
        if tool_def["name"] == "project_propose":
            proposal = result.get("proposal")
            if proposal is None:
                return (result.get("unsupported") or
                        "I could not turn that into a concrete change.",
                        [{"tool": tool_def["name"], "status": "failed",
                          "error": "unsupported change"}], "general guidance")
            pid = dbmod.new_id("prop")
            change_doc = dict(proposal["change"])
            if proposal.get("element_id"):
                change_doc["element_id"] = proposal["element_id"]
            self.conn.execute(
                "INSERT INTO assistant_proposals (id, conversation_id, user_id, "
                "project_id, target, change_json, summary, status) "
                "VALUES (?,?,?,?,?,?,?,'pending')",
                (pid, conv["id"], user["id"], ctx_project_id(conv),
                 proposal["target"], json.dumps(change_doc),
                 proposal["summary"]))
            self.conn.commit()
            reply = (f"Proposed change (not applied yet):\n"
                     f"**{proposal['summary']}**\n\n"
                     f"Reply with the proposal id `{pid}` and approve it from "
                     f"the chat, or use the Approve button. Nothing changes "
                     f"until you approve it.")
            return reply, [{"tool": tool_def["name"], "status": "proposed",
                            "proposal_id": pid,
                            "summary": proposal["summary"]}], "proposal"
        reply = assistmod.format_result(tool_def, result)
        return reply, [{"tool": tool_def["name"], "status": "completed",
                        "provenance": result.get("provenance"),
                        "source": result.get("source")}], result.get("provenance")

    def _asst_apply_proposal(self, proposal, user):
        """Apply an approved proposal to the owner's project. Only the
        two supported change types exist; anything else is refused."""
        row = self._own_project(proposal["project_id"], user["id"])
        payload = json.loads(row["payload"] or "{}")
        change = json.loads(proposal["change_json"])
        if proposal["target"] == "structure":
            _payload, structure = self._structure_of(row)
            elements = structure.get("elements") or []
            target = next((e for e in elements if isinstance(e, dict)
                           and e.get("id") == change.get("element_id")), None)
            if target is None:
                raise ApiError(400, "The structure element no longer exists")
            target["section"] = change["section"]
            structure["version"] = int(structure.get("version") or 1) + 1
            self._save_structure(proposal["project_id"], user["id"], _payload, structure)
        elif proposal["target"] == "aerospace":
            _payload, design = self._aerospace_of(row)
            for k, v in change.items():
                design[k] = v
            design["version"] = int(design.get("version") or 1) + 1
            self._save_aerospace(proposal["project_id"], user["id"], _payload, design)
        else:
            raise ApiError(400, f"Unsupported proposal target: {proposal['target']}")
        self.conn.execute(
            "UPDATE assistant_proposals SET status='applied', "
            "decided_at=datetime('now') WHERE id=?", (proposal["id"],))
        self.conn.commit()

    def _route_assistant(self, path, method, query):
        parts = [p for p in path.split("/") if p]
        # GET /api/v1/assistant/config — provider status (never the key).
        if len(parts) == 4 and parts[3] == "config" and method == "GET":
            user = self._current_user()
            cfg = assistmod.get_provider_config()
            return self._send(200, {"provider": cfg["provider"],
                                    "label": cfg["label"],
                                    "model": cfg["model"],
                                    "configured": cfg["configured"],
                                    "api_key_set": cfg["api_key_set"],
                                    "rate_limit_per_minute": assistmod.RATE_LIMIT_PER_MINUTE,
                                    "rate_limit_per_hour": assistmod.RATE_LIMIT_PER_HOUR})
        # GET /api/v1/assistant/tools — the tool registry.
        if len(parts) == 4 and parts[3] == "tools" and method == "GET":
            self._current_user()
            return self._send(200, {"tools": [assistmod.tool_summary(t)
                                              for t in assistmod.TOOL_DEFS]})
        # GET /api/v1/assistant/usage — per-user usage and costs.
        if len(parts) == 4 and parts[3] == "usage" and method == "GET":
            user = self._current_user()
            rows = self.conn.execute(
                "SELECT * FROM assistant_usage WHERE user_id=? "
                "ORDER BY created_at DESC LIMIT 50", (user["id"],)).fetchall()
            totals = self.conn.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(prompt_tokens),0) pt, "
                "COALESCE(SUM(completion_tokens),0) ct, "
                "COALESCE(SUM(cost_usd),0) cost FROM assistant_usage "
                "WHERE user_id=?", (user["id"],)).fetchone()
            return self._send(200, {
                "totals": {"requests": totals["n"], "prompt_tokens": totals["pt"],
                           "completion_tokens": totals["ct"],
                           "cost_usd": round(totals["cost"], 6)},
                "usage": [dict(r) for r in rows]})
        # GET/POST /api/v1/assistant/conversations
        if len(parts) == 4 and parts[3] == "conversations":
            user = self._current_user()
            if method == "GET":
                rows = self.conn.execute(
                    "SELECT * FROM assistant_conversations WHERE user_id=? "
                    "ORDER BY updated_at DESC", (user["id"],)).fetchall()
                return self._send(200, {"conversations": [dict(r) for r in rows]})
            if method == "POST":
                data = self._read_json()
                title = str(data.get("title") or "New conversation").strip()[:120]
                pid = data.get("project_id")
                if pid:
                    self._own_project(str(pid), user["id"])
                cid = dbmod.new_id("conv")
                self.conn.execute(
                    "INSERT INTO assistant_conversations (id, user_id, title, project_id) "
                    "VALUES (?,?,?,?)", (cid, user["id"], title, pid or None))
                self.conn.commit()
                row = self.conn.execute(
                    "SELECT * FROM assistant_conversations WHERE id=?", (cid,)).fetchone()
                return self._send(201, {"conversation": dict(row)})
            raise ApiError(404, "Not found")
        # /api/v1/assistant/conversations/<id> and below
        if len(parts) >= 5 and parts[3] == "conversations":
            cid = parts[4]
            user = self._current_user()
            conv = self._asst_conv(cid, user["id"])
            if len(parts) == 5 and method == "GET":
                msgs = self.conn.execute(
                    "SELECT * FROM assistant_messages WHERE conversation_id=? "
                    "AND user_id=? ORDER BY created_at ASC LIMIT 200",
                    (cid, user["id"])).fetchall()
                props = self.conn.execute(
                    "SELECT * FROM assistant_proposals WHERE conversation_id=? "
                    "AND user_id=? ORDER BY created_at DESC",
                    (cid, user["id"])).fetchall()
                out = dict(conv)
                out["messages"] = [self._asst_msg_out(m) for m in msgs]
                out["proposals"] = [dict(p) for p in props]
                return self._send(200, {"conversation": out})
            if len(parts) == 5 and method == "PATCH":
                data = self._read_json()
                if "title" in data:
                    title = str(data["title"] or "").strip()[:120]
                    if not title:
                        raise ApiError(400, "title must not be empty")
                    self.conn.execute(
                        "UPDATE assistant_conversations SET title=?, "
                        "updated_at=datetime('now') WHERE id=?", (title, cid))
                if "project_id" in data:
                    pid = data["project_id"]
                    if pid:
                        self._own_project(str(pid), user["id"])
                    self.conn.execute(
                        "UPDATE assistant_conversations SET project_id=?, "
                        "updated_at=datetime('now') WHERE id=?",
                        (pid or None, cid))
                self.conn.commit()
                row = self.conn.execute(
                    "SELECT * FROM assistant_conversations WHERE id=?", (cid,)).fetchone()
                return self._send(200, {"conversation": dict(row)})
            if len(parts) == 5 and method == "DELETE":
                self.conn.execute(
                    "DELETE FROM assistant_conversations WHERE id=?", (cid,))
                self.conn.commit()
                return self._send(200, {"deleted": True})
            if len(parts) == 6 and parts[5] == "messages":
                if method == "GET":
                    msgs = self.conn.execute(
                        "SELECT * FROM assistant_messages WHERE conversation_id=? "
                        "AND user_id=? ORDER BY created_at ASC LIMIT 200",
                        (cid, user["id"])).fetchall()
                    return self._send(200, {"messages": [self._asst_msg_out(m) for m in msgs]})
                if method == "POST":
                    data = self._read_json()
                    msg = self._asst_handle_message(conv, user, data.get("content"))
                    return self._send(201, {"message": msg})
                raise ApiError(404, "Not found")
            if len(parts) == 7 and parts[5] == "proposals" and method == "POST":
                pid = parts[6]
                prop = self.conn.execute(
                    "SELECT * FROM assistant_proposals WHERE id=? AND user_id=?",
                    (pid, user["id"])).fetchone()
                if not prop or prop["conversation_id"] != cid:
                    raise ApiError(404, "Proposal not found")
                if prop["status"] != "pending":
                    raise ApiError(409, f"Proposal is already {prop['status']}")
                data = self._read_json()
                decision = str(data.get("decision", "")).strip().lower()
                if decision not in ("approve", "deny"):
                    raise ApiError(400, "decision must be approve or deny")
                if decision == "deny":
                    self.conn.execute(
                        "UPDATE assistant_proposals SET status='denied', "
                        "decided_at=datetime('now') WHERE id=?", (pid,))
                    self.conn.commit()
                    self._asst_store_message(
                        cid, user["id"], "assistant",
                        f"Proposal declined — no change was made: {prop['summary']}.",
                        None, "general guidance")
                    return self._send(200, {"proposal": "denied"})
                self._asst_apply_proposal(prop, user)
                self._asst_store_message(
                    cid, user["id"], "assistant",
                    f"Approved and applied: {prop['summary']}.",
                    None, "verified calculation")
                return self._send(200, {"proposal": "applied"})
        raise ApiError(404, "Not found")

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
        if len(parts) == 5 and parts[4] == "materials" and method == "POST":
            # Select a material for this project (owner only). The
            # material id is stored in payload.materials; the material
            # data itself stays in the materials tables.
            row = self._own_project(parts[3], user["id"])
            data = self._read_json()
            mid = str(data.get("material_id", "")).strip()
            if not dbmod.fetch_material(self.conn, mid):
                raise ApiError(404, "Material not found")
            payload = json.loads(row["payload"]) or {}
            selected = payload.get("materials") or []
            if mid not in selected:
                selected.append(mid)
            payload["materials"] = selected
            self.conn.execute(
                "UPDATE projects SET payload=?, updated_at=? WHERE id=? AND owner_id=?",
                (json.dumps(payload), now_iso(), parts[3], user["id"]))
            self.conn.commit()
            row = self.conn.execute(dbmod.PROJECT_SELECT + " WHERE projects.id=?",
                                    (parts[3],)).fetchone()
            return self._send(200, {"project": dbmod.project_public(row)})
        if len(parts) == 6 and parts[4] == "materials" and method == "DELETE":
            row = self._own_project(parts[3], user["id"])
            payload = json.loads(row["payload"]) or {}
            selected = [m for m in (payload.get("materials") or [])
                        if m != parts[5]]
            payload["materials"] = selected
            self.conn.execute(
                "UPDATE projects SET payload=?, updated_at=? WHERE id=? AND owner_id=?",
                (json.dumps(payload), now_iso(), parts[3], user["id"]))
            self.conn.commit()
            row = self.conn.execute(dbmod.PROJECT_SELECT + " WHERE projects.id=?",
                                    (parts[3],)).fetchone()
            return self._send(200, {"project": dbmod.project_public(row)})
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


def _comparison_table(mats):
    """Side-by-side comparison rows, computed from stored data.
    `best` is the index of the best value in that row (None when
    values are missing or not comparable, e.g. hardness scales)."""
    labels = {
        "density_kg_m3": ("Density", "kg/m³", "min"),
        "tensile_strength_mpa": ("Tensile strength", "MPa", "max"),
        "compressive_strength_mpa": ("Compressive strength", "MPa", "max"),
        "yield_strength_mpa": ("Yield strength", "MPa", "max"),
        "elastic_modulus_gpa": ("Elastic modulus", "GPa", "max"),
        "poisson_ratio": ("Poisson's ratio", "—", None),
        "shear_modulus_gpa": ("Shear modulus", "GPa", "max"),
        "thermal_conductivity_w_mk": ("Thermal conductivity", "W/m·K", "max"),
        "specific_heat_j_kgk": ("Specific heat", "J/kg·K", "max"),
        "thermal_expansion_um_mk": ("Thermal expansion", "µm/m·K", "min"),
        "melting_point_c": ("Melting point", "°C", "max"),
        "electrical_resistivity_ohm_m": ("Electrical resistivity", "Ω·m", "min"),
        "electrical_conductivity_pct_iacs": ("Electrical conductivity", "% IACS", "max"),
        "fatigue_limit_mpa": ("Fatigue limit", "MPa", "max"),
        "fracture_toughness_mpa_sqrt_m": ("Fracture toughness", "MPa√m", "max"),
    }
    rows = []
    for key, (label, unit, direction) in labels.items():
        values = [m["properties"].get(key) for m in mats]
        best = None
        present = [(i, v) for i, v in enumerate(values) if v is not None]
        if direction and len(present) >= 2:
            best = (max if direction == "max" else min)(present, key=lambda t: t[1])[0]
        rows.append({"key": key, "label": label, "unit": unit,
                     "values": values, "best": best})
    # Derived metrics + cost + corrosion.
    for key, label, unit, direction in [
            ("strength_to_weight_kn_m_kg", "Strength-to-weight", "kN·m/kg", "max"),
            ("specific_stiffness", "Specific stiffness", "10⁶ m²/s²", "max")]:
        values = [m["derived"].get(key) for m in mats]
        present = [(i, v) for i, v in enumerate(values) if v is not None]
        best = max(present, key=lambda t: t[1])[0] if len(present) >= 2 else None
        rows.append({"key": key, "label": label, "unit": unit,
                     "values": values, "best": best})
    for key, label, unit, direction in [
            ("cost_index", "Relative cost (1 cheap – 5 expensive)", "1–5", "min"),
            ("corrosion_resistance", "Corrosion resistance", "1–5", "max")]:
        values = [m.get(key) for m in mats]
        present = [(i, v) for i, v in enumerate(values) if v is not None]
        best = (max if direction == "max" else min)(present, key=lambda t: t[1])[0] \
            if len(present) >= 2 else None
        rows.append({"key": key, "label": label, "unit": unit,
                     "values": values, "best": best})
    return rows


def main():
    port = int(os.environ.get("AIELAB_PORT", "8001"))
    conn = dbmod.connect()
    dbmod.init_db(conn)
    conn.close()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"AI Engineering Laboratory API — Stage 7")
    print(f"Listening on http://127.0.0.1:{port}  (health: /health)")
    print("Set AIELAB_SECRET in production; AIELAB_DB to change the database file.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
