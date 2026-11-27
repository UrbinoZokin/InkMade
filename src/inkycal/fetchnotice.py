"""The red line at the bottom of the screen that says what couldn't be fetched.

Every fetch (the forecast, NWS alerts, Google and iCloud calendars) is allowed
to fail without failing the run, and the screen is drawn without what it would
have shown. That keeps the panel updating, but a day missing its Google events
looks like a free day, and missing weather looks like nothing at all. So each
failure is recorded as a FetchProblem and drawn as a short notice instead, with
the reason cut down to a few words: enough to tell "the Pi is offline" from
"the service is down" from "the calendar needs signing in again" without
reading the logs. The full error still goes to the log as before.
"""
from __future__ import annotations

import errno
import socket
import ssl
import urllib.error
from dataclasses import dataclass
from typing import Iterator, List, Optional, Sequence

# What each fetch is called on the screen.
WEATHER = "Weather"
WEATHER_ALERTS = "Weather alerts"
GOOGLE = "Google"
ICLOUD = "iCloud"


@dataclass(frozen=True)
class FetchProblem:
    source: str  # one of the names above, perhaps qualified: "Google (1 calendar)"
    reason: str  # a few words from describe_error, or "not set up"

    def __str__(self) -> str:
        return f"{self.source}: {self.reason}"


# How far _causes follows an exception's chain. Real chains are three or four
# deep (requests -> urllib3 -> socket); this only guards against a cycle.
_MAX_CAUSES = 20


def _causes(exc: BaseException) -> Iterator[BaseException]:
    """`exc` and every exception it wraps, outermost first.

    The useful part is usually at the bottom. Google's client and requests
    each wrap urllib3, which wraps the socket error, and they link them in
    different ways: raise ... from (__cause__), raising inside an except
    (__context__), a .reason attribute (urllib's URLError, urllib3's
    MaxRetryError), or the wrapped exception as an argument (requests).
    """
    seen = set()
    queue: List[BaseException] = [exc]
    while queue and len(seen) < _MAX_CAUSES:
        e = queue.pop(0)
        if id(e) in seen:
            continue
        seen.add(id(e))
        yield e
        linked = [e.__cause__, e.__context__, getattr(e, "reason", None), *getattr(e, "args", ())]
        queue.extend(x for x in linked if isinstance(x, BaseException))


def http_status(exc: BaseException) -> Optional[int]:
    """The HTTP status the server answered with, if the failure was an HTTP error."""
    for e in _causes(exc):
        if isinstance(e, urllib.error.HTTPError):
            candidates = [e.code]
        else:
            candidates = [
                getattr(getattr(e, "resp", None), "status", None),  # googleapiclient HttpError
                getattr(getattr(e, "response", None), "status_code", None),  # requests HTTPError
            ]
        for status in candidates:
            try:
                return int(status)
            except (TypeError, ValueError):
                continue
    return None


def _describe_status(status: int) -> str:
    if status == 401:
        return "sign-in rejected"
    if status == 403:
        return "access denied"
    if status == 404:
        return "not found"
    if status == 429:
        return "rate limited"
    if status >= 500:
        return f"server error {status}"
    return f"error {status}"


_NO_ROUTE_ERRNOS = {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN}


def describe_error(exc: BaseException) -> str:
    """A few words on why a fetch failed, short enough for the status line."""
    causes = list(_causes(exc))
    names = {type(e).__name__ for e in causes}

    # Checked in this order because the libraries' own classes overlap: in
    # urllib3 a failed DNS lookup is a subclass of its connect *timeout*.
    if any(isinstance(e, socket.gaierror) for e in causes) or "NameResolutionError" in names:
        return "no internet"
    if any(isinstance(e, OSError) and e.errno in _NO_ROUTE_ERRNOS for e in causes):
        return "no internet"
    if any(isinstance(e, ssl.SSLError) for e in causes):
        # On a Pi this is most often its clock being wrong (it has no
        # battery-backed clock), which makes every certificate look invalid.
        return "certificate error"
    if any(isinstance(e, TimeoutError) or "Timeout" in type(e).__name__ for e in causes):
        return "timed out"

    status = http_status(exc)
    if status is not None:
        return _describe_status(status)

    if any(isinstance(e, ConnectionError) for e in causes) or names & {
        "NewConnectionError",
        "ProtocolError",
        "RemoteDisconnected",
    }:
        return "connection failed"
    if "RefreshError" in names:  # google-auth: the refresh token was revoked or expired
        return "sign-in expired"
    if "GoogleAuthError" in names:  # calendar_google: no usable token file
        return "needs sign-in"
    if "AuthorizationError" in names:  # caldav: iCloud turned the app password down
        return "sign-in rejected"
    if "NotFoundError" in names:  # caldav
        return "not found"
    if any(isinstance(e, ValueError) for e in causes):  # JSON that didn't parse, or wasn't what we expected
        return "bad response"
    return "failed"


def notice_text(problems: Sequence[FetchProblem]) -> Optional[str]:
    """The notice for `problems`, or None when there are none.

    Sources that failed for the same reason share it, so an outage reads
    "Weather, Google: no internet" rather than repeating it for each.
    """
    if not problems:
        return None
    by_reason: dict[str, List[str]] = {}
    for p in problems:
        sources = by_reason.setdefault(p.reason, [])
        if p.source not in sources:
            sources.append(p.source)
    return " · ".join(f"{', '.join(sources)}: {reason}" for reason, sources in by_reason.items())
