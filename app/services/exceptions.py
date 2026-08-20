from __future__ import annotations


class AegisOpsError(Exception):
    """Base class for domain-level service errors."""


class MemoryNotFoundError(AegisOpsError):
    """Raised when a requested memory does not exist."""


class InvalidMemoryDataError(AegisOpsError):
    """Raised when required memory data is missing or invalid."""


class InvalidLifecycleTransitionError(AegisOpsError):
    """Raised when a memory lifecycle transition is forbidden."""


class MemoryConflictError(AegisOpsError):
    """Raised when a transactional or concurrency conflict is detected."""
