from __future__ import annotations

import os
from functools import lru_cache
from typing import Final


class Settings:
    PROJECT_NAME: Final[str] = "AegisOps"
    POSTGRES_DB: Final[str | None] = os.getenv("POSTGRES_DB")
    POSTGRES_USER: Final[str | None] = os.getenv("POSTGRES_USER")
    POSTGRES_PASSWORD: Final[str | None] = os.getenv("POSTGRES_PASSWORD")
    POSTGRES_HOST: Final[str | None] = os.getenv("POSTGRES_HOST")
    POSTGRES_PORT: Final[str | None] = os.getenv("POSTGRES_PORT")
    DATABASE_URL: Final[str] = os.environ.get("DATABASE_URL")

    if DATABASE_URL is None:
        raise ValueError(
            "DATABASE_URL environment variable is required. Set it in your shell or .env before starting AegisOps."
        )

    # Qdrant configuration
    QDRANT_URL: Final[str | None] = os.getenv("QDRANT_URL", "http://qdrant:6333")
    QDRANT_COLLECTION_NAME: Final[str] = os.getenv("QDRANT_COLLECTION_NAME", "memories")


@lru_cache
def get_settings() -> Settings:
    return Settings()
