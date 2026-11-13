"""Request dependencies: who is signed in, and which group they may act in."""

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.models import Group, Membership, User
from app.core.security import session_user
from app.db import get_db

CLIENT_HEADER = "X-Genie-Client"


def require_client_header(request: Request) -> None:
    """Blocks cross-site form posts: browsers cannot add custom headers to them.

    Applied to every request that changes data. Together with SameSite=Lax cookies this is the
    app's protection against cross-site request forgery.
    """
    if request.method not in ("GET", "HEAD", "OPTIONS") and not request.headers.get(CLIENT_HEADER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing client header.")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = session_user(db, request.cookies.get(get_settings().session_cookie_name))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    return user


@dataclass
class GroupAccess:
    group: Group
    membership: Membership
    user: User

    @property
    def is_owner(self) -> bool:
        return self.membership.role == "owner"


def group_access(group_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> GroupAccess:
    """Every group-scoped route uses this. A user who is not a member gets 404, so ids don't leak."""
    membership = db.scalar(select(Membership).where(Membership.group_id == group_id, Membership.user_id == user.id))
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    return GroupAccess(group=db.get(Group, group_id), membership=membership, user=user)


def owner_access(access: GroupAccess = Depends(group_access)) -> GroupAccess:
    if not access.is_owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the group's owners can do this.")
    return access
