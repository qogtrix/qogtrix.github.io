"""SQLite storage for Stage 2. Stdlib only (sqlite3).

One file: backend/aielab.db (created on first run, git-ignored).
Schema is defined in db/schema.sql — this module executes the
Stage 2 tables from it, so the SQL file stays the single source
of truth for the data model. Foreign keys are enforced
(PRAGMA foreign_keys = ON) on every connection.

Deployment (₹0): when TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are set,
the same SQL runs against a Turso (libSQL) database instead, through a
thin wrapper below. Turso speaks the SQLite dialect (including
json_extract), so no query changes. The local file then acts as an
embedded replica: reads are local, and every commit syncs to Turso, so
data survives the host's ephemeral disk. Set AIELAB_DB_DRIVER=libsql
to exercise the libsql wrapper against a plain local file (no sync)
— used by the regression suite.
"""
import json
import os
import sqlite3
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_DB = os.path.join(HERE, "aielab.db")


class _Row:
    """Minimal sqlite3.Row stand-in for the libsql wrapper.

    Supports row["col"], row[0], row.keys(), iteration over values,
    len(row), and {**row} unpacking — everything the app uses.
    """

    __slots__ = ("_columns", "_values")

    def __init__(self, columns, values):
        self._columns = list(columns)
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._values[self._columns.index(key)]

    def keys(self):
        return list(self._columns)

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return repr(dict(zip(self._columns, self._values)))


class _Cursor:
    """Wraps a libsql cursor so fetched rows are _Row objects."""

    def __init__(self, raw):
        self._raw = raw

    def _convert(self, rows):
        if rows is None:
            return None
        cols = [d[0] for d in (self._raw.description or [])]
        return [_Row(cols, r) for r in rows]

    def fetchone(self):
        row = self._raw.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in (self._raw.description or [])]
        return _Row(cols, row)

    def fetchall(self):
        return self._convert(self._raw.fetchall())

    def fetchmany(self, size=None):
        if size is None:
            return self._convert(self._raw.fetchmany())
        return self._convert(self._raw.fetchmany(size))

    def __iter__(self):
        # The libsql cursor is not itself iterable; pull the rows.
        return iter(self.fetchall())

    def __getattr__(self, name):
        return getattr(self._raw, name)


class _Connection:
    """Wraps a libsql connection with the sqlite3 surface the app uses.

    Every commit is followed by a sync to Turso (one retry), so a write
    is durable in the cloud before the request returns. Without a
    sync_url (local file mode) sync is skipped.
    """

    def __init__(self, raw, syncable):
        self._raw = raw
        self._syncable = syncable

    def execute(self, sql, parameters=()):
        return _Cursor(self._raw.execute(sql, parameters))

    def executemany(self, sql, parameters):
        return _Cursor(self._raw.executemany(sql, parameters))

    def executescript(self, sql):
        return self._raw.executescript(sql)

    def cursor(self):
        return _Cursor(self._raw.cursor())

    def commit(self):
        self._raw.commit()
        if self._syncable:
            try:
                self._raw.sync()
            except Exception:
                time.sleep(1)
                self._raw.sync()  # raise if it fails again

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()

    def sync(self):
        if self._syncable:
            self._raw.sync()

    def __getattr__(self, name):
        return getattr(self._raw, name)


def connect(db_path: str | None = None):
    url = os.environ.get("TURSO_DATABASE_URL")
    token = os.environ.get("TURSO_AUTH_TOKEN")
    force_libsql = os.environ.get("AIELAB_DB_DRIVER") == "libsql"
    if (url and token) or force_libsql:
        import libsql

        local = db_path or os.environ.get("AIELAB_DB") or DEFAULT_DB
        first_boot = (not os.path.exists(local)) or os.path.getsize(local) == 0
        raw = libsql.connect(local, sync_url=url or None,
                             auth_token=token or "")
        raw.execute("PRAGMA foreign_keys = ON")
        if url and first_boot:
            # Fresh replica on an ephemeral disk: pull the cloud copy.
            raw.sync()
        return _Connection(raw, syncable=bool(url))
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
    seed_materials(conn)
    conn.commit()


