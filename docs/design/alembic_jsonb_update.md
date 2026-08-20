# Alembic JSONB Alignment Update

## Summary

The initial Alembic migration was updated to make the `metadata` column explicitly use PostgreSQL `JSONB` instead of generic `sa.JSON()` so it matches the SQLAlchemy model definition in [app/db/models/memory.py](../../app/db/models/memory.py).

## Why this correction was necessary

The model defines:

```python
from sqlalchemy.dialects.postgresql import JSONB

metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
```

The migration originally declared:

```python
sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb"))
```

This was inconsistent because:

- the ORM model is PostgreSQL-specific JSONB
- the migration was using a generic JSON type while also assigning a PostgreSQL `jsonb` default
- the GIN index on `metadata` was explicitly using `jsonb_path_ops`, which only makes sense for PostgreSQL JSONB

## Corrected migration behavior

The migration now uses:

```python
sa.Column(
    "metadata",
    postgresql.JSONB(astext_type=sa.Text()),
    nullable=False,
    server_default=sa.text("'{}'::jsonb"),
)
```

This makes the migration explicitly PostgreSQL-compatible and aligned with the model and the intended canonical storage type.

## Result

The model and migration now agree on the database representation for `metadata`:

- SQLAlchemy model: `JSONB`
- Alembic migration: `postgresql.JSONB`
- Postgres storage: JSONB
- index: `jsonb_path_ops` GIN index remains valid for JSONB

No schema migration was applied; this was a design-only correction to keep the generated migration consistent before the next implementation step.
