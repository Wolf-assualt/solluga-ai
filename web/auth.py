"""
web/auth.py — Session cookie authentication for the owner dashboard.
Uses itsdangerous URLSafeTimedSerializer to sign session cookies.
"""

import os
from typing import Optional
from fastapi import Request, HTTPException, status
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from dotenv import load_dotenv

load_dotenv()

_SECRET_KEY = os.getenv("SECRET_KEY", "sollunga-dashboard-secret-fallback")
_COOKIE_NAME = "sollunga_session"
_MAX_AGE_SECONDS = 86400 * 7  # 7 days

_serializer = URLSafeTimedSerializer(_SECRET_KEY)


def get_dashboard_password() -> str:
    """Return dashboard password from environment (default: YuvaNavi123)."""
    return os.getenv("DASHBOARD_PASSWORD", "YuvaNavi123").strip()


def create_session_token(username: str = "owner") -> str:
    """Generate a signed session token."""
    return _serializer.dumps({"user": username})


def verify_session_token(token: str) -> Optional[str]:
    """Verify session token and return user, or None if invalid/expired."""
    try:
        data = _serializer.loads(token, max_age=_MAX_AGE_SECONDS)
        return data.get("user")
    except (BadSignature, SignatureExpired, Exception):
        return None


def get_current_user(request: Request) -> Optional[str]:
    """Extract authenticated user from request cookie, or None."""
    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        return None
    return verify_session_token(token)


def require_auth(request: Request) -> str:
    """Dependency that ensures user is authenticated, otherwise raises 401."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return user
