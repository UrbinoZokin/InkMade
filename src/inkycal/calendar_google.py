from __future__ import annotations
from datetime import datetime
from typing import List
from zoneinfo import ZoneInfo
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .models import Event

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
]


class GoogleAuthError(RuntimeError):
    """Raised when the Google token file is missing or cannot be refreshed."""


def _load_creds(token_path: str) -> Credentials:
    # The interactive OAuth flow runs off-device (scripts/google_auth.py) and
    # produces token_path. The Pi only reads that file and refreshes the
    # access token using the stored refresh_token; it never prompts a user.
    if not token_path or not os.path.exists(token_path):
        raise GoogleAuthError(
            f"Google token file not found at '{token_path}'. "
            "Generate it off-device with scripts/google_auth.py and copy it here."
        )

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _persist_token(token_path, creds)
        return creds

    raise GoogleAuthError(
        f"Google token at '{token_path}' is invalid and cannot be refreshed. "
        "Re-run scripts/google_auth.py off-device to regenerate it."
    )


def _persist_token(token_path: str, creds: Credentials) -> None:
    parent = os.path.dirname(token_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())


def fetch_google_events(
    calendar_ids: List[str],
    day_start: datetime,
    day_end: datetime,
    tz: ZoneInfo,
    token_path: str,
) -> List[Event]:
    creds = _load_creds(token_path)
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

            if "date" in start_obj:
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
