from __future__ import annotations

from dataclasses import dataclass
import os
from threading import Lock
import time
from typing import Annotated

from fastapi import Depends, Header, HTTPException
import requests

from app.config import get_settings


@dataclass(slots=True)
class AuthenticatedUser:
    user_id: str
    email: str | None
    raw: dict[str, object]


_AUTH_CACHE: dict[str, tuple[float, AuthenticatedUser]] = {}
_AUTH_CACHE_LOCK = Lock()


def _extract_bearer_token(authorization: str | None) -> str:
    value = str(authorization or "").strip()
    if not value:
        raise HTTPException(status_code=401, detail="Authorization header required")
    parts = value.split(" ", 1)
    if len(parts) != 2 or parts[0].strip().lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = parts[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token required")
    return token


def _fetch_supabase_user(token: str) -> AuthenticatedUser:
    settings = get_settings()
    supabase_url = str(settings.supabase_url or "").strip().rstrip("/")
    supabase_anon_key = str(settings.supabase_anon_key or "").strip()
    if not supabase_url:
        supabase_url = str(
            os.getenv("NEXT_PUBLIC_SUPABASE_URL")
            or os.getenv("SUPABASE_PUBLIC_URL")
            or ""
        ).strip().rstrip("/")
    if not supabase_anon_key:
        supabase_anon_key = str(
            os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
            or os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
            or os.getenv("SUPABASE_PUBLISHABLE_KEY")
            or ""
        ).strip()
    if not supabase_url or not supabase_anon_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "Supabase auth is not configured on backend "
                "(set SUPABASE_URL + SUPABASE_ANON_KEY, or NEXT_PUBLIC_SUPABASE_URL + "
                "NEXT_PUBLIC_SUPABASE_ANON_KEY, or SUPABASE_PUBLISHABLE_KEY / "
                "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY)."
            ),
        )

    try:
        response = requests.get(
            f"{supabase_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": supabase_anon_key,
            },
            timeout=max(1.0, float(settings.supabase_auth_timeout_seconds)),
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Auth provider unreachable: {exc}") from exc

    if response.status_code in {401, 403}:
        raise HTTPException(status_code=401, detail="Invalid or expired auth token")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Auth provider error ({response.status_code})")

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Auth provider returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Auth provider returned unexpected response")

    user_id = str(payload.get("id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid auth token payload")
    email_raw = payload.get("email")
    email = str(email_raw).strip() if isinstance(email_raw, str) and email_raw.strip() else None
    return AuthenticatedUser(user_id=user_id, email=email, raw=payload)


def get_authenticated_user(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> AuthenticatedUser:
    token = _extract_bearer_token(authorization)
    settings = get_settings()
    now = time.time()
    with _AUTH_CACHE_LOCK:
        cached = _AUTH_CACHE.get(token)
        if cached and cached[0] > now:
            return cached[1]

    user = _fetch_supabase_user(token)
    ttl_seconds = max(0, int(settings.supabase_auth_cache_ttl_seconds))
    if ttl_seconds > 0:
        with _AUTH_CACHE_LOCK:
            _AUTH_CACHE[token] = (now + ttl_seconds, user)
            # Keep cache bounded.
            if len(_AUTH_CACHE) > 512:
                oldest_tokens = sorted(_AUTH_CACHE.items(), key=lambda kv: kv[1][0])[:128]
                for key, _ in oldest_tokens:
                    _AUTH_CACHE.pop(key, None)
    return user


def get_authenticated_user_id(
    auth_user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> str:
    return auth_user.user_id