# -- Stage 4: normalized material database ---------------------------
# The authoritative material content is data/materials.json. On first
# run the tables are seeded from it; on later runs the tables are
# the source of truth, so edits made through a future admin UI persist.
# A NULL property means "not available" — never zero, never invented.
PROPERTY_UNITS = {
    "density_kg_m3": "kg/m³", "tensile_strength_mpa": "MPa",
    "compressive_strength_mpa": "MPa", "yield_strength_mpa": "MPa",
    "elastic_modulus_gpa": "GPa", "poisson_ratio": "—",
    "shear_modulus_gpa": "GPa", "thermal_conductivity_w_mk": "W/m·K",
    "specific_heat_j_kgk": "J/kg·K", "thermal_expansion_um_mk": "µm/m·K",
    "melting_point_c": "°C", "electrical_resistivity_ohm_m": "Ω·m",
    "electrical_conductivity_pct_iacs": "% IACS",
    "fatigue_limit_mpa": "MPa",
    "fracture_toughness_mpa_sqrt_m": "MPa√m",
}
PROPERTY_KEYS = list(PROPERTY_UNITS.keys()) + ["hardness"]


def load_materials_json() -> dict:
    path = os.path.join(ROOT, "data", "materials.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"materials": []}


def seed_materials(conn: sqlite3.Connection) -> None:
    """Seed the normalized materials tables from data/materials.json
    if they are empty. Existing rows are never overwritten."""
    try:
        count = conn.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
    except Exception:
        return
    if count:
        return
    data = load_materials_json()
    for m in data.get("materials", []):
        props = m.get("properties", {}) or {}
        temp = m.get("temperature_range_c") or [None, None]
        conn.execute(
            "INSERT INTO materials(id,name,grade,category,standard,source,"
            " confidence,test_conditions,temp_min_c,temp_max_c,cost_index,"
            " cost_note,corrosion_resistance,corrosion_note,notes)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (m["id"], m["name"], m.get("grade"), m["category"],
             m.get("standard"), m.get("source"), m.get("confidence", "typical"),
             m.get("test_conditions"), temp[0], temp[1],
             m.get("cost_index"), m.get("cost_note"),
             m.get("corrosion_resistance"), m.get("corrosion_note"),
             m.get("notes")))
        for key in PROPERTY_KEYS:
            val = props.get(key)
            if key == "hardness":
                if isinstance(val, dict):
                    conn.execute(
                        "INSERT INTO material_properties(material_id,property_key,"
                        " value_num,value_text,unit,confidence) VALUES (?,?,?,?,?,?)",
                        (m["id"], key, val.get("value"),
                         f"{val.get('value')} {val.get('scale')}",
                         val.get("scale"), m.get("confidence", "typical")))
                else:
                    conn.execute(
                        "INSERT INTO material_properties(material_id,property_key,"
                        " value_num,value_text,unit,confidence) VALUES (?,?,?,?,?,?)",
                        (m["id"], key, None, None, None,
                         m.get("confidence", "typical")))
                continue
            conn.execute(
                "INSERT INTO material_properties(material_id,property_key,"
                " value_num,value_text,unit,confidence) VALUES (?,?,?,?,?,?)",
                (m["id"], key, val,
                 None if val is None else str(val),
                 PROPERTY_UNITS.get(key), m.get("confidence", "typical")))


