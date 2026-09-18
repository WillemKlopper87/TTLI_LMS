# How-To Guide (Engineering)

Task-oriented recipes for people working in this codebase. For first-time
environment setup, use [README.md](../README.md#local-development) — this
document assumes the stack already runs locally and answers "how do I do X"
questions that come up once you're building features or fixing bugs.

For the guide aimed at people *using* the deployed product (learners,
corporate administrators, facilitators, partners), see
[USER_GUIDE.md](USER_GUIDE.md). That document has no engineering content and
should not need this one.

## Everyday development

### Run the full local stack

```bash
scripts/dev-up.sh          # starts Postgres, Redis, Garage, Mailpit, ClamAV
cd apps/api && python -m uvicorn src.main:app --reload --port 8010
cd apps/api && python -m arq src.workers.main.WorkerSettings   # second terminal
cd apps/web && npm run dev
```

See [README.md](../README.md#local-ports) for the full port table and the
second-tenant hosts-file entry.

### Run a single test file or test

```bash
cd apps/api
python -m pytest tests/test_licence.py -x
python -m pytest tests/test_licence.py::test_grant_seat_respects_capacity -x
```

### Run the same checks CI runs, before pushing

```bash
scripts/gates.sh
```

Or individually — see [README.md](../README.md#quality-and-ci).

### Add a database migration

1. Change the SQLAlchemy models under `apps/api/src/models/`.
2. Every model must be imported in `apps/api/src/models/__init__.py` — an
   unimported model is invisible to Alembic autogenerate and the schema will
   silently drift.
3. From `apps/api`, generate and hand-review the migration:
   ```bash
   python -m alembic revision --autogenerate -m "short_description"
   ```
4. If the table is tenant-scoped, add the `tenant_id` column and the RLS
   policy in the same migration — see any recent migration under
   `apps/api/alembic/versions/` for the pattern (`CREATE POLICY
   tenant_isolation ON <table> USING (tenant_id = current_setting(...))`).
   A table listed for RLS without a `tenant_id` column fails at migration
   time, not at review time — always run the upgrade against a real database
   before committing.
5. Apply it and confirm it also downgrades cleanly:
   ```bash
   python -m alembic upgrade head
   python -m alembic downgrade -1 && python -m alembic upgrade head
   ```

### Add a new API endpoint

- Put the route in `apps/api/src/routers/<area>.py`, the logic in
  `apps/api/src/services/<area>.py`. Routers stay thin: parse/validate the
  request, call the service, shape the response.
- Every endpoint that reads or writes tenant-scoped data must look up related
  entities scoped by `tenant_id`, not just by primary key —
  `session.get(Model, id)` alone accepts another tenant's row. Use
  `select(Model).where(Model.id == id, Model.tenant_id == tenant_id)`
  instead. This is the single most common review finding in this codebase.
- Gate the endpoint with `principal.require("permission:name")`, or for
  "any of several permissions", `if not principal.permissions & {"a", "b"}:
  raise Forbidden(...)`. There is no `require_one_of` method — it does not
  exist despite looking like it should.
- Regenerate the frontend's typed client after changing the OpenAPI surface:
  ```bash
  cd apps/api && python -m src.export_openapi   # or the project's equivalent
  cd packages/api-client && npm run generate
  ```
  CI fails the build if the generated client drifts from the live schema.

### Work across multiple branches at once

Use `git worktree add <path> <branch>` rather than repeatedly checking out
branches in one working copy — each worktree is an isolated checkout that
shares the same `.git`. Useful when reviewing or fixing several feature
branches in parallel. Remove worktrees you no longer need with
`git worktree remove <path>` to reclaim disk space.

## Troubleshooting

### `ruff`/`mypy` fail with a disk-space error, or Docker won't respond

Check `df -h /c/` (or the equivalent for your OS). Docker Desktop, `npm`'s
`_npx` package cache (`%LOCALAPPDATA%\npm-cache\_npx` on Windows), and
`pip`'s cache are common large, safely-clearable offenders —
`npm cache clean --force`, deleting `_npx` directly, and `pip cache purge`
recover space without touching anything you'd need to rebuild by hand,
short of a re-download next time those tools are used.

### Migration fails with `UndefinedColumn: column "tenant_id" does not exist`

A table was added to a loop that creates RLS policies (`for table in
TENANT_SCOPED: CREATE POLICY ...`) without actually defining a `tenant_id`
column on that table in the same migration. Add the column.

### Mypy says a service function's return type doesn't match

`session.execute(...).scalars().all()` returns `Sequence[...]`, not
`list[...]`. Wrap it: `list(result.scalars().all())`.

## Where things are documented

| Question | Document |
|---|---|
| What does the product do today, and what's still open? | [README.md](../README.md) product-coverage table |
| What's next in priority order? | [docs/BACKLOG.md](BACKLOG.md) |
| Full requirements, personas, decisions | [docs/01_PRD.md](01_PRD.md) |
| Schema, tenancy, retention | [docs/02_DATA_MODEL.md](02_DATA_MODEL.md) |
| REST conventions and endpoint contracts | [docs/03_API_SPEC.md](03_API_SPEC.md) |
| Auth, POPIA, encryption, audit | [docs/04_SECURITY_AND_COMPLIANCE.md](04_SECURITY_AND_COMPLIANCE.md) |
| Runtime topology, backups, recovery, runbooks | [docs/06_OPERATIONS.md](06_OPERATIONS.md) |
| How to use the deployed product (non-engineering) | [docs/USER_GUIDE.md](USER_GUIDE.md) |
