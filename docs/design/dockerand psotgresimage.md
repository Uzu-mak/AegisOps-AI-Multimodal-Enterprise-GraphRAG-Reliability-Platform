# Docker Compose and PostgreSQL Foundation Plan

## Scope

This phase establishes the production-style Docker Compose foundation needed to safely run the approved memory-engine migration without yet executing Alembic upgrades. The scope is intentionally limited to PostgreSQL integration for the application; Neo4j and Qdrant are included as service placeholders only and are not used by application logic yet.

## Goals

1. Add Docker Compose services for:
   - api
   - postgres
   - neo4j
   - qdrant
2. Integrate PostgreSQL with the application and keep the app runtime configuration environment-based.
3. Ensure the API waits on PostgreSQL health, not just container startup.
4. Use a single `DATABASE_URL` configuration source for both SQLAlchemy and Alembic.
5. Keep credentials out of source control.
6. Provide local operational commands for starting, inspecting, and stopping the PostgreSQL dependency safely.
7. Do not run Alembic upgrade yet.

---

## Compose service plan

### PostgreSQL service

- Use a stable current PostgreSQL image, such as `postgres:16-alpine`.
- Set:
  - `POSTGRES_DB=aegisops`
  - `POSTGRES_USER=aegisops`
  - `POSTGRES_PASSWORD` from environment
- Persist data with a named Docker volume.
- Expose port `5432` for local inspection.
- Add a `pg_isready` healthcheck.
- Use the Compose network hostname `postgres` so the API resolves it as the database host.

### API service

- Python 3.12 base image.
- Built from an API Dockerfile in the project.
- Reads `DATABASE_URL` from environment.
- Depends on the PostgreSQL service health condition, not just startup state.
- No hardcoded DB credentials in the application code or Dockerfile defaults.
- Does not yet use Neo4j or Qdrant.

### Neo4j service

- Included as a service so the Compose environment mirrors the intended production-like topology.
- Started as a supporting service only.
- Not used by application logic in this phase.

### Qdrant service

- Included as a service for future memory/vector integration.
- Not wired into runtime logic in this phase.

---

## Application configuration strategy

The existing project already follows the correct pattern for a single config source:

- [app/core/config.py](../../app/core/config.py)
- [app/db/session.py](../../app/db/session.py)
- [alembic/env.py](../../alembic/env.py)

The app and Alembic should both resolve the same `DATABASE_URL` from environment variables. No duplicate DB URLs should be hardcoded in code paths.

This keeps runtime configuration and migration configuration consistent and avoids schema drift between local dev and containerized use.

---

## Environment file design

Add a `.env.example` with the following values:

```env
POSTGRES_DB=aegisops
POSTGRES_USER=aegisops
POSTGRES_PASSWORD=change_me
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

DATABASE_URL=postgresql+psycopg://aegisops:change_me@postgres:5432/aegisops
```

The real `.env` file should be gitignored and generated locally from `.env.example`.

This preserves a safe default for local development while preventing credentials from being committed to the repository.

---

## Git ignore requirement

Add `.env` to `.gitignore` so local secrets are not checked into source control.

---

## SQLAlchemy and Alembic use

Both SQLAlchemy and Alembic must resolve the same environment-backed value:

- `DATABASE_URL` is the source of truth.
- No code should contain a separate hardcoded PostgreSQL URL.
- The configured URL must be valid for the container network: `postgres` is the hostname inside Docker Compose, not `localhost`.

---

## PostgreSQL health and dependency safety

The API container must wait until PostgreSQL is marked healthy before continuing. This avoids a race condition where the API starts before PostgreSQL is accepting connections.

### Why this matters

A container can be in a running state while the database is still initializing. A healthy check ensures the dependency is actually ready to accept queries.

The health check should use PostgreSQL's readiness tool:

```bash
pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}
```

The `depends_on` condition for the API should be `service_healthy` for PostgreSQL, not merely `service_started`.

---

## Docker network hostnames

### `postgres` vs `localhost`

Within a Docker Compose network:

- `postgres` is the service name and the correct hostname for other containers to reach the database.
- `localhost` inside a container refers to that same container, not the PostgreSQL container.

Therefore, the API should use `postgres` in `DATABASE_URL` rather than `localhost` when running inside Compose.

---

## Named volume rationale

A named volume is used for PostgreSQL persistence so that database data survives container restarts and can be reused across local dev sessions.

Without a named volume, the database would lose its state whenever the container is recreated.

This is a critical difference between a transient dev database and a reliable persistent local foundation.

---

## Why secrets are environment variables

Secrets and connection settings should be provided through environment variables because:

- they stay out of source control,
- they can vary by environment (local, CI, staging, production),
- they reduce the chance of embedding credentials into code,
- they match the expected 12-factor app configuration pattern.

This is exactly why `.env` and `.env.example` are part of the plan.

---

## What `docker compose down -v` destroys

The command:

```bash
docker compose down -v
```

removes the containers and also deletes the named volumes attached to them.

For PostgreSQL, that means the database data stored in the volume is destroyed as well. This is useful for a full reset, but it is not a safe command for preserving local state.

The non-volume version:

```bash
docker compose down
```

stops and removes the containers without deleting the database volume.

---

## Required operational commands

These commands will be documented for the local PostgreSQL workflow:

```bash
docker compose up -d postgres
docker compose ps
docker compose logs postgres
docker compose exec postgres psql -U aegisops -d aegisops
docker compose down
docker compose down -v
```

---

## Development boundary

This step intentionally does not include:

- Alembic upgrade execution
- Neo4j application integration
- Qdrant application integration
- repositories/services/API implementation beyond the database foundation

The project remains paused at the containerized PostgreSQL foundation layer until the user approves and requests the next implementation step.
