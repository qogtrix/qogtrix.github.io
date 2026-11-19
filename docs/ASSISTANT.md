# AI Engineering Assistant — Stage 11

19 Nov 2026. A lightweight, per-user AI assistant (`assistant.html`,
`backend/assistant.py`) that routes natural-language requests to the
laboratory's existing engines. It does NOT train or host a large
language model, it does NOT duplicate any engineering engine, and it
is NOT an autonomous agent.

## What it is

Three layers, each deliberately small:

1. **Provider layer.** The default provider is the built-in local
   engine: a deterministic intent parser + the real solvers. External
   AI model APIs (OpenAI-compatible, Anthropic, Gemini, or a custom
   endpoint) are supported through one interface, configured
   server-side only (`AIELAB_AI_PROVIDER`, `AIELAB_AI_MODEL`,
   `AIELAB_AI_API_KEY`, `AIELAB_AI_ENDPOINT`). The key is never
   returned, logged, or sent to the frontend — the config endpoint
   reports only whether one is set. An external provider is used
   ONLY to draft free-text explanations. It never selects tools,
   never supplies tool arguments, and never supplies numbers. If
   it fails (missing key, outage, bad response), the local engine
   answers and the failure is recorded in usage.
2. **Tool layer.** A registry of 27 tools, each a thin wrapper
   around an existing solver or module (Stages 4–10). The intent
   engine picks a tool from the user's words, extracts parameters
   with a unit-aware parser (mm/cm/m, kN/N, MPa/GPa, rpm, kW, V/A/Ω,
   µF/nF, m², "1k" = 1000 Ω), validates them, and executes. Missing
   parameters are asked for — with suggested defaults the user must
   confirm — never invented. A solver refusal is reported honestly
   ("The calculation could not run: …"), never papered over.
3. **Conversation layer.** Conversations, messages, proposals and
   usage live in the same database (four new tables, schema v4).
   Every row carries `user_id` and every query filters by it.
   Project access is re-verified against ownership on every call;
   another user's conversation or project behaves as if it does
   not exist (404).

## Tools (27)

- **Materials:** material lookup, material comparison (2–4).
- **Mechanical:** gear train, shaft (combined bending + torsion),
  belt drive, helical spring, vibration (1 DOF), power transmission.
- **Electrical:** Ohm's law, RC time constant, RLC resonance,
  DC motor, battery configuration, voltage divider (built and
  solved with the Stage 8 MNA solver).
- **Structural:** cantilever beam, simply supported beam, column
  buckling, wind load (IS 875), plus project inspection.
- **Aerospace:** airfoil lift, stall speed, rocket delta-v,
  multirotor hover.
- **Robotics:** forward kinematics, 2R inverse kinematics, PID
  step response.
- **Projects:** inspect my project, propose a project change.

Beam/column sections are parsed from the message ("0.1x0.2 m",
"100x100 mm square") or fall back to a stated default section
listed as an assumption. Material properties come from the
database; a missing property is a refusal, never a substitution.

## Proposals and approval

The assistant may PROPOSE a project change (currently: a
structure element's section, or an aircraft cruise speed / mass).
The proposal is stored as `pending` and shown with Approve/Deny
buttons. Nothing is applied until the user approves it — verified
by test: the structure is byte-identical before approval, changes
only after approval (version bumped), and a denied proposal leaves
it untouched. Approval re-verifies project ownership.

## Provenance

Every assistant message carries a provenance label:

- **Verified calculation** — an analytical solver ran.
- **Simulation result** — the MNA circuit solver ran.
- **Database value** — material/project data.
- **Estimate** — labelled as such (used sparingly).
- **General guidance** — explanations from the built-in knowledge
  base or an external provider's prose; never a number.
- **Proposal** — a change awaiting approval.

Assumptions are listed in the reply (default section, end
condition k = 1.0, motor parameters for PID demos, "per 1 V step"
for RC without a voltage).

## Isolation and security

- Auth is the existing session/API-key auth. The frontend never
  sends a user id; the backend takes it from the verified token.
- Every conversation/message/proposal/usage query filters by
  `user_id`. Cross-user access returns 404 (no existence leak).
- Tool arguments come only from the structured parser (numbers +
  whitelisted enums), never from raw message text passed through.
  Provider responses are untrusted prose and cannot trigger a
  tool call. No eval, no shell, no frontend-provided ownership
  claims.
- Rate limits: 30 messages/user/minute, 200/hour (in-memory,
  per process). Exceeding returns 429 and is recorded.
- Message length is capped at 4000 characters.
- **Muse separation:** this assistant is a separate service with
  its own accounts. It has no access to Muse's session, browser
  session, credentials, or private context, and Muse has no access
  to other users' assistant conversations through this platform.

## Usage and costs

Every request records provider, model, estimated tokens
(len ÷ 4), cost (from the configured per-1k-token rates), status
and duration. The local engine costs $0. External rates are
configured estimates — verify against the provider's current
pricing before relying on them. `GET /api/v1/assistant/usage`
returns per-user totals and the last 50 rows.

## API

- `GET /api/v1/assistant/config` — provider status (never the key).
- `GET /api/v1/assistant/tools` — the tool registry.
- `GET /api/v1/assistant/usage` — per-user usage and costs.
- `GET/POST /api/v1/assistant/conversations` — list / create.
- `GET/PATCH/DELETE /api/v1/assistant/conversations/{id}` —
  read with messages and proposals / rename / attach or detach a
  project / delete (cascades to messages and proposals).
- `GET/POST /api/v1/assistant/conversations/{id}/messages` —
  history / send a message.
- `POST /api/v1/assistant/conversations/{id}/proposals/{pid}` —
  `{decision: "approve" | "deny"}`.

## Frontend

`assistant.html` + `assets/js/assistant.js`: conversation
sidebar (create/rename/delete), project attach selector, chat
with provenance badges, tool-call cards (tool, status,
provenance, source), proposal Approve/Deny buttons, example
prompt chips, provider status and usage panels. Mobile
responsive (sidebar stacks above the chat). No external JS
libraries — the markdown renderer is ~40 lines.

## Honest limits

- **No large language model is hosted or trained.** The local
  engine is a deterministic intent parser: it understands the
  phrasings in the tool registry and asks when it does not. It
  will not understand a request phrased very differently from
  the examples, and it says so rather than guessing.
- **No external provider is configured by default.** Explanations
  for topics outside the built-in knowledge base fall back to a
  short capabilities reply until a provider key is set
  server-side.
- **Proposals cover two change types only** (structure section,
  aircraft cruise speed/mass). Anything else is refused with an
  explanation of what is supported.
- **Rate limits are in-memory** (per backend process). A restart
  resets them; a multi-process deployment would need a shared
  store.
- **Token counts are estimates** (characters ÷ 4) for the local
  engine; exact counts come from the provider's response when an
  external provider is used (not yet wired — the estimate is
  used and labelled as such).
- **Long calculations run synchronously** in the message request
  (all current tools finish in well under a second). The existing
  job system (`simulations` table) is reused for analyses that
  need it; no new queue was built.
- **The chat was not probed in a live browser** from this
  environment (syntax checked with `node --check`; pages serve
  200). The API behind it is fully tested end-to-end.
