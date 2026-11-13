"""Password hashing, session tokens and login throttling.

The local login lives behind the functions in this module (and app.core.auth_routes) so that a hosted
identity service with passkeys and two-step verification can replace it later without touching the
rest of the app.
"""

import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.models import AuthSession, LoginAttempt, User, aware, utcnow

_hasher = PasswordHasher()
# Used to spend the same time on unknown emails as on wrong passwords.
_DUMMY_HASH = _hasher.hash("not-a-real-password")

MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if password.strip() == "" or len(set(password)) < 4:
        return "Choose a less repetitive password."
    return None


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def create_session(db: Session, user: User, user_agent: str | None) -> str:
    token = new_token()
    db.add(
        AuthSession(
            token_hash=sha256(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(days=get_settings().session_days),
            user_agent=(user_agent or "")[:300],
        )
    )
    return token


def session_user(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == sha256(token)))
    if row is None:
        return None
    if aware(row.expires_at) <= utcnow():
        db.delete(row)
        db.commit()
        return None
    return db.get(User, row.user_id)


def end_session(db: Session, token: str | None) -> None:
    if not token:
        return
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == sha256(token)))
    if row is not None:
        db.delete(row)


def too_many_failures(db: Session, email: str) -> bool:
    s = get_settings()
    since = utcnow() - timedelta(minutes=s.login_window_minutes)
    failures = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.email == email, LoginAttempt.at >= since, LoginAttempt.success.is_(False))
    )
    return (failures or 0) >= s.login_max_failures


def record_attempt(db: Session, email: str, success: bool) -> None:
    db.add(LoginAttempt(email=email, success=success))
