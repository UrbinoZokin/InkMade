"""What couldn't be fetched is said at the bottom of the screen, not just logged.

A fetch that fails is drawn without: no weather beside the events, no Google
events on the day. That kept the panel updating, but it also made an outage
look like an empty day, and the only record of it was the log on the Pi.
"""
from __future__ import annotations

import json
import socket
import ssl
import urllib.error
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httplib2
import pytest
import requests
import urllib3.exceptions
from caldav.lib.error import AuthorizationError
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError
from PIL import Image, ImageDraw

from inkycal import main, render
from inkycal.calendar_google import CONTACTS_BIRTHDAY_CALENDAR_ID, GoogleAuthError
from inkycal.fetchnotice import FetchProblem, describe_error, http_status, notice_text
from inkycal.models import Event
from inkycal.state import load_state

TZ = ZoneInfo("America/Phoenix")


def _raised(exc: BaseException, cause: BaseException | None = None) -> BaseException:
    """`exc` as it would be caught: raised, chained to `cause` if one is given."""
    try:
        if cause is None:
            raise exc
        raise exc from cause
    except BaseException as caught:
        return caught


def _requests_dns_failure() -> BaseException:
    # What requests raises when the Pi can't resolve a hostname: its
    # ConnectionError around urllib3's retry error around the lookup failure.
    lookup = _raised(
        urllib3.exceptions.NameResolutionError("api.example.com", None, socket.gaierror(-3, "Temporary failure")),
        socket.gaierror(-3, "Temporary failure"),
    )
    retries = urllib3.exceptions.MaxRetryError(None, "/", reason=lookup)
    return _raised(requests.exceptions.ConnectionError(retries))


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.open-meteo.com/v1/forecast", status, "x", {}, None)


# ---- describe_error: the reason, in a few words ----------------------------


