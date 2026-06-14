#!/usr/bin/env python3
"""Off-device helper that mints a Google Calendar read-only OAuth token file.

Run this on a machine that has a web browser (your laptop, not the Pi).
It performs the interactive OAuth consent flow and writes a token file
that the Pi can consume via GOOGLE_TOKEN_JSON.

Usage:
    pip install google-auth google-auth-oauthlib
    python scripts/google_auth.py \\
        --credentials /path/to/google_credentials.json \\
        --token /path/to/google_token.json

Then copy the generated token file to the Pi at the path referenced by
GOOGLE_TOKEN_JSON (default: /opt/inkycal/secrets/google_token.json).

The token file embeds a long-lived refresh_token; the Pi refreshes the
short-lived access_token on its own and never opens a browser.
"""
from __future__ import annotations

import argparse
import os
import sys

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--credentials",
        required=True,
        help="Path to OAuth client secrets JSON (downloaded from Google Cloud Console).",
    )
    parser.add_argument(
        "--token",
        required=True,
        help="Destination path for the generated token JSON.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Local port for the OAuth loopback redirect (0 = auto-pick).",
    )
    args = parser.parse_args()

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "Missing dependency. Install with: pip install google-auth google-auth-oauthlib",
            file=sys.stderr,
        )
        return 1

    if not os.path.exists(args.credentials):
        print(f"Credentials file not found: {args.credentials}", file=sys.stderr)
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(args.credentials, SCOPES)
    creds = flow.run_local_server(port=args.port, prompt="consent", access_type="offline")

    parent = os.path.dirname(os.path.abspath(args.token))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(args.token, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    if not creds.refresh_token:
        print(
            "WARNING: token has no refresh_token. The Pi will stop working after ~1 hour.\n"
            "Re-run with prompt=consent and ensure this is the first authorization for the client.",
            file=sys.stderr,
        )
        return 2

    print(f"Wrote token to {args.token}")
    print("Copy this file to the Pi at the path referenced by GOOGLE_TOKEN_JSON.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
