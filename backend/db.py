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
    conn.commit()


def new_id(prefix: str) -> str:
    return prefix + "_" + uuid.uuid4().hex[:16]


def user_public(row) -> dict:
    return {"id": row["id"], "email": row["email"], "name": row["name"],
            "created_at": row["created_at"]}


def project_public(row) -> dict:
    payload = row["payload"]
    try:
        payload = json.loads(payload) if payload else {}
    except Exception:
        payload = {}
    return {"id": row["id"], "owner_id": row["owner_id"],
            "name": row["name"], "description": row["description"],
            "lab": row["lab"], "payload": payload,
            "created_at": row["created_at"], "updated_at": row["updated_at"]}
