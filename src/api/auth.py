"""Bearer auth dependency. Every route except /health requires it."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from config.settings import get_settings


async def require_bearer_token(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not settings.api_bearer_token:
        # Fail closed: an unconfigured token means nothing can authenticate,
        # not "auth is disabled". Misconfiguration should be loud.
        raise HTTPException(status_code=503, detail="API_BEARER_TOKEN is not configured")

    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")

    token = authorization.removeprefix("Bearer ")
    # Constant-time compare - a timing side-channel on token comparison is
    # a real (if narrow) attack surface for a bearer secret.
    if not hmac.compare_digest(token, settings.api_bearer_token):
        raise HTTPException(status_code=401, detail="invalid bearer token")
