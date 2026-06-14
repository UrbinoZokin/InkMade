"""Run the Google OAuth consent flow on the user's machine.

Produces an authorized-user token JSON string (with a refresh_token) that
the Pi can consume via GOOGLE_TOKEN_JSON. This mirrors the existing
scripts/google_auth.py flow but returns the token in-memory so the
companion app can upload it straight to the Pi.
"""
from __future__ import annotations

from typing import Optional

from .protocol import GOOGLE_SCOPES


class OAuthError(RuntimeError):
    pass


def run_oauth(credentials_path: str, port: int = 0) -> str:
    """Open the browser consent flow and return the token as a JSON string.

    ``credentials_path`` is the OAuth client-secrets JSON downloaded from the
    Google Cloud Console (Desktop app credentials).
    """
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise OAuthError(
            "Missing dependency google-auth-oauthlib. Reinstall the app."
        ) from exc

    import os

    if not os.path.isfile(credentials_path):
        raise OAuthError(f"Client secrets file not found: {credentials_path}")

    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, GOOGLE_SCOPES)
    creds = flow.run_local_server(port=port, prompt="consent", access_type="offline")

    if not creds.refresh_token:
        raise OAuthError(
            "Google did not return a refresh_token. Revoke prior access for "
            "this app at https://myaccount.google.com/permissions and try again."
        )
    return creds.to_json()


def validate_credentials_file(credentials_path: str) -> Optional[str]:
    """Return None if the client-secrets file looks usable, else an error string."""
    import json
    import os

    if not os.path.isfile(credentials_path):
        return "File does not exist."
    try:
        with open(credentials_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return f"Not readable JSON: {exc}"
    if not ({"installed", "web"} & data.keys()):
        return "Not an OAuth client-secrets file (expected 'installed' or 'web')."
    return None
