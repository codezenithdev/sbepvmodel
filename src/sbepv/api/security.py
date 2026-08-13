"""HTTP Basic authentication for the shared deployment.

Credentials come from the environment; when they are absent the dashboard is
unprotected, which is the intended local-development behaviour. Comparisons use
``secrets.compare_digest`` so a wrong password costs the same time as a wrong
username.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import secrets

from fastapi.responses import JSONResponse

from sbepv.api import config

logger = logging.getLogger(__name__)


def _dashboard_basic_credentials() -> tuple[str, str] | None:
    username = os.getenv("DASHBOARD_BASIC_USER", "").strip()
    password = os.getenv("DASHBOARD_BASIC_PASSWORD", "")
    if bool(username) != bool(password):
        raise RuntimeError(
            "DASHBOARD_BASIC_USER and DASHBOARD_BASIC_PASSWORD must be configured together"
        )
    if not username:
        return None
    return username, password


def _auth_required_response() -> JSONResponse:
    return JSONResponse(
        {"detail": "Authentication required."},
        status_code=401,
        headers={"WWW-Authenticate": f'Basic realm="{config.AUTH_REALM}"'},
    )


def _basic_auth_is_valid(authorization: str | None) -> bool:
    expected = _dashboard_basic_credentials()
    if expected is None:
        return True
    if not authorization or not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(
            authorization.removeprefix("Basic ").strip(),
            validate=True,
        ).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False

    username, separator, password = decoded.partition(":")
    if not separator:
        return False
    return secrets.compare_digest(username, expected[0]) and secrets.compare_digest(
        password, expected[1]
    )
