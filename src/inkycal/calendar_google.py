from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .calendar_common import normalize_all_day_bounds
from .models import Event

# Google exposes the birthdays it derives from Google Contacts as a
# read-only calendar with this fixed id. It needs no extra OAuth scope beyond
# calendar.readonly, and it is not returned as part of "primary".
CONTACTS_BIRTHDAY_CALENDAR_ID = "addressbook#contacts@group.v.calendar.google.com"

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


def _is_birthday(item: dict, calendar_id: str) -> bool:
    # Google tags contact birthdays/anniversaries with eventType "birthday";
    # older responses from the contacts calendar carry no eventType at all, so
    # fall back to the calendar the item came from.
    if item.get("eventType") == "birthday":
        return True
    return calendar_id == CONTACTS_BIRTHDAY_CALENDAR_ID


def _parse_google_event(item: dict, tz: ZoneInfo, calendar_id: str) -> Optional[Event]:
    start_obj = item.get("start", {})
    end_obj = item.get("end", {})

    if "date" in start_obj:
        start = datetime.fromisoformat(start_obj["date"]).replace(tzinfo=tz)
        raw_end = end_obj.get("date")
        end = datetime.fromisoformat(raw_end).replace(tzinfo=tz) if raw_end else None
        start, end = normalize_all_day_bounds(start, end, tz)
        all_day = True
    elif "dateTime" in start_obj and "dateTime" in end_obj:
        start = datetime.fromisoformat(start_obj["dateTime"]).astimezone(tz)
        end = datetime.fromisoformat(end_obj["dateTime"]).astimezone(tz)
        all_day = False
    else:
        # Cancelled instances of a recurring event come back without times.
        return None

    return Event(
        source="google",
        title=item.get("summary") or "(No title)",
        start=start,
        end=end,
        all_day=all_day,
        birthday=_is_birthday(item, calendar_id),
        location=item.get("location"),
    )


def _list_calendar_events(service, calendar_id: str, time_min: str, time_max: str) -> List[dict]:
    items: List[dict] = []
    page_token = None
    while True:
        resp = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            pageToken=page_token,
        ).execute()
        items.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            return items


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
        try:
            items = _list_calendar_events(service, cal_id, time_min, time_max)
        except Exception as e:
            # One unreadable calendar (a stale id, or a birthday calendar the
            # account doesn't have) must not cost us every other calendar.
            print(f"Google Calendar '{cal_id}' fetch failed; skipping it. Error: {e}")
            continue

        for item in items:
            event = _parse_google_event(item, tz, cal_id)
            if event is not None:
                events.append(event)

    return events
