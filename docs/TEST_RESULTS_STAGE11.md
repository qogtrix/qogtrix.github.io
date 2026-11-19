# Stage 11 test results — 19 Nov 2026

`backend/test_stage11.py` — **45/45 tests passed.**

## The 12 required categories (all passing)

1. **Engineering question answered** — "what is torque?" returns
   general guidance, no tool call, no invented numbers.
2. **Mechanical calculation** — gear train (20/40 teeth, 1000 rpm,
   10 N·m) runs the Stage 7 solver: output torque 19 N·m,
   output speed 500 rpm, provenance "verified calculation".
3. **Electrical circuit** — "voltage divider 10 V, R1 1k, R2 1k"
   builds the circuit and solves it with the Stage 8 MNA solver:
   Vout 5.0 V, provenance "actual simulation result".
4. **Structural calculation** — column buckling (3 m, 100×100 mm)
   runs the Stage 9 solver: critical load 1,827,704 N.
5. **Material properties** — steel S355: E 200 GPa, yield 355 MPa,
   provenance "database value".
6. **Project inspected** — with a project attached, the assistant
   lists the project name, its structure document (version 2) and
   its simulations.
7. **Modification requires approval** — a section change is
   proposed, the structure is byte-identical before approval,
   changes to rectangle 0.2 × 0.3 m with a version bump after
   approval, a second approval of the same proposal is 409, and
   a denied proposal leaves the structure untouched.
8. **Two users simultaneously** — Alice and Bob send 3 messages
   each from parallel threads; all 6 complete, and each
   conversation contains only its own user's messages.
9. **Unauthorized access rejected** — Bob gets 404 on Alice's
   conversation, on attaching Alice's project, on deciding
   Alice's proposal, and on reading Alice's project.
10. **AI API failure handled** — with `AIELAB_AI_PROVIDER=openai`
    and no key, the config reports the provider as unconfigured,
    the assistant answers honestly ("provider is unavailable…
    no API key configured") via the local engine, and the usage
    row records status `provider_error` with provider `openai`.
11. **Invalid inputs rejected** — missing gear parameters are
    asked for (and completed correctly from the follow-up);
    an impossible rocket (final mass > initial mass) is refused
    with no fake delta-v; empty and over-long messages are 400.
12. **Usage and costs recorded** — Alice's usage totals (17
    requests, tokens, $0.001082 from the single provider-error
    row at the configured OpenAI rates) and Bob's separate
    totals (3 requests) are correct; every local row costs $0.

## Also tested

- Conversation create / rename / attach / detach / delete
  (delete cascades; a deleted conversation is 404).
- Clarification with suggested defaults: a divider without
  resistor values asks, and "yes" applies the suggested 1 kΩ
  resistors (Vout 5 V).
- Rate limit trips after 30 messages/minute (unit-level check).
- History persists across reads (12+ user messages).

## Earlier suites re-run

Stage 2 **34/34**, Stage 3 **34/34**, Stage 4 **42/42**,
Stage 5 **56/56** (backend) + **29/29** (JS maths) +
**28/28** (headless kernel), Stage 6 **29/29** (backend) +
**9/9** (Rapier), Stage 7 **99/99** (backend) + **36/36**
(JS maths) + **22/22** (headless kernel), Stage 8 **71/71**,
Stage 9 **80/80**, Stage 10 **140/140**, Stage 11 **45/45**.
Health assertions accept stage 11. All green — **630 Python
tests** in total.

## Bugs found and fixed while testing Stage 11

- **Unit conversion:** `1000 rpm` was converted to rad/s by the
  unit parser but the gear solver expects rpm. Fixed with
  per-parameter unit conversion (SI → the solver's unit).
- **Section dimensions stole the load:** "5 kN tip load, section
  0.1x0.2 m" assigned 0.1 to the load. Fixed by preferring
  unit-kind matches and by looking for the number before the
  keyword as well as after it.
- **"1 m2" parsed as 1 m + bare 2.** Fixed with area units
  (m2/m²/cm2/mm2) in the parser.
- **"5 degrees" was divided by π/180** because the word
  "degrees" is not a recognised unit. Fixed: only numbers whose
  unit was recognised go through SI conversion.
- **Material lookup failed on "steel S355"** — the parser
  filled the query with the bare number 355.0. Fixed: a
  numeric-only query is ignored and the name is derived from
  the raw text.
- **Proposal apply could not find the element** — the element
  id was stored outside the change document. Fixed by storing
  it inside the change.
- **"explain … design" matched any sentence** containing both
  words (a quantum-tunnelling question was answered by
  inspecting the project). Fixed by narrowing the pattern to
  explicit project/design requests.
- **Follow-up values overwrote given ones** — a clarification
  answer re-extracted all parameters. Fixed: only the missing
  parameters are extracted from a follow-up.
- **Circuit result keys** were `voltages`/`branch_currents`,
  not `node_voltages`/`currents`. Fixed in the divider executor.
- **PID and delta-v result shapes** were nested/flat
  differently than assumed. Fixed in the executors (and the PID
  time series is no longer stored in chat messages).

## Not tested

- Browser rendering of `assistant.html` (syntax checked with
  `node --check`; the page serves 200). The chat, tool cards and
  proposal buttons were not probed in a live browser from this
  environment.
- A real external provider call (no API key exists for this
  project; the provider path is tested through its failure
  handling, not through a live key).
