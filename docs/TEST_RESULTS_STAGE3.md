# Stage 3 — Test Results (two separate accounts)

**Date:** 19 Nov 2026
**How:** `cd backend && python3 test_stage3.py` — real backend on a
temporary SQLite database, real HTTP. Stage 2 suite re-run as well:
34/34 still passing. A separate live curl check confirmed the
publish → gallery → unpublish flow against the backend on port 8001.

## Result: 34 / 34 tests passed (Stage 3) + 34 / 34 (Stage 2)

Stage 3 tests:

```
PASS  register Alice (username alice)
PASS  duplicate username rejected (409, case-insensitive)
PASS  too-short username rejected (400)
PASS  invalid username chars rejected (400)
PASS  register Bob (username bob)
PASS  login by username works
PASS  A: Alice creates project — defaults to private even when client sends public
PASS  B: public gallery is empty (no auth needed)
PASS  B: public search finds nothing
PASS  B: public detail URL for private project → 404
PASS  B: direct API access as Bob → 404
PASS  B: Bob's own list does not contain it
PASS  B: unauthenticated direct access → 401
PASS  C: Alice publishes (explicit publish endpoint)
PASS  C: Bob cannot publish Alice's project (404)
PASS  D: public gallery now lists it
PASS  D: public listing never exposes email or owner_id
PASS  D: public search finds it
PASS  D: Bob views public detail (name, owner, payload published)
PASS  E: Bob cannot rename public project (404)
PASS  E: Bob cannot delete public project (404)
PASS  E: Bob cannot change its visibility (404)
PASS  E: Bob cannot duplicate it (404)
PASS  E: Alice's project unchanged after Bob's attempts
PASS  F: Alice makes it private again
PASS  G: public gallery empty again immediately
PASS  G: public detail URL rejected again (404)
PASS  G: public search finds nothing again
PASS  owner can publish via PATCH visibility
PASS  duplicate of a public project is private by default
PASS  duplicate does not leak into gallery
PASS  username change to taken name rejected (409)
PASS  owner can change own username
PASS  gallery shows updated username

34/34 tests passed
```

## Mapping to the spec §7 (A–G)

| Step | Evidence |
|---|---|
| A. Alice creates private project | Created with `visibility: "public"` in the request — stored as `private` |
| B. Bob cannot find or open it | Gallery empty, search empty, public detail 404, owner API 404, Bob's list empty, unauthenticated 401 |
| C. Alice changes it to public | `POST /publish` → `visibility: "public"`; Bob's publish attempt → 404 |
| D. Bob can now view it | Gallery lists it with owner `@alice`, search finds it, public detail shows name/description/payload |
| E. Bob cannot modify or delete it | PATCH / DELETE / unpublish / duplicate all 404; Alice's copy unchanged |
| F. Alice changes it back to private | `POST /unpublish` → `visibility: "private"` |
| G. Bob immediately loses access | Gallery empty, detail 404, search empty — same requests as D, now rejected |

## File access

There are no file attachments in Stage 3, so there is no attachment
URL to test. The access rule is fixed in `docs/ARCHITECTURE.md` §16:
any future attachment download must pass the same owner-or-public
check as the project detail endpoint — never a direct static URL.
Private project data was verified not to leak through the public
list/search/detail responses (no `email`, no `owner_id` anywhere
in the public JSON).

## Not tested

- Hosted fullstack app's Stage 3 update (artifact edit, separate
  build — its own verification is reported with that build).
- Live Postgres RLS execution (see Stage 2 test notes).
