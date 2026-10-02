"""One setup session: its one-time code, its deadline, and the wrong codes it has seen.

Shared by the HTTP and Bluetooth transports, which both refuse any change that
doesn't carry the code shown on the panel. Six digits are only safe because
guessing is capped: after MAX_WRONG_CODES wrong codes the session ends, so
anyone guessing gets 5 tries in a million before they'd need the device in
front of them again to press C.
"""
from __future__ import annotations

import hmac
import secrets
import threading
import time
from typing import Callable

CODE_DIGITS = 6
SESSION_MINUTES = 10
MAX_WRONG_CODES = 5

# check() verdicts
OK = "ok"
MISSING = "missing"  # no code at all: not a guess, so it doesn't count
WRONG = "wrong"
CLOSED = "closed"  # the session is over: out of time, out of tries, or finished


def new_code() -> str:
    return f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"


def _digits(value: str) -> str:
    # People type the code the way the panel shows it ("482 913"), or with a dash.
    return "".join(ch for ch in (value or "") if ch.isdigit())


class SetupSession:
    def __init__(
        self,
        code: str = "",
        *,
        seconds: float = SESSION_MINUTES * 60,
        max_wrong: int = MAX_WRONG_CODES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.code = code or new_code()
        self.seconds = seconds
        self._max_wrong = max_wrong
        self._clock = clock
        self._lock = threading.Lock()
        self._deadline = clock() + seconds
        self._wrong = 0
        self._end_reason = ""

    def check(self, attempt: str) -> str:
        """Judge one supplied code, counting it against the session if it's wrong."""
        with self._lock:
            if self._ended():
                return CLOSED
            supplied = _digits(attempt)
            if not supplied:
                return MISSING
            if hmac.compare_digest(supplied.encode(), self.code.encode()):
                return OK
            self._wrong += 1
            if self._wrong >= self._max_wrong:
                self._end_reason = "too many wrong setup codes"
            return WRONG

    def extend(self) -> bool:
        """Restart the clock (another press of button C). False once the session is over."""
        with self._lock:
            if self._ended():
                return False
            self._deadline = self._clock() + self.seconds
            return True

    def finish(self, reason: str) -> None:
        with self._lock:
            if not self._end_reason:
                self._end_reason = reason

    @property
    def ended(self) -> bool:
        with self._lock:
            return self._ended()

    @property
    def end_reason(self) -> str:
        with self._lock:
            self._ended()
            return self._end_reason

    @property
    def wrong_codes_left(self) -> int:
        with self._lock:
            return max(0, self._max_wrong - self._wrong)

    def seconds_left(self) -> float:
        with self._lock:
            return max(0.0, self._deadline - self._clock())

    def _ended(self) -> bool:
        if not self._end_reason and self._clock() >= self._deadline:
            self._end_reason = "timed out"
        return bool(self._end_reason)


def refusal(verdict: str, session: SetupSession) -> str:
    """What to tell the companion app when `verdict` isn't OK."""
    if verdict == MISSING:
        return "Enter the setup code shown on the InkyCal's screen."
    if verdict == WRONG and not session.ended:
        left = session.wrong_codes_left
        return (
            "That setup code is wrong. Check the code on the InkyCal's screen "
            f"({left} {'try' if left == 1 else 'tries'} left)."
        )
    if session.end_reason == "too many wrong setup codes":
        return (
            "Too many wrong setup codes, so setup mode has ended. "
            "Press button C on the InkyCal to start again with a new code."
        )
    return "Setup mode has ended. Press button C on the InkyCal to turn it back on."
