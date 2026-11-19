# Backend — Stage 2 (real, running)

**Stdlib only — no pip install needed.** The Stage 1 FastAPI plan
was changed in Stage 2 for a concrete reason: this machine has no
FastAPI / uvicorn / PyJWT installed, and a zero-dependency backend
runs anywhere with just `python3`. FastAPI remains an option for a
later stage; the API contract in `api-spec.md` is framework-neutral,
so the frontend does not care which one serves it.

## Run

```bash
cd backend
python3 app.py          # http://127.0.0.1:8001, /health
```

Environment: `AIELAB_PORT` (default 8001), `AIELAB_DB`
(default `backend/aielab.db`, SQLite), `AIELAB_SECRET`
(signing secret — **set this in production**; without it a
`backend/.secret` file is generated once, mode 0600).

## Files

- `app.py` — HTTP server + all routes (auth, projects, materials,
  health). Simulation routes still return 501.
- `auth.py` — PBKDF2 password hashing, HMAC-signed session tokens,
  API-key generation.
- `db.py` — SQLite connection + schema loading (`db/schema.sql`
  is the single source of truth for the data model).
- `test_stage2.py` — 34 automated tests, two accounts, real HTTP.
  Run: `cd backend && python3 test_stage2.py`
- `requirements.txt` — intentionally empty (stdlib only).

## Security summary

- Passwords: PBKDF2-HMAC-SHA256, 200,000 iterations, per-user salt.
  Only the hash is stored; plain passwords never touch the database.
- Sessions: HMAC-signed tokens, 7-day expiry, stored as a hash in
  the `sessions` table. Logout deletes the session row.
- Login rate limit: 5 failed attempts per email per 15 minutes → 429.
- Projects: every query filters `owner_id = current user`. A project
  owned by someone else returns 404 (no existence leak).
- API keys (`aielab_…`): SHA-256 hash stored, full key shown once.
  Scoped to one user; revocable in Account Settings.
