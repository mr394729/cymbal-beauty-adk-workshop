"""Bind trusted session scope to an authenticated service caller and audience."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    user_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    store_id: str = Field(pattern=r"^S-\d{3,6}$")
    role: str = Field(pattern=r"^(associate|store_manager|district_manager)$")
    namespace: str = Field(pattern=r"^[a-z][a-z0-9]{2,11}$")
    environment: str = Field(pattern=r"^(dev|preprod|prod)$")
    audience: str
    caller: str
    issued_at: int
    expires_at: int

    def state(self) -> dict:
        return {"user:user_id": self.user_id, "user:store_id": self.store_id, "user:role": self.role}


@dataclass(frozen=True)
class Settings:
    audience: str
    scope_key: str = field(repr=False)
    trusted_callers: frozenset[str]
    namespace: str
    environment: str

    def __post_init__(self):
        parsed = urlsplit(self.audience)
        if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"} or parsed.query:
            raise ValueError("CYMBAL_MCP_AUDIENCE must be the HTTPS Cloud Run service origin.")
        if len(self.scope_key.encode()) < 32:
            raise ValueError("CYMBAL_MCP_SCOPE_KEY must contain at least 32 bytes.")
        if not self.trusted_callers or any(not x.endswith(".gserviceaccount.com") for x in self.trusted_callers):
            raise ValueError("CYMBAL_MCP_TRUSTED_CALLERS must list trusted service account emails.")

    @classmethod
    def from_env(cls):
        names = ("CYMBAL_MCP_AUDIENCE", "CYMBAL_MCP_SCOPE_KEY", "CYMBAL_MCP_TRUSTED_CALLERS",
                 "WORKSHOP_NAMESPACE", "STORE_OPS_ENV")
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            raise ValueError("Missing MCP server configuration: " + ", ".join(missing))
        return cls(os.environ[names[0]].rstrip("/"), os.environ[names[1]],
                   frozenset(x.strip() for x in os.environ[names[2]].split(",")),
                   os.environ[names[3]], os.environ[names[4]])


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def sign_scope(scope: Scope, key: str) -> str:
    payload = _encode(scope.model_dump_json().encode())
    signature = _encode(hmac.digest(key.encode(), payload.encode(), hashlib.sha256))
    return payload + "." + signature


def verify_scope(value: str, settings: Settings, caller: str, now: int | None = None) -> Scope:
    """Reject tampering, replay outside a short validity window, and scope mismatch."""
    if len(value) > 4096:
        raise ValueError("Invalid session scope.")
    try:
        payload, signature = value.split(".")
        expected = _encode(hmac.digest(settings.scope_key.encode(), payload.encode(), hashlib.sha256))
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid session signature.")
        scope = Scope.model_validate(json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))))
    except (ValueError, UnicodeError, ValidationError) as error:
        raise ValueError("Invalid session scope.") from error
    now = int(time.time()) if now is None else now
    if (scope.audience != settings.audience or scope.caller != caller
            or scope.namespace != settings.namespace or scope.environment != settings.environment
            or scope.issued_at > now + 15 or scope.expires_at <= now
            or not 0 < scope.expires_at - scope.issued_at <= 180):
        raise ValueError("Expired or mismatched session scope.")
    return scope


class GoogleCallerVerifier:
    """Verify the original signed ID token; Cloud Run can strip Authorization's signature."""
    def __init__(self, request=None):
        if request is not None:
            self.request = request
            return
        import cachecontrol
        import requests
        from google.auth.transport.requests import Request
        self.request = Request(session=cachecontrol.CacheControl(requests.Session()))

    def __call__(self, token: str, audience: str) -> dict:
        from google.oauth2.id_token import verify_oauth2_token
        return verify_oauth2_token(token, self.request, audience=audience)
