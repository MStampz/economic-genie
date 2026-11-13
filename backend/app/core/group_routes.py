import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit
from app.core.deps import GroupAccess, current_user, group_access, owner_access
from app.core.models import AuditEvent, Group, Invite, Membership, User, aware, utcnow
from app.core.schemas import AuditOut, GroupIn, GroupOut, InviteOut, JoinIn, MemberOut, RoleIn
from app.core.security import sha256
from app.db import get_db

router = APIRouter(prefix="/api/groups", tags=["groups"])

# Invite codes avoid letters and digits that are easy to confuse (0/O, 1/I/L).
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _new_code() -> str:
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def _normalise_code(code: str) -> str:
    c = "".join(ch for ch in code.upper() if ch.isalnum())
    return f"{c[:5]}-{c[5:]}"


@router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(body: GroupIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    group = Group(**body.model_dump())
    db.add(group)
    db.flush()
    db.add(Membership(user_id=user.id, group_id=group.id, role="owner"))
    audit.log(db, "group.created", user_id=user.id, group_id=group.id)
    db.commit()
    return group


@router.get("/{group_id}", response_model=GroupOut)
def get_group(access: GroupAccess = Depends(group_access)):
    return access.group


@router.patch("/{group_id}", response_model=GroupOut)
def update_group(body: GroupIn, access: GroupAccess = Depends(owner_access), db: Session = Depends(get_db)):
    for k, v in body.model_dump().items():
        setattr(access.group, k, v)
    audit.log(db, "group.updated", user_id=access.user.id, group_id=access.group.id)
    db.commit()
    return access.group


@router.get("/{group_id}/members", response_model=list[MemberOut])
def members(access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.group_id == access.group.id)
        .order_by(Membership.joined_at)
    ).all()
    return [
        MemberOut(user_id=u.id, display_name=u.display_name, email=u.email, role=m.role, joined_at=m.joined_at)
        for m, u in rows
    ]


@router.post("/{group_id}/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
def create_invite(access: GroupAccess = Depends(owner_access), db: Session = Depends(get_db)):
    """Creates a one-time code. The code is shown once; only its hash is stored."""
    code = _new_code()
    invite = Invite(
        group_id=access.group.id,
        code_hash=sha256(code),
        created_by=access.user.id,
        expires_at=utcnow() + timedelta(days=get_settings().invite_valid_days),
    )
    db.add(invite)
    audit.log(db, "invite.created", user_id=access.user.id, group_id=access.group.id)
    db.commit()
    return InviteOut(code=code, expires_at=invite.expires_at)


@router.post("/join", response_model=GroupOut)
def join(body: JoinIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    invite = db.scalar(select(Invite).where(Invite.code_hash == sha256(_normalise_code(body.code))))
    now = utcnow()
    if invite is None or invite.used_at or invite.revoked_at or aware(invite.expires_at) <= now:
        audit.log(db, "invite.rejected", user_id=user.id)
        db.commit()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invite code is not valid. Ask for a new one.")
    exists = db.scalar(select(Membership).where(Membership.group_id == invite.group_id, Membership.user_id == user.id))
    if exists is None:
        db.add(Membership(user_id=user.id, group_id=invite.group_id, role=invite.role))
    invite.used_by, invite.used_at = user.id, now
    audit.log(db, "group.joined", user_id=user.id, group_id=invite.group_id)
    db.commit()
    return db.get(Group, invite.group_id)


@router.patch("/{group_id}/members/{user_id}", response_model=MemberOut)
def change_role(user_id: str, body: RoleIn, access: GroupAccess = Depends(owner_access), db: Session = Depends(get_db)):
    m = _membership(db, access, user_id)
    if m.role == "owner" and body.role != "owner":
        _ensure_another_owner(db, access, m)
    m.role = body.role
    audit.log(
        db,
        "member.role_changed",
        user_id=access.user.id,
        group_id=access.group.id,
        member=str(m.user_id),
        role=body.role,
    )
    db.commit()
    u = db.get(User, m.user_id)
    return MemberOut(user_id=u.id, display_name=u.display_name, email=u.email, role=m.role, joined_at=m.joined_at)


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(user_id: str, access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    """Owners can remove anyone; any member can remove themselves (leave the group)."""
    m = _membership(db, access, user_id)
    if m.user_id != access.user.id and not access.is_owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the group's owners can remove members.")
    if m.role == "owner":
        _ensure_another_owner(db, access, m)
    db.delete(m)
    audit.log(db, "member.removed", user_id=access.user.id, group_id=access.group.id, member=str(m.user_id))
    db.commit()


@router.get("/{group_id}/activity", response_model=list[AuditOut])
def activity(access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    return db.scalars(
        select(AuditEvent).where(AuditEvent.group_id == access.group.id).order_by(AuditEvent.at.desc()).limit(200)
    ).all()


def _membership(db: Session, access: GroupAccess, user_id: str) -> Membership:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found.") from None
    m = db.scalar(select(Membership).where(Membership.group_id == access.group.id, Membership.user_id == uid))
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found.")
    return m


def _ensure_another_owner(db: Session, access: GroupAccess, m: Membership) -> None:
    owners = db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.group_id == access.group.id, Membership.role == "owner")
    )
    if owners <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A group needs at least one owner. Make someone else owner first."
        )
