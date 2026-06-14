from __future__ import annotations
from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

from .calendar_google import _load_creds
from .models import Reminder


def _parse_due(due_raw: Optional[str], tz: ZoneInfo) -> Optional[datetime]:
    """Parse a Google Tasks ``due`` value into a timezone-aware datetime.

    Google Tasks stores ``due`` as an RFC3339 timestamp, but only the date part
    is meaningful (the time is always midnight UTC). We anchor it to local
    midnight so date comparisons against "today" behave intuitively.
    """
    if not due_raw:
        return None
    try:
        parsed = datetime.fromisoformat(due_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=tz)


def fetch_google_tasks(
    token_path: str,
    tz: ZoneInfo,
    day_end: datetime,
    task_list_allowlist: Optional[List[str]] = None,
) -> List[Reminder]:
    """Fetch incomplete Google Tasks that are due today or overdue.

    Tasks with no due date are skipped (they are open-ended "someday" items and
    would clutter a daily display). Tasks due after ``day_end`` are also skipped.
    """
    creds = _load_creds(token_path)
    service = build("tasks", "v1", credentials=creds, cache_discovery=False)

    allowlist = set(task_list_allowlist or [])
    reminders: List[Reminder] = []
    # ``day_end`` is the exclusive end of today (next local midnight); today's
    # start is one day earlier. Anything due before it is overdue.
    day_start = (
        day_end.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        - timedelta(days=1)
    )

    tasklists = service.tasklists().list(maxResults=100).execute().get("items", [])
    for tasklist in tasklists:
        if allowlist and tasklist.get("title") not in allowlist:
            continue

        resp = service.tasks().list(
            tasklist=tasklist["id"],
            showCompleted=False,
            showHidden=False,
            maxResults=100,
        ).execute()

        for item in resp.get("items", []):
            if item.get("status") == "completed":
                continue
            title = (item.get("title") or "").strip()
            if not title:
                continue

            due = _parse_due(item.get("due"), tz)
            if due is None:
                continue
            if due >= day_end:
                continue

            reminders.append(
                Reminder(
                    source="google",
                    title=title,
                    due=due,
                    overdue=due < day_start,
                )
            )

    return reminders
