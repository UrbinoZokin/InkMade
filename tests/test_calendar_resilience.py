from types import SimpleNamespace
from datetime import datetime
from zoneinfo import ZoneInfo

from inkycal.main import _fetch_events_for_range


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