def material_row_to_dict(row, props: dict) -> dict:
    """Full material view from a materials row + its property rows.
    `props` maps property_key -> (value_num, value_text, unit)."""
    properties = {}
    missing = []
    for key in PROPERTY_KEYS:
        num, text, unit = props.get(key, (None, None, None))
        if key == "hardness":
            properties[key] = None
            if num is not None:
                properties[key] = {"value": num, "scale": unit}
            else:
                missing.append(key)
        else:
            properties[key] = num
            if num is None:
                missing.append(key)
    temp = None
    if row["temp_min_c"] is not None or row["temp_max_c"] is not None:
        temp = [row["temp_min_c"], row["temp_max_c"]]
    derived = {}
    d = properties.get("density_kg_m3")
    t = properties.get("tensile_strength_mpa")
    e = properties.get("elastic_modulus_gpa")
    if t is not None and d:
        # kN·m/kg — tensile strength per unit density
        derived["strength_to_weight_kn_m_kg"] = round(t * 1000 / d, 1)
    if e is not None and d:
        # 10^6 m²/s² — elastic modulus per unit density
        derived["specific_stiffness"] = round(e * 1000 / d, 1)
    return {"id": row["id"], "name": row["name"], "grade": row["grade"],
            "category": row["category"], "standard": row["standard"],
            "source": row["source"], "confidence": row["confidence"],
            "test_conditions": row["test_conditions"],
            "temperature_range_c": temp,
            "cost_index": row["cost_index"], "cost_note": row["cost_note"],
            "corrosion_resistance": row["corrosion_resistance"],
            "corrosion_note": row["corrosion_note"], "notes": row["notes"],
            "properties": properties, "missing_properties": missing,
            "derived": derived,
            # Convenience top-level fields (Stage 1 compatibility):
            "density": d, "tensile_strength": t,
            "yield_strength": properties.get("yield_strength_mpa"),
            "youngs_modulus": e,
            "melting_point": properties.get("melting_point_c"),
            "thermal_conductivity": properties.get("thermal_conductivity_w_mk"),
            "poisson": properties.get("poisson_ratio")}


def fetch_material(conn, material_id: str):
    row = conn.execute("SELECT * FROM materials WHERE id=?",
                       (material_id,)).fetchone()
    if not row:
        return None
    props = {r["property_key"]: (r["value_num"], r["value_text"], r["unit"])
             for r in conn.execute(
                 "SELECT * FROM material_properties WHERE material_id=?",
                 (material_id,))}
    return material_row_to_dict(row, props)


def fetch_materials(conn, where: str = "", args: tuple = ()):
    rows = conn.execute(
        "SELECT * FROM materials " + where + " ORDER BY name", args).fetchall()
    out = []
    for row in rows:
        props = {r["property_key"]: (r["value_num"], r["value_text"], r["unit"])
                 for r in conn.execute(
                     "SELECT * FROM material_properties WHERE material_id=?",
                     (row["id"],))}
        out.append(material_row_to_dict(row, props))
    return out


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
    # Stage 11: the assistant tables are CREATE TABLE IF NOT EXISTS
    # in schema.sql, so existing databases get them from init_db's
    # executescript — nothing to migrate here.
    # Stage 4: the flat Stage 1 materials table (no 'grade' column)
    # is replaced by the normalized materials + material_properties
    # tables. Drop and recreate so the schema is the single source
    # of truth; seed_materials() repopulates from materials.json.
    if "materials" in {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")} \
            and "grade" not in _columns(conn, "materials"):
        conn.execute("DROP TABLE IF EXISTS material_properties")
        conn.execute("DROP TABLE IF EXISTS materials")
        conn.execute("""CREATE TABLE materials (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, grade TEXT,
            category TEXT NOT NULL, standard TEXT, source TEXT,
            confidence TEXT NOT NULL DEFAULT 'typical'
                CHECK (confidence IN ('verified','typical','estimated')),
            test_conditions TEXT, temp_min_c REAL, temp_max_c REAL,
            cost_index INTEGER CHECK (cost_index BETWEEN 1 AND 5),
            cost_note TEXT,
            corrosion_resistance INTEGER CHECK (corrosion_resistance BETWEEN 1 AND 5),
            corrosion_note TEXT, notes TEXT)""")
        conn.execute("""CREATE TABLE material_properties (
            material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
            property_key TEXT NOT NULL, value_num REAL, value_text TEXT,
            unit TEXT, confidence TEXT NOT NULL DEFAULT 'typical'
                CHECK (confidence IN ('verified','typical','estimated')),
            PRIMARY KEY (material_id, property_key))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS material_favorites (
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, material_id))""")


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
