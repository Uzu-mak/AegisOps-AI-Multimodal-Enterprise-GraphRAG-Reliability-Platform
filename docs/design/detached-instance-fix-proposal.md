# DetachedInstanceError fix proposal for service-returned MemoryRecord objects

## Problem

The service methods commit within a session and then return a SQLAlchemy `MemoryRecord` instance that was loaded in that same scoped session. After the session closes, the ORM instance is detached. With default expiration semantics, attributes like `title`, `status`, `content`, and `memory_metadata` may be expired and then reloaded lazily. In practice, the future API serializer or tests may access those fields after the session has ended, which triggers `DetachedInstanceError`.

The root cause is not invalid business logic; it is the transaction/session lifecycle boundary. The service owns the transaction and commits, but the returned object is still tied to a session that is closed immediately after the return path.

## Constraints

- Do not weaken transaction ownership.
- Do not remove the service-layer commit.
- Do not move commit responsibility into the repository.
- Do not modify tests to hide the issue.
- Do not broaden scope beyond the Phase 1 memory service contract.

## Preferred fix: explicit materialization before return

The safest fix is to keep the service as the transaction owner, then materialize the object state before the session closes and return a detached-but-stable value object / ORM instance whose required attributes are already loaded.

### Recommended pattern

```python
with self.session_factory() as session:
    memory = self.repository.get_by_id(session, memory_id)
    if memory is None:
        raise MemoryNotFoundError(f"Memory {memory_id} not found.")

    session.flush()
    session.refresh(memory)
    session.expunge(memory)
    return memory
```

### Why this works

- The service still controls the transaction.
- The database row is fully loaded and refreshed before returning.
- The object is detached before external consumers touch it.
- Required fields remain readable after the session closes because they are no longer pending expiration.

This is the most explicit and predictable option when a service must return a persisted ORM entity while preserving a strict session boundary.

## Alternative fix: `expire_on_commit=False`

A simpler alternative is to configure the session factory with:

```python
sessionmaker(..., expire_on_commit=False)
```

This keeps loaded attributes available after commit even though the session is closed. It is often the least invasive fix for service methods returning ORM instances after a commit.

### Tradeoff

This is convenient and keeps the returned object usable for serialization, but it works by preserving attribute state across commit rather than by making the returned object explicitly detached and materialized. In other words, it avoids the error with less ceremony, but it is a broader session policy decision that affects all committed ORM instances.

For a strict Phase 1 service contract, the explicit refresh/materialization strategy is clearer because it states: "we are returning a fully materialized record after the transaction, and the session boundary is respected." The `expire_on_commit=False` option is easier to implement but is a more global policy that may hide future lifecycle surprises for other ORM-returning service methods.

## Recommended decision

Use the explicit materialization pattern at the service return boundary.

This preserves these guarantees:

- transaction ownership stays in the service layer
- commit semantics stay unchanged
- returned records are safe for downstream serialization
- session closure is respected
- future API code can read required fields without detached-state surprises

## Implementation guidance

For each service method that returns a `MemoryRecord` after commit, ensure the method does the following in order:

1. open a session
2. load or update the record within the transaction
3. validate and persist as required
4. commit
5. refresh or otherwise materialize the record before close
6. return the record as a detached but stable object

Avoid returning raw in-session entities that have not been explicitly made safe for outside access.

## Scope note

This fix is intentionally limited to the service return lifecycle and does not expand into API schemas, repository logic, or unrelated components.
