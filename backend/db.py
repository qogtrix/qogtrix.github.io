"""SQLite storage for Stage 2. Stdlib only (sqlite3).

One file: backend/aielab.db (created on first run, git-ignored).
Schema is defined in db/schema.sql — this module executes the
Stage 2 tables from it, so the SQL file stays the single source
of truth for the data model. Foreign keys are enforced
(PRAGMA foreign_keys = ON) on every connection.
"""
import json
import os
import sqlite3
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_DB = os.path.join(HERE, "aielab.db")


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or os.environ.get("AIELAB_DB") or DEFAULT_DB
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    schema_path = os.path.join(ROOT, "db", "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        sql = f.read()
    # schema.sql contains a Postgres RLS section after a marker;
    # SQLite must only run the portable part before it.
    sql = sql.split("-- === POSTGRES RLS")[0]
    conn.executescript(sql)
    _migrate(conn)
    conn.commit()


def _columns(conn, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn: sqlite3.Connection) -> None:
    """Stage 2 -> Stage 3 migrations for existing databases.
    Fresh databases already have the columns from schema.sql."""
    import re as _re
    if "username" not in _columns(conn, "users"):
        conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
        # Backfill: derive a unique username from the email local part.
        for row in conn.execute("SELECT id, email FROM users WHERE username IS NULL OR username=''"):
            base = _re.sub(r"[^a-z0-9_]", "_", row["email"].split("@")[0].lower()).strip("_") or "user"
            if len(base) < 3:
                base = (base + "user")[:30]
            candidate, n = base[:30], 2
            while conn.execute("SELECT 1 FROM users WHERE username=?", (candidate,)).fetchone():
                candidate = f"{base[:24]}_{n}"
                n += 1
            conn.execute("UPDATE users SET username=? WHERE id=?", (candidate, row["id"]))
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    if "visibility" not in _columns(conn, "projects"):
        conn.execute("ALTER TABLE projects ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'")
        conn.execute("UPDATE projects SET visibility='private' WHERE visibility IS NULL OR visibility=''")


def new_id(prefix: str) -> str:
    return prefix + "_" + uuid.uuid4().hex[:16]


def user_public(row) -> dict:
    return {"id": row["id"], "email": row["email"],
            "username": row["username"] if "username" in row.keys() else None,
            "name": row["name"], "created_at": row["created_at"]}


def project_public(row) -> dict:
    """Owner view: full project, including owner_id and visibility."""
    payload = row["payload"]
    try:
        payload = json.loads(payload) if payload else {}
    except Exception:
        payload = {}
    keys = row.keys()
    return {"id": row["id"], "owner_id": row["owner_id"],
            "owner_username": row["owner_username"] if "owner_username" in keys else None,
            "name": row["name"], "description": row["description"],
            "lab": row["lab"],
            "visibility": row["visibility"] if "visibility" in keys else "private",
            "payload": payload,
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def project_public_view(row) -> dict:
    """Public gallery view: published information only.
    Never includes owner_id or email — only the public username."""
    payload = row["payload"]
    try:
        payload = json.loads(payload) if payload else {}
    except Exception:
        payload = {}
    keys = row.keys()
    return {"id": row["id"],
            "owner_username": row["owner_username"] if "owner_username" in keys else None,
            "name": row["name"], "description": row["description"],
            "lab": row["lab"], "visibility": "public",
            "payload": payload,
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


PROJECT_SELECT = ("SELECT projects.*, users.username AS owner_username "
                  "FROM projects JOIN users ON users.id = projects.owner_id")
