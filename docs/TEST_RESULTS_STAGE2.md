# Stage 2 — Test Results (two separate accounts)

**Date:** 19 Nov 2026
**How:** `cd backend && python3 test_stage2.py` — real backend on a
temporary SQLite database, real HTTP requests (no mocks for auth
or ownership). A second live check was also done with `curl`
against the backend on port 8001 + the static site on port 8124.

## Result: 34 / 34 tests passed

```
PASS  health endpoint
PASS  register Alice
PASS  register Bob
PASS  duplicate email rejected (409)
PASS  invalid email rejected (400)
PASS  short password rejected (400)
PASS  wrong password rejected (401)
PASS  no token rejected (401)
PASS  bad token rejected (401)
PASS  Alice /me returns her profile
PASS  Alice creates project 1
PASS  Alice creates project 2
PASS  Bob creates project
PASS  Alice sees only her 2 projects
PASS  Bob sees only his 1 project
PASS  Bob cannot GET Alice's project (404)
PASS  Bob cannot rename Alice's project (404)
PASS  Bob cannot delete Alice's project (404)
PASS  Alice's project intact after Bob's attempts
PASS  Bob cannot duplicate Alice's project (404)
PASS  Alice renames + saves progress
PASS  Alice duplicates her own project
PASS  Alice search finds beam project only
PASS  Alice lab filter works
PASS  Alice creates API key (shown once)
PASS  API key lists owner's projects
PASS  API key cannot reach Bob's project (404)
PASS  Alice deletes her own project
PASS  Deleted project gone from Alice's list
PASS  Alice logout succeeds
PASS  Old token rejected after logout (401)
PASS  Alice logs in again
PASS  Projects persist after logout + login
PASS  invalid lab rejected (400)

34/34 tests passed
```

## What the tests verify (mapped to the Stage 2 spec §8)

| Requirement | Evidence |
|---|---|
| Both users can create projects | Alice created 2, Bob created 1 |
| Each user sees only their own projects | Alice list = her 2; Bob list = his 1 |
| One user cannot retrieve another's private project | Bob GET / PATCH / DELETE / duplicate Alice's project → 404, project intact |
| Project changes persist after logout and login | Rename + saved payload still present after logout, rejected old token, fresh login |
| Unauthorized API requests are rejected | No token → 401, bad token → 401, wrong password → 401, duplicate email → 409, invalid input → 400 |
| Muse key scoping (prep) | Alice's API key lists her 3 projects; same key + Bob's project → 404 |

## Live curl check (separate from the test suite)

- `POST /api/v1/auth/register` as karan@example.com → 201, token issued
- `GET /api/v1/auth/me` with token → correct profile
- `POST /api/v1/projects` → 201, project with `owner_id` = Karan's id
- `GET /api/v1/projects` with token → 1 project; without token → 401
- Static pages `/auth.html`, `/projects.html`, `/settings.html` → 200

## Not tested / known limits

- The hosted fullstack Stage 2 app is built by Muse's artifact
  builder (separate implementation of the same contract) — its own
  verification is reported with that build, not in this file.
- Postgres RLS policies in `db/schema.sql` are defined but not
  executed against a live Postgres instance in Stage 2 (SQLite is
  the tested engine; backend ownership checks are the tested
  enforcement layer).
- No email verification / password reset by email in Stage 2
  (password change works while signed in; reset via support is
  a later stage).
