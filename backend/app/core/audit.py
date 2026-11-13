import uuid

from sqlalchemy.orm import Session

from app.core.models import AuditEvent


def log(
    db: Session,
    action: str,
    *,
    user_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    **detail,
) -> None:
    """Record an action in the activity log. Never put passwords, tokens or invite codes in detail."""
    db.add(AuditEvent(action=action, user_id=user_id, group_id=group_id, detail=detail or None))
