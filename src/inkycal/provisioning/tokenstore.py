"""Persist the Google OAuth token delivered by the companion app.

The display program reads ``GOOGLE_TOKEN_JSON`` (see ``calendar_google.py``).
This module validates an uploaded token blob, writes it atomically to that
path and nudges the display service to refresh.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

DEFAULT_TOKEN_PATH = "/opt/inkycal/secrets/google_token.json"

# Fields the google-auth library writes for an authorized user token.
_REQUIRED_TOKEN_FIELDS = {"refresh_token", "client_id", "client_secret"}


def token_path() -> str:
    return os.environ.get("GOOGLE_TOKEN_JSON", DEFAULT_TOKEN_PATH)


def token_present() -> bool:
    path = token_path()
    try:
        return Path(path).is_file() and Path(path).stat().st_size > 0
    except OSError:
        return False


def validate_token(raw: bytes | str) -> dict:
    """Parse and sanity-check an uploaded token. Raises ValueError if bad."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"Token is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Token JSON must be an object")

    missing = _REQUIRED_TOKEN_FIELDS - data.keys()
    if missing:
        raise ValueError(
            "Token is missing required field(s): " + ", ".join(sorted(missing))
        )
    if not data.get("refresh_token"):
        raise ValueError(
            "Token has no refresh_token; re-run Google sign-in with consent."
        )
    return data


def save_token(raw: bytes | str, path: Optional[str] = None) -> str:
    """Validate then atomically write the token. Returns the path written."""
    data = validate_token(raw)
    dest = path or token_path()
    parent = os.path.dirname(dest) or "."
    os.makedirs(parent, exist_ok=True)

    # Atomic write: temp file in the same dir, then rename.
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".google_token.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass

    # The agent often runs as root while the display service runs as the
    # install user (owner of the secrets dir). Match the file's ownership to
    # that directory so the display process can read the token it was given.
    try:
        dir_stat = os.stat(parent)
        if os.geteuid() == 0 and dir_stat.st_uid != 0:
            os.chown(dest, dir_stat.st_uid, dir_stat.st_gid)
    except (OSError, AttributeError):
        pass
    return dest


def refresh_display() -> bool:
    """Best-effort: kick the display service so the new token is used now.

    Uses ``--no-block`` because inkycal.service is Type=oneshot with a long
    ExecStartPre; without it ``systemctl start`` would block until the render
    finishes (45s+) and hang the HTTP request that triggered this. Never
    raises — a failed start just means the next scheduled poll picks it up.
    """
    for cmd in (
        ["systemctl", "start", "--no-block", "inkycal.service"],
        ["sudo", "systemctl", "start", "--no-block", "inkycal.service"],
    ):
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10, check=False
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            return True
    return False
