"""Remember who signed in (app_user), at most once a minute per person and process."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

logger = logging.getLogger(__name__)
_last: dict[tuple[str, str], float] = {}
THROTTLE_SECONDS = 60


def remember(principal: Any, session_factory=None) -> None:
    """Upsert the signed-in person. Never fails a request: errors are logged."""
    key = (principal.issuer or "", principal.subject or "")
    now = time.monotonic()
    if not principal.subject or now - _last.get(key, -THROTTLE_SECONDS) < THROTTLE_SECONDS:
        return
    try:
        from app.db.models.user import AppUser

        if session_factory is None:
            from app.db.session import SessionLocal as session_factory  # noqa: N813
        with session_factory() as session:
            user = session.execute(select(AppUser).where(AppUser.issuer == key[0], AppUser.subject == key[1])).scalar_one_or_none()
            if user is None:
                user = AppUser(issuer=key[0], subject=key[1], username=principal.username or key[1])
                session.add(user)
            user.username = principal.username or user.username
            user.display_name = principal.display_name
            user.email = principal.email
            user.tenant_id = principal.tenant_id
            user.roles = list(principal.roles)
            user.last_seen_at = datetime.now(timezone.utc)
            session.commit()
        _last[key] = now
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not record signed-in user: %s", exc)


def list_users(session) -> list[dict[str, Any]]:
    from app.db.models.user import AppUser

    rows = session.execute(select(AppUser).order_by(AppUser.last_seen_at.desc())).scalars()
    return [{"username": u.username, "display_name": u.display_name, "email": u.email, "roles": u.roles,
             "tenant_id": u.tenant_id, "first_seen_at": u.first_seen_at.isoformat(), "last_seen_at": u.last_seen_at.isoformat()}
            for u in rows]
