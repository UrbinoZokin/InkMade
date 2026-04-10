from types import SimpleNamespace
from datetime import datetime
from zoneinfo import ZoneInfo

from inkycal.main import _clip_events_to_range, _fetch_events_for_range
from inkycal.models import Event


def test_fetch_events_for_range_continues_when_google_fetch_fails(monkeypatch, capsys):
    tz = ZoneInfo("America/Phoenix")
    cfg = SimpleNamespace(
        google=SimpleNamespace(enabled=True, calendar_ids=["primary"]),
        icloud=SimpleNamespace(enabled=False, calendar_name_allowlist=[]),
        travel=SimpleNamespace(enabled=False, origin_address="", back_to_back_window_minutes=30),
    )

    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", "/tmp/creds.json")
    monkeypatch.setenv("GOOGLE_TOKEN_JSON", "/tmp/token.json")
    monkeypatch.setattr(
        "inkycal.main.fetch_google_events",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("invalid_grant")),
    )

    events = _fetch_events_for_range(
        cfg,
        datetime(2026, 2, 5, 0, 0, tzinfo=tz),
        datetime(2026, 2, 6, 0, 0, tzinfo=tz),
        tz,
    )

    out = capsys.readouterr().out

    assert events == []
    assert "Google Calendar fetch failed; continuing without Google events." in out


def test_clip_events_to_range_keeps_overlapping_segment_for_multiday_event():
    tz = ZoneInfo("America/Phoenix")
    range_start = datetime(2026, 2, 6, 0, 0, tzinfo=tz)
    range_end = datetime(2026, 2, 7, 0, 0, tzinfo=tz)
    event = Event(
        source="icloud",
        title="Overnight trip",
        start=datetime(2026, 2, 5, 22, 0, tzinfo=tz),
        end=datetime(2026, 2, 6, 8, 0, tzinfo=tz),
    )

    clipped = _clip_events_to_range([event], range_start, range_end)

    assert len(clipped) == 1
    assert clipped[0].start == range_start
    assert clipped[0].end == datetime(2026, 2, 6, 8, 0, tzinfo=tz)
