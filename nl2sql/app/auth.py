"""JWT authentication with bcrypt password hashing and YAML user store."""

from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
import jwt
import bcrypt

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_USERS_FILE = _REPO_ROOT / "users.yaml"

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7


def _load_users() -> dict[str, Any]:
    if not _USERS_FILE.exists():
        return {}
    with open(_USERS_FILE, "r") as f:
        data = yaml.safe_load(f) or {}
    return data.get("users", {})


def _save_users(users: dict[str, Any]) -> None:
    _USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_USERS_FILE, "w") as f:
        yaml.dump({"users": users}, f)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def ensure_default_admin() -> None:
    """Create default admin user if no users exist."""
    users = _load_users()
    if users:
        return
    users["admin"] = {
        "password_hash": hash_password("admin"),
        "role": "admin",
    }
    _save_users(users)
    logger.info("Created default admin user (admin/admin)")


def authenticate_user(username: str, password: str) -> dict[str, str] | None:
    users = _load_users()
    user = users.get(username)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    return {"username": username, "role": user.get("role", "viewer")}


def create_access_token(data: dict) -> str:
    payload = {
        **data,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    payload = {
        **data,
        "exp": datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        "type": "refresh",
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str, expected_type: str = "access") -> dict | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != expected_type:
            return None
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
