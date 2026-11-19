# AI Engineering Agent — Foundation Contract (Stage 1)

**Status:** Contract only. No agent code, model call, or API key
exists in Stage 1. This document fixes the rules the Stage 2 agent
must follow, so later work does not have to re-decide them.

## 1. What the agent will be

A tool-using agent that helps a user design, model, simulate,
analyse, test and improve an engineering system — by calling the
same backend endpoints a human would use (`backend/api-spec.md`),
never by inventing results in chat.

## 2. Tools (Stage 2)

| Tool | Access |
|---|---|
| `materials.search` / `materials.get` | Read-only |
| `components.search` / `components.get` | Read-only |
| `projects.create` / `projects.get` / `projects.list` | Read + write (user's own projects) |
| `simulations.create` (queues a real solver run) | Write — queues only |
| `simulations.get` (reads a real solver's output) | Read-only |

The agent has **no tool** that writes a simulation result directly.
Results may only appear in `simulations.results` when written by
the solver service itself.

## 3. Hard rules

1. **Never present a computed number as a simulation result unless
   it came from `simulations.get` for a `completed` run** with a
   recorded `solver` + `solver_version`.
2. **Uncertainty must be stated.** If inputs are incomplete, the
   agent asks for them or states the assumption — it does not silently
   fill in a load, material, or boundary condition.
3. **Every run is logged** in `agent_runs` (see `db/schema.sql`):
   model, prompt hash, tools called, project id, timestamp.
   No log entry = the run did not happen.
4. **No paid/proprietary API is required.** The agent must work with
   the local backend + open-source solvers. A model API may be
   plugged in later as an *optional* provider, never as the only path.
5. **Human approval** is required before the agent queues a
   long/expensive solver run (threshold to be set in Stage 2).

## 4. Stage 2 first steps (not started)

1. Implement one real solver end-to-end (smallest: beam bending
   with `scipy`) behind `POST /api/v1/simulate/beam`.
2. Wire `simulations` table + status polling.
3. Build the agent as a thin wrapper over those same endpoints.
4. Add `agent_runs` logging and a visible run history page.
