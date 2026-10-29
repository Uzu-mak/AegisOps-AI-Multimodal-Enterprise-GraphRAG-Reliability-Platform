from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.services.exceptions import (
    AegisOpsError,
    InvalidLifecycleTransitionError,
    InvalidMemoryDataError,
    MemoryConflictError,
    MemoryNotFoundError,
)


def register_exception_handlers(app) -> None:
    from sqlalchemy.exc import IntegrityError
    @app.exception_handler(IntegrityError)
    async def integrity_conflict(request: Request, exc):
        return JSONResponse(status_code=409, content={"detail": "Concurrent or duplicate record change; refresh and retry"})

    @app.exception_handler(AegisOpsError)
    async def aegisops_exception_handler(request: Request, exc: AegisOpsError):
        if isinstance(exc, MemoryNotFoundError):
            status_code = 404
        elif isinstance(exc, (InvalidMemoryDataError, InvalidLifecycleTransitionError, MemoryConflictError)):
            status_code = 409 if isinstance(exc, (InvalidLifecycleTransitionError, MemoryConflictError)) else 422
        else:
            status_code = 400
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})
