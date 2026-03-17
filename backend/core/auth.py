from __future__ import annotations

import secrets
import time
from typing import Any

import jwt
from fastapi import HTTPException, Request, Response
from starlette.websockets import WebSocket


TOKEN_COOKIE = "raspwatch_token"
_FALLBACK_SECRET: str | None = None


def _get_secret(settings: dict[str, Any]) -> str:
    secret = (settings.get("auth_jwt_secret") or "").strip()
    if secret:
        return secret
    global _FALLBACK_SECRET
    if _FALLBACK_SECRET is None:
        _FALLBACK_SECRET = secrets.token_urlsafe(32)
    return _FALLBACK_SECRET


def create_access_token(settings: dict[str, Any], subject: str = "user") -> str:
    now = int(time.time())
    exp_min = settings.get("auth_jwt_exp_minutes", 720)
    try:
        exp_min = int(exp_min)
    except (TypeError, ValueError):
        exp_min = 720
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + max(5, exp_min) * 60,
    }
    return jwt.encode(payload, _get_secret(settings), algorithm="HS256")


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip() or None
    token = request.cookies.get(TOKEN_COOKIE)
    if token:
        return token
    q = request.query_params.get("token")
    if q:
        return q
    return None


def _extract_ws_token(ws: WebSocket) -> str | None:
    q = ws.query_params.get("token")
    if q:
        return q
    token = ws.cookies.get(TOKEN_COOKIE)
    if token:
        return token
    # Some clients may set Authorization header during WS handshake
    auth = ws.headers.get("authorization") or ws.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip() or None
    return None


def require_auth_if_enabled(request: Request, settings: dict[str, Any]) -> None:
    if not settings.get("auth_enabled"):
        return
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        jwt.decode(token, _get_secret(settings), algorithms=["HS256"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_ws_auth_if_enabled(ws: WebSocket, settings: dict[str, Any]) -> None:
    if not settings.get("auth_enabled"):
        return
    token = _extract_ws_token(ws)
    if not token:
        raise HTTPException(status_code=4401, detail="Missing token")
    try:
        jwt.decode(token, _get_secret(settings), algorithms=["HS256"])
    except Exception:
        raise HTTPException(status_code=4401, detail="Invalid token")


def set_token_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        TOKEN_COOKIE,
        token,
        httponly=True,
        secure=False,  # can be set true behind https
        samesite="lax",
        max_age=7 * 24 * 3600,
        path="/",
    )

