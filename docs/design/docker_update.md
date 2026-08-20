# Docker and PostgreSQL Foundation Update

## Approved modifications

1. The default Phase-1 stack will run only the API and PostgreSQL.
2. Neo4j and Qdrant will not be started in the default workflow.
3. If they are needed later, they should be placed behind Docker Compose profiles so they do not run unless explicitly requested.
4. PostgreSQL credentials and connection details must not be duplicated in both separate environment variables and a manually hardcoded `DATABASE_URL`.
5. The application and Alembic must use one clear configuration strategy: a single environment-backed `DATABASE_URL` source, with the API and migration code deriving from it consistently.

---

## Configuration strategy

The implementation should follow a single source of truth:

- `.env` defines the base database variables.
- `DATABASE_URL` is built once from those values.
- The API reads `DATABASE_URL` from the environment.
- Alembic reads the same `DATABASE_URL` from the environment.
- No separate hardcoded URL is repeated in the app or migration code.

This prevents password duplication and keeps the runtime and migration configuration aligned.

---

## Why this matters

If the PostgreSQL password is duplicated in both component environment variables and a manually written `DATABASE_URL`, the configuration can drift. One place may be updated while the other remains stale, which creates a subtle but serious operational issue.

The better pattern is:

- define the underlying values once,
- construct the URL from those values,
- expose the final URL to both app and Alembic as the same environment source.

---

## Default Phase-1 stack

The default Compose workflow should contain only:

- `api`
- `postgres`

This keeps the initial development environment lightweight and aligned with the approved Phase-1 scope.

---

## Future optional services

If Neo4j or Qdrant are needed later, they should be added as optional Compose services behind profiles such as:

```yaml
profiles:
  - graph
  - vector
```

This ensures they are out of the default development path until the project explicitly requires them.

---

## Implementation principle

The PostgreSQL foundation should be safe and minimal:

- API and PostgreSQL run in the default stack
- PostgreSQL is persistent and health-checked
- credentials remain environment-driven
- Alembic does not run yet
- no unused services are started by default

This preserves the approved Phase-1 boundary while preparing the project for the next database migration step.
