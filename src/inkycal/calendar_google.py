from __future__ import annotations
from datetime import datetime
from typing import List
from zoneinfo import ZoneInfo
import ipaddress
import os

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .models import Event

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

def _is_private_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_private
    except ValueError:
        return False


def _get_creds(credentials_path: str, token_path: str) -> Credentials:
    if os.path.exists(token_path):
        return Credentials.from_authorized_user_file(token_path, SCOPES)

    flow = InstalledAppFlow.from_client_secrets_file(
            credentials_path,
            SCOPES,
        )
    # OOB redirect flow is deprecated/blocked by Google.
    # Google installed-app OAuth requires loopback redirect URIs.
    oauth_host = os.environ.get("GOOGLE_OAUTH_HOST", "127.0.0.1")
    oauth_bind_addr = os.environ.get("GOOGLE_OAUTH_BIND_ADDR", oauth_host)
    oauth_port = int(os.environ.get("GOOGLE_OAUTH_PORT", "0"))

    if _is_private_ip(oauth_host):
        print(
            "GOOGLE_OAUTH_HOST is a private IP address. "
            "Google installed-app OAuth requires loopback host values "
            "(127.0.0.1 or localhost). Falling back to 127.0.0.1."
        )
        oauth_host = "127.0.0.1"
    if _is_private_ip(oauth_bind_addr):
        print(
            "GOOGLE_OAUTH_BIND_ADDR is a private IP address. "
            "Falling back to 127.0.0.1 for local callback binding."
        )
        oauth_bind_addr = "127.0.0.1"

    print("\n" + "=" * 60)
    print("GOOGLE AUTHORIZATION REQUIRED")
    print("This opens a temporary local callback server for OAuth.")
    print(f"Callback host: {oauth_host} (bind: {oauth_bind_addr}, port: {oauth_port})")
    print("Tip: keep host and bind address aligned (default 127.0.0.1) to avoid IPv6 localhost mismatches.")
    print(
        "If authorizing from another device, use SSH port-forwarding with a fixed "
        "GOOGLE_OAUTH_PORT (for example: ssh -L 8080:127.0.0.1:8080 <pi-host>)."
    )
    print("=" * 60 + "\n")

    creds = flow.run_local_server(
        host=oauth_host,
        bind_addr=oauth_bind_addr,
        port=oauth_port,
        open_browser=False,
        access_type="offline",
        prompt="consent",
    )
    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    return creds


def ensure_google_token(credentials_path: str, token_path: str) -> None:
    _get_creds(credentials_path, token_path)

def fetch_google_events(
    calendar_ids: List[str],
    day_start: datetime,
    day_end: datetime,
    tz: ZoneInfo,
    credentials_path: str,
    token_path: str,
) -> List[Event]:
    creds = _get_creds(credentials_path, token_path)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    events: List[Event] = []
    time_min = day_start.isoformat()
    time_max = day_end.isoformat()

    for cal_id in calendar_ids:
        resp = service.events().list(
            calendarId=cal_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        for item in resp.get("items", []):
            title = item.get("summary", "(No title)")
            location = item.get("location")

            start_obj = item.get("start", {})
            end_obj = item.get("end", {})

            # All-day events have "date" not "dateTime"
            if "date" in start_obj:
                # Interpret as local midnight range
                start = datetime.fromisoformat(start_obj["date"]).replace(tzinfo=tz)
                end = datetime.fromisoformat(end_obj["date"]).replace(tzinfo=tz)
                all_day = True
            else:
                start = datetime.fromisoformat(start_obj["dateTime"]).astimezone(tz)
                end = datetime.fromisoformat(end_obj["dateTime"]).astimezone(tz)
                all_day = False

            events.append(Event(
                source="google",
                title=title,
                start=start,
                end=end,
                all_day=all_day,
                location=location,
            ))

    return events