@pytest.mark.parametrize(
    "exc, reason",
    [
        # urllib (Open-Meteo, weather.gov)
        (urllib.error.URLError(socket.gaierror(-2, "Name or service not known")), "no internet"),
        (urllib.error.URLError(OSError(101, "Network is unreachable")), "no internet"),
        (urllib.error.URLError(TimeoutError("timed out")), "timed out"),
        (TimeoutError("The read operation timed out"), "timed out"),
        (_http_error(503), "server error 503"),
        (_http_error(429), "rate limited"),
        (_http_error(400), "error 400"),
        (urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed")), "certificate error"),
        (urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")), "connection failed"),
        (json.JSONDecodeError("Expecting value", "<html>", 0), "bad response"),
        # requests (google-auth's refresh, caldav)
        (_requests_dns_failure(), "no internet"),
        (requests.exceptions.ReadTimeout("read timed out"), "timed out"),
        # Google
        (HttpError(httplib2.Response({"status": 404}), b""), "not found"),
        (HttpError(httplib2.Response({"status": 500}), b""), "server error 500"),
        (RefreshError("invalid_grant: Token has been expired or revoked."), "sign-in expired"),
        (_raised(TransportError("refresh failed"), _requests_dns_failure()), "no internet"),
        (GoogleAuthError("Google token file not found"), "needs sign-in"),
        # iCloud
        (AuthorizationError(url="https://caldav.icloud.com", reason="Unauthorized"), "sign-in rejected"),
        # Anything else
        (RuntimeError("something odd"), "failed"),
    ],
)
def test_describe_error(exc, reason):
    assert describe_error(exc) == reason


def test_http_status_reads_each_librarys_error():
    assert http_status(_http_error(502)) == 502
    assert http_status(HttpError(httplib2.Response({"status": 404}), b"")) == 404
    assert http_status(RuntimeError("no status")) is None


# ---- notice_text: one line for all of them ---------------------------------


def test_no_problems_no_notice():
    assert notice_text([]) is None


def test_sources_that_failed_the_same_way_share_the_reason():
    problems = [
        FetchProblem("Weather", "no internet"),
        FetchProblem("Weather alerts", "no internet"),
        FetchProblem("iCloud", "sign-in rejected"),
        FetchProblem("Google", "no internet"),
    ]
    assert notice_text(problems) == "Weather, Weather alerts, Google: no internet · iCloud: sign-in rejected"


# ---- the calendar fetch records what it couldn't get -----------------------

RANGE = (datetime(2026, 2, 5, tzinfo=TZ), datetime(2026, 2, 6, tzinfo=TZ))


def _cfg(google=False, icloud=False, calendar_ids=("primary",)):
    return SimpleNamespace(
        google=SimpleNamespace(enabled=google, calendar_ids=list(calendar_ids), birthdays_enabled=True),
        icloud=SimpleNamespace(enabled=icloud, calendar_name_allowlist=[]),
    )


@pytest.fixture
def google_token(monkeypatch):
    monkeypatch.setenv("GOOGLE_TOKEN_JSON", "/tmp/token.json")


def _fetch_problems(cfg) -> list:
    problems: list = []
    main._fetch_raw_events(cfg, *RANGE, TZ, problems=problems)
    return problems


def test_a_failed_google_fetch_is_a_problem(google_token, monkeypatch):
    def fail(*_a, **_kw):
        raise RefreshError("invalid_grant")

    monkeypatch.setattr(main, "fetch_google_events", fail)

    assert _fetch_problems(_cfg(google=True)) == [FetchProblem("Google", "sign-in expired")]


def _google_with_failures(monkeypatch, failing: dict):
    """fetch_google_events as it would run with the calendars in `failing` unreadable."""

    def fetch(calendar_ids, *_a, failures=None, **_kw):
        for cal_id in calendar_ids:
            if cal_id in failing:
                failures.append((cal_id, failing[cal_id]))
        return []

    monkeypatch.setattr(main, "fetch_google_events", fetch)


def test_every_google_calendar_failing_reads_as_google(google_token, monkeypatch):
    # Offline with a still-valid token: no exception escapes the fetch, but
    # every calendar fails on its own.
    dns = urllib.error.URLError(socket.gaierror(-2, "Name or service not known"))
    _google_with_failures(monkeypatch, {"primary": dns, CONTACTS_BIRTHDAY_CALENDAR_ID: dns})

    assert _fetch_problems(_cfg(google=True)) == [FetchProblem("Google", "no internet")]


def test_some_google_calendars_failing_says_how_many(google_token, monkeypatch):
    _google_with_failures(monkeypatch, {"work": HttpError(httplib2.Response({"status": 404}), b"")})

    problems = _fetch_problems(_cfg(google=True, calendar_ids=["primary", "work"]))

    assert problems == [FetchProblem("Google (1 calendar)", "not found")]


def test_an_account_without_a_birthday_calendar_is_not_a_problem(google_token, monkeypatch):
    # It's added for everyone, and an account without one answers 404 every run.
    _google_with_failures(
        monkeypatch, {CONTACTS_BIRTHDAY_CALENDAR_ID: HttpError(httplib2.Response({"status": 404}), b"")}
    )

    assert _fetch_problems(_cfg(google=True)) == []


def test_the_birthday_calendar_failing_otherwise_still_is(google_token, monkeypatch):
    _google_with_failures(
        monkeypatch, {CONTACTS_BIRTHDAY_CALENDAR_ID: HttpError(httplib2.Response({"status": 500}), b"")}
    )

    assert _fetch_problems(_cfg(google=True)) == [FetchProblem("Google (1 calendar)", "server error 500")]


def test_google_without_a_token_is_not_set_up(monkeypatch):
    monkeypatch.delenv("GOOGLE_TOKEN_JSON", raising=False)

    assert _fetch_problems(_cfg(google=True)) == [FetchProblem("Google", "not set up")]


def test_a_failed_icloud_fetch_is_a_problem(monkeypatch):
    monkeypatch.setenv("ICLOUD_USERNAME", "someone")
    monkeypatch.setenv("ICLOUD_APP_PASSWORD", "secret")

    def fail(*_a, **_kw):
        raise AuthorizationError(url="https://caldav.icloud.com", reason="Unauthorized")

    monkeypatch.setattr(main, "fetch_icloud_events", fail)

    assert _fetch_problems(_cfg(icloud=True)) == [FetchProblem("iCloud", "sign-in rejected")]


def test_icloud_without_credentials_is_not_set_up(monkeypatch):
    monkeypatch.delenv("ICLOUD_USERNAME", raising=False)
    monkeypatch.delenv("ICLOUD_APP_PASSWORD", raising=False)

    assert _fetch_problems(_cfg(icloud=True)) == [FetchProblem("iCloud", "not set up")]


def test_nothing_enabled_nothing_to_report():
    assert _fetch_problems(_cfg()) == []


# ---- run_once: the notice comes and goes with the outage -------------------

CONFIG = """
timezone: "America/Phoenix"
sleep:
  enabled: false
display:
  width: 60
  height: 80
  rotate_degrees: 0
  border: white
calendars:
  google:
    enabled: false
  icloud:
    enabled: false
travel:
  enabled: false
auto_update:
  enabled: false
"""


@pytest.fixture
def run(tmp_path, monkeypatch):
    """run_once against a stubbed panel, with the forecast up or down as
    `run.weather_down` says. Returns the namespace; `.drawn` collects the
    fetch problems of each frame put on the panel."""
    config = tmp_path / "config.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    state = SimpleNamespace(weather_down=False, drawn=[], state_path=str(tmp_path / "state.json"))

    class Weather:
        def __init__(self, **_kw):
            self.error = urllib.error.URLError(socket.gaierror(-2, "Name or service not known")) if state.weather_down else None

        def load(self):
            if self.error:
                raise self.error

        def active_alerts(self):
            return []

        def forecast_for_datetime(self, _when):
            self.load()

        forecast_for_event_start = forecast_for_datetime

        def daily_forecasts(self):
            self.load()
            return {}

    panel = []

    def daily(**kw):
        img = Image.new("RGB", (60, 80), "white")
        img.info["fetch_problems"] = kw["fetch_problems"]
        return img

    monkeypatch.setattr(main, "WeatherForecastResolver", Weather)
    monkeypatch.setattr(main, "_fetch_raw_events", lambda *_a, **_kw: [])
    monkeypatch.setattr(main, "render_daily_schedule", daily)
    monkeypatch.setattr(main, "show_on_inky", lambda img, **_kw: state.drawn.append(img.info["fetch_problems"]))

    def once():
        main.run_once(config_path=str(config), state_path=state.state_path)

    state.once = once
    return state


def test_a_failed_forecast_is_drawn_as_a_notice(run, capsys):
    run.weather_down = True
    run.once()

    assert run.drawn == [[FetchProblem("Weather", "no internet")]]
    assert "Fetch problems shown on screen: Weather: no internet" in capsys.readouterr().out


def test_the_panel_repaints_when_the_forecast_comes_back(run):
    # The forecast isn't in the content hash, so this used to wait for the
    # hourly repaint: up to an hour of a screen with no weather on it.
    run.weather_down = True
    run.once()
    run.once()  # still down: nothing new to show
    run.weather_down = False
    run.once()

    assert run.drawn == [[FetchProblem("Weather", "no internet")], []]


def test_a_forecast_going_down_repaints_too(run):
    run.once()
    run.weather_down = True
    run.once()

    assert run.drawn == [[], [FetchProblem("Weather", "no internet")]]
    assert load_state(run.state_path).last_hash


# ---- render: red, at the bottom, and only when there's something to say ----

W, H, PADDING = 1200, 1600, 40
NOW = datetime(2026, 2, 5, 8, 0, tzinfo=TZ)
PROBLEMS = [FetchProblem("Weather", "no internet"), FetchProblem("Google", "no internet")]


def _daily(problems):
    event = Event(source="google", title="Focus", start=NOW + timedelta(hours=1), end=NOW + timedelta(hours=2))
    return render.render_daily_schedule(
        canvas_w=W, canvas_h=H, now=NOW, events=[event], tz=TZ,
        show_sleep_banner=False, sleep_banner_text="", fetch_problems=problems,
    )


def _weekly(problems):
    return render.render_weekly_schedule(
        canvas_w=W, canvas_h=H, now=NOW, week_events=[], tz=TZ,
        show_sleep_banner=False, sleep_banner_text="", fetch_problems=problems,
    )


def _red_box(img):
    """The bounding box of the pure-red pixels in `img`, or None."""
    r, g, b = img.split()
    red = Image.eval(r, lambda v: 255 if v > 200 else 0)
    not_green = Image.eval(g, lambda v: 255 if v < 60 else 0)
    not_blue = Image.eval(b, lambda v: 255 if v < 60 else 0)
    from PIL import ImageChops

    return ImageChops.multiply(ImageChops.multiply(red, not_green), not_blue).getbbox()


@pytest.mark.parametrize("draw", [_daily, _weekly], ids=["daily", "weekly"])
def test_the_notice_is_red_and_just_above_the_status_line(draw):
    assert _red_box(draw([])) is None, "nothing red without a problem"

    left, top, right, bottom = _red_box(draw(PROBLEMS))
    assert left >= PADDING and right <= W - PADDING
    # One line of 30px text, sitting directly above the "Updated" line.
    assert top > H - PADDING - 120 and bottom < H - PADDING - 30


def test_a_long_notice_is_cut_with_an_ellipsis():
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = render._load_font(30)
    problems = [FetchProblem(f"Source {i}", f"reason number {i}") for i in range(20)]

    lines = render._fetch_notice_lines(d, problems, font, 500)

    assert len(lines) == render.FETCH_NOTICE_MAX_LINES
    assert lines[0].startswith("⚠ ")
    assert lines[-1].endswith("…")
    assert all(d.textlength(line, font=font) <= 500 for line in lines)
