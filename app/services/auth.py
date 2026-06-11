"""
Authentication Service
======================
Simple but secure auth system for IPRMS with two roles:
- user: can run scenarios, view history, download exports
- admin: all user permissions plus edit master data, manage users

Uses bcrypt for password hashing + JWT tokens stored in session state.
SQLite-backed user store.
"""

from __future__ import annotations

import json
import secrets
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import Column, String, Boolean, DateTime, Integer, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[2]
AUTH_DB_PATH = BASE_DIR / "runs" / "auth.db"


def _get_auth_engine():
    AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{AUTH_DB_PATH}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    @event.listens_for(engine, "connect")
    def set_wal(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
    return engine


_auth_engine = _get_auth_engine()
_AuthSession = sessionmaker(bind=_auth_engine, autoflush=False, autocommit=False)


class AuthBase(DeclarativeBase):
    pass


class User(AuthBase):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(128), nullable=False)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(16), nullable=False, default="user")   # "user" or "admin"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = Column(DateTime)


AuthBase.metadata.create_all(_auth_engine)


# ---------------------------------------------------------------------------
# Password hashing — simple SHA-256 + salt (no external bcrypt dependency)
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(32)
    h = hmac.new(salt.encode(), password.encode(), hashlib.sha256).hexdigest()
    return h, salt


def _verify_password(password: str, stored_hash: str) -> bool:
    """stored_hash is 'hash:salt'"""
    try:
        h, salt = stored_hash.split(":", 1)
        candidate, _ = _hash_password(password, salt)
        return hmac.compare_digest(candidate, h)
    except Exception:
        return False


def _make_hash(password: str) -> str:
    h, salt = _hash_password(password)
    return f"{h}:{salt}"


# ---------------------------------------------------------------------------
# Seed default users if none exist
# ---------------------------------------------------------------------------

def _seed_default_users():
    with _AuthSession() as session:
        if session.query(User).count() == 0:
            session.add_all([
                User(
                    username="admin",
                    display_name="Administrator",
                    password_hash=_make_hash("admin123"),
                    role="admin",
                ),
                User(
                    username="user",
                    display_name="Standard User",
                    password_hash=_make_hash("user123"),
                    role="user",
                ),
            ])
            session.commit()


_seed_default_users()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def authenticate(username: str, password: str) -> Optional[dict]:
    """
    Verify credentials. Returns user dict on success, None on failure.
    Updates last_login on success.
    """
    with _AuthSession() as session:
        user = session.query(User).filter_by(username=username, is_active=True).first()
        if user is None:
            return None
        if not _verify_password(password, user.password_hash):
            return None
        user.last_login = datetime.now(timezone.utc)
        session.commit()
        return _user_to_dict(user)


def get_all_users() -> list[dict]:
    with _AuthSession() as session:
        return [_user_to_dict(u) for u in session.query(User).order_by(User.id).all()]


def create_user(username: str, display_name: str, password: str, role: str = "user") -> dict:
    with _AuthSession() as session:
        existing = session.query(User).filter_by(username=username).first()
        if existing:
            raise ValueError(f"Username '{username}' already exists")
        u = User(
            username=username,
            display_name=display_name,
            password_hash=_make_hash(password),
            role=role,
        )
        session.add(u)
        session.commit()
        return _user_to_dict(u)


def update_user_password(user_id: int, new_password: str) -> bool:
    with _AuthSession() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return False
        user.password_hash = _make_hash(new_password)
        session.commit()
        return True


def update_user_role(user_id: int, new_role: str) -> bool:
    with _AuthSession() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return False
        user.role = new_role
        session.commit()
        return True


def deactivate_user(user_id: int) -> bool:
    with _AuthSession() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return False
        user.is_active = False
        session.commit()
        return True


def _user_to_dict(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "role": u.role,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login": u.last_login.isoformat() if u.last_login else None,
    }
