# API Spec — Stage 2 (implemented, tested)

Base: `/api/v1`. Backend: `backend/app.py` (stdlib, SQLite).
Auth: `Authorization: Bearer <session token>` or
`Authorization: Bearer aielab_<api key>`.

## Health (public)

`GET /health` → `{"status":"ok","stage":2,"solver_available":false}`

## Auth

| Method & path | Body | Success | Errors |
|---|---|---|---|
| `POST /api/v1/auth/register` | `{email, password>=8, name}` | 201 `{user, token}` | 400 validation, 409 email exists |
| `POST /api/v1/auth/login` | `{email, password}` | 200 `{user, token}` | 401 wrong credentials, 429 too many failures |
| `POST /api/v1/auth/logout` | — (auth) | 200 `{ok:true}` — session revoked | 401 |
| `GET /api/v1/auth/me` | — (auth) | 200 `{user}` | 401 |
| `PATCH /api/v1/auth/me` | `{name}` | 200 `{user}` | 400, 401 |
| `POST /api/v1/auth/change-password` | `{current_password, new_password>=8}` | 200 — other sessions revoked | 400, 401 |
| `POST /api/v1/auth/api-keys` | `{name}` | 201 `{id, name, key_prefix, key}` — key shown **once** | 401 |
| `GET /api/v1/auth/api-keys` | — (auth) | 200 `{api_keys:[...]}` (hashes never returned) | 401 |
| `DELETE /api/v1/auth/api-keys/{id}` | — (auth) | 200 — key revoked | 401, 404 |

## Projects (auth required, always owner-scoped)

| Method & path | Notes |
|---|---|
| `GET /api/v1/projects?q=&lab=` | Only the caller's projects, newest first. `lab` must be a known lab. |
| `POST /api/v1/projects` | `{name 2–120, description, lab, payload{}}` → 201 |
| `GET /api/v1/projects/{id}` | 404 if the project is not the caller's (no existence leak) |
| `PATCH /api/v1/projects/{id}` | Rename / edit description / lab / save `payload` progress |
| `POST /api/v1/projects/{id}/duplicate` | Copy with ` (copy)` suffix, new id, same owner |
| `DELETE /api/v1/projects/{id}` | Deletes only the caller's project |

All project errors: 401 unauthenticated, 404 not yours / not found,
400 validation.

## Unique usernames (Stage 3)

- Register now requires `username` (3–30 chars, `[a-z0-9_]`, unique
  case-insensitively) → 409 if taken.
- Login accepts `email` **or** `username` as the identifier.
- `PATCH /api/v1/auth/me` accepts `username` (409 if taken).
- Public responses show `owner_username` only — never email.

## Visibility (Stage 3)

- `POST /api/v1/projects` — new projects are **always private**;
  a `visibility` value in the request is ignored.
- `POST /api/v1/projects/{id}/publish` — owner only → `public`.
- `POST /api/v1/projects/{id}/unpublish` — owner only → `private`.
- `PATCH /api/v1/projects/{id}` — owner may set `visibility`
  to `private` or `public`.
- Duplicates are always created private.
- `GET /api/v1/projects?visibility=private|public` — owner's own
  projects, filterable by visibility.

## Public gallery (Stage 3, no auth required)

- `GET /api/v1/public/projects?q=&lab=` — public projects only,
  newest first. Response contains no `email` or `owner_id`.
- `GET /api/v1/public/projects/{id}` — public project detail
  (read-only); 404 for private or nonexistent projects.

## Public data (read-only)

`GET /api/v1/materials`, `GET /api/v1/components` — served from
`data/*.json`.

## Simulations (not in Stage 2)

`POST /api/v1/simulate/*` → 501 Not Implemented. `results` stays
`null` until a real solver exists (Stage 3).
