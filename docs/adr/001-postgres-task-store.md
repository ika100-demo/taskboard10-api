# ADR-001: Tasks are stored in Postgres through psycopg 3; the app owns its schema

## Status

Accepted (spec 002).

## Context

Spec 001 kept tasks in process memory: a restart loses them, and every replica has its own list. The system plan `001-persistent-tasks-and-web-task-board` gives this service a Postgres database through the gitops `uses: postgres`, which sets `DATABASE_URL` and `PG*`. The service has to start and stay ready while that database is down, answering 503 instead of crash-looping. Two replicas may start at the same moment. The repo has no migration tooling, and the CI test job runs `devbox run test` from a skeleton workflow that platform updates overwrite.

## Decision

- Tasks live in Postgres. The service talks to it with **psycopg 3** (`psycopg[binary]`) and a small **`psycopg_pool.ConnectionPool`**, built and opened lazily on the first task request. Nothing connects at startup.
- The only configuration is `DATABASE_URL`. Without it the store reports itself unavailable (503). It never falls back to `PG*` or libpq defaults.
- **The app owns its schema.** On its first successful connection, each process runs an idempotent `CREATE TABLE IF NOT EXISTS` in one transaction that holds `pg_advisory_xact_lock(<fixed key>)`. The first spec that changes an existing table introduces a migration tool (Alembic, run by the app under the same advisory lock), and the existing DDL becomes its baseline revision.
- Tests that need a database run against a **real Postgres from devbox** (`postgresql@16`). A pytest fixture starts it in a temp dir on a free local port. There is no Docker, no testcontainers and no mocked driver. `devbox run test` therefore works the same on a laptop and in CI, and `ci.yml` stays unchanged.

## Consequences

**Positive:**
- Tasks survive restarts, and every replica sees one list.
- Startup never depends on the database.
- No extra deploy step (a migration job or init container) is needed while the schema is a single additive table.
- Tests run against the real SQL dialect and real connection failures.

**Negative:**
- Schema changes beyond additive DDL need the migration tool, which is not there yet.
- The `postgresql` devbox package and the `db-up`/`db-down` recipes are repo additions to the template's `devbox.json`. Check after each `/platform:update` that the package is still listed.
- The test fixture runs `initdb`, which refuses to run as root. A CI runner must run the tests as a non-root user, as GitHub-hosted runners do.
