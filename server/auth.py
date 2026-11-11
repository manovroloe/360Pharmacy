from __future__ import annotations

from typing import Any, Iterable
from fastapi import Header, HTTPException

from database import DatabaseError, db
from infrastructure.supabase_auth import auth_gateway, AuthServiceError


def _token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Please log in first.")
    return authorization.split(" ", 1)[1].strip()


def profile_for_user(user_id: str) -> dict[str, Any]:
    rows = db.select("profiles", {"select": "*", "id": f"eq.{user_id}", "limit": 1})
    if not rows:
        raise HTTPException(status_code=403, detail="Your user profile is not available.")
    profile = rows[0]
    if not profile.get("is_active", True):
        raise HTTPException(status_code=403, detail="This account is disabled.")
    return profile


def current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    try:
        token = _token(authorization)
        auth_user = auth_gateway.get_user(token)
        profile = profile_for_user(auth_user["id"])
        return {"token": token, "auth": auth_user, "profile": profile}
    except HTTPException:
        raise
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def require_roles(user: dict[str, Any], roles: Iterable[str]) -> dict[str, Any]:
    allowed = set(roles)
    role = user["profile"].get("role")
    if role not in allowed:
        raise HTTPException(status_code=403, detail=f"This action requires: {', '.join(sorted(allowed))}.")
    return user
