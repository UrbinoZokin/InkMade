from datetime import datetime
from zoneinfo import ZoneInfo

import inkycal.reminders_google as rg


class _FakeExecutable:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeTaskLists:
    def __init__(self, items):
        self._items = items

    def list(self, **kwargs):
        return _FakeExecutable({"items": self._items})


class _FakeTasks:
    def __init__(self, by_list):
        self._by_list = by_list

    def list(self, tasklist, **kwargs):
        return _FakeExecutable({"items": self._by_list.get(tasklist, [])})


class _FakeService:
    def __init__(self, tasklists, tasks_by_list):
        self._tasklists = _FakeTaskLists(tasklists)
        self._tasks = _FakeTasks(tasks_by_list)

    def tasklists(self):
        return self._tasklists

    def tasks(self):
        return self._tasks


def _patch(monkeypatch, tasklists, tasks_by_list):
    monkeypatch.setattr(rg, "_load_creds", lambda token_path: object())
    monkeypatch.setattr(
        rg, "build", lambda *a, **k: _FakeService(tasklists, tasks_by_list)
    )


def test_includes_today_and_overdue_skips_future_and_undated(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    day_end = datetime(2026, 2, 6, 0, 0, tzinfo=tz)  # exclusive end of 2026-02-05

    tasks = [
        {"title": "Overdue item", "status": "needsAction", "due": "2026-02-03T00:00:00.000Z"},
        {"title": "Today item", "status": "needsAction", "due": "2026-02-05T00:00:00.000Z"},
        {"title": "Future item", "status": "needsAction", "due": "2026-02-07T00:00:00.000Z"},
        {"title": "Undated item", "status": "needsAction"},
        {"title": "Done item", "status": "completed", "due": "2026-02-05T00:00:00.000Z"},
        {"title": "  ", "status": "needsAction", "due": "2026-02-05T00:00:00.000Z"},
    ]
    _patch(monkeypatch, [{"id": "L1", "title": "My Tasks"}], {"L1": tasks})

    reminders = rg.fetch_google_tasks("token.json", tz, day_end)
    titles = [r.title for r in reminders]

    assert titles == ["Overdue item", "Today item"]
    overdue = next(r for r in reminders if r.title == "Overdue item")
    today = next(r for r in reminders if r.title == "Today item")
    assert overdue.overdue is True
    assert today.overdue is False


def test_task_list_allowlist_filters_lists(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    day_end = datetime(2026, 2, 6, 0, 0, tzinfo=tz)

    _patch(
        monkeypatch,
        [{"id": "L1", "title": "Personal"}, {"id": "L2", "title": "Work"}],
        {
            "L1": [{"title": "Personal task", "status": "needsAction", "due": "2026-02-05T00:00:00Z"}],
            "L2": [{"title": "Work task", "status": "needsAction", "due": "2026-02-05T00:00:00Z"}],
        },
    )

    reminders = rg.fetch_google_tasks("token.json", tz, day_end, task_list_allowlist=["Work"])
    assert [r.title for r in reminders] == ["Work task"]


def test_parse_due_handles_bad_and_missing_values():
    tz = ZoneInfo("America/Phoenix")
    assert rg._parse_due(None, tz) is None
    assert rg._parse_due("not-a-date", tz) is None
    parsed = rg._parse_due("2026-02-05T00:00:00.000Z", tz)
    assert (parsed.year, parsed.month, parsed.day) == (2026, 2, 5)
    assert parsed.tzinfo == tz
