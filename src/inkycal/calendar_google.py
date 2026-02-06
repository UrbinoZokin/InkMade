from __future__ import annotations
from datetime import datetime
from typing import List
from zoneinfo import ZoneInfo
import os

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .models import Event

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

def _get_creds(credentials_path: str, token_path: str) -> Credentials:
    if os.path.exists(token_path):
        return Credentials.from_authorized_user_file(token_path, SCOPES)

    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
    creds = flow.run_local_server(port=0)
    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    return creds

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
