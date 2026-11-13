from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit
from app.core.deps import current_user
from app.core.models import Group, Membership, User
from app.core.schemas import LoginIn, MembershipOut, MeOut, RegisterIn, UserOut
from app.core.security import (
    create_session,
    end_session,
    hash_password,
    password_problem,
    record_attempt,
    too_many_failures,
    verify_password,
)
from app.db import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        s.session_cookie_name,
        token,
        max_age=s.session_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/",
    )


def _me(db: Session, user: User) -> MeOut:
    rows = db.execute(
        select(Membership, Group).join(Group, Group.id == Membership.group_id).where(Membership.user_id == user.id)
    ).all()
    return MeOut(
        user=UserOut.model_validate(user),
        groups=[MembershipOut(group_id=g.id, group_name=g.name, role=m.role) for m, g in rows],
    )


@router.post("/register", response_model=MeOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
    user = User(email=body.email, display_name=body.display_name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.") from None
    token = create_session(db, user, request.headers.get("user-agent"))
    audit.log(db, "user.registered", user_id=user.id)
    db.commit()
    _set_cookie(response, token)
    return _me(db, user)


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if too_many_failures(db, body.email):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts. Wait 15 minutes and try again."
        )
    user = db.scalar(select(User).where(User.email == body.email))
    ok = verify_password(user.password_hash if user else None, body.password)
    record_attempt(db, body.email, ok)
    if not ok:
        audit.log(db, "auth.login_failed", user_id=user.id if user else None)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect.")
    token = create_session(db, user, request.headers.get("user-agent"))
    audit.log(db, "auth.login", user_id=user.id)
    db.commit()
    _set_cookie(response, token)
    return _me(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    end_session(db, request.cookies.get(s.session_cookie_name))
    db.commit()
    response.delete_cookie(s.session_cookie_name, path="/")


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _me(db, user)
