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


def _basic_auth_result(authorization: str | None) -> tuple[bool, str | None]:
    expected = _dashboard_basic_credentials()
    if expected is None:
        return True, None
    if not authorization or not authorization.startswith("Basic "):
        return False, None
    try:
        decoded = base64.b64decode(
            authorization.removeprefix("Basic ").strip(),
            validate=True,
        ).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False, None

    username, separator, password = decoded.partition(":")
    if not separator:
        return False, None
    # compare_digest rejects non-ASCII str inputs. Compare the same UTF-8 bytes
    # accepted by the decoder so a Unicode credential cannot crash middleware.
    username_valid = secrets.compare_digest(
        username.encode("utf-8"), expected[0].encode("utf-8")
    )
    password_valid = secrets.compare_digest(
        password.encode("utf-8"), expected[1].encode("utf-8")
    )
    valid = username_valid and password_valid
    return valid, expected[0] if valid else None


def _basic_auth_is_valid(authorization: str | None) -> bool:
    return _basic_auth_result(authorization)[0]


def _basic_auth_principal(authorization: str | None) -> str | None:
    """Return the configured shared principal only after full validation."""

    return _basic_auth_result(authorization)[1]
