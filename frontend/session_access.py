"""Signed browser identities, isolated by persona at the ADK session boundary."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from fastapi import HTTPException, Request, Response

COOKIE = "cymbal_browser"
_LOCAL_KEY = secrets.token_bytes(32)
_IDENTITY = re.compile(r"^[a-f0-9]{32}$")
PERSONAS = frozenset({"manager", "associate"})


def key(password: str) -> bytes:
    return hashlib.sha256(f"cymbal-browser:{password}".encode()).digest() if password else _LOCAL_KEY


def signature(principal: str, password: str) -> str:
    return hmac.new(key(password), principal.encode(), hashlib.sha256).hexdigest()


def principal(request: Request, password: str) -> str:
    owner, _, signed = request.cookies.get(COOKIE, "").partition(".")
    if not _IDENTITY.fullmatch(owner) or not hmac.compare_digest(signed, signature(owner, password)):
        raise HTTPException(401, "Refresh and sign in to continue.")
    return owner


def ensure_browser(request: Request, response: Response, password: str, *, secure: bool) -> str:
    try:
        owner = principal(request, password)
    except HTTPException:
        owner = secrets.token_hex(16)
        response.set_cookie(COOKIE, f"{owner}.{signature(owner, password)}", httponly=True,
                            samesite="lax", secure=secure, max_age=30 * 86400)
    return owner


def runtime_user(request: Request, password: str, persona: str) -> str:
    if persona not in PERSONAS:
        raise HTTPException(400, "Choose manager or associate.")
    # ADK user: state and memory span sessions, so isolate personas by user ID.
    return f"browser-{principal(request, password)}-{persona}"


def public_state(state: dict) -> dict:
    return {k: v for k, v in state.items() if not k.startswith("_")}


def as_dict(value):
    return value.model_dump(mode="json", exclude_none=True) if hasattr(value, "model_dump") else value
