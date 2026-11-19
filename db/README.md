# Database — Stage 1

Prepared architecture only. No database is running in Stage 1.

- `schema.sql` — PostgreSQL/SQLite-compatible schema for materials,
  components, projects, simulations and agent_runs.
- Seed data for Stage 2 is the same data as `data/materials.json`
  and `data/components.json` (typical published values — verify
  against datasheets before design use).

Apply (Stage 2): `psql <db> -f schema.sql`
