"""One setup session: its one-time code, its deadline, and the wrong codes it has seen.

The code never crosses the network or Bluetooth. The companion app and the
agent use it as the password of a key exchange (setupcrypto.py): pair() runs
the Pi's half, and a wrong code shows up as the first sealed message of that
exchange failing to open(). That is what counts as a guess here, and each
exchange gets exactly one. Six digits are only safe because guessing is
capped: after MAX_WRONG_CODES the session ends, so anyone guessing gets 5
tries in a million before they'd need the device in front of them again to
hold C.
"""
from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict
from typing import Callable, Optional, Tuple

from ..setupmode import HOLD_SECONDS, SESSION_MINUTES
from .setupcrypto import BadSeal, Channel, pi_handshake

CODE_DIGITS = 6
MAX_WRONG_CODES = 5
# Exchanges started but not yet spent. Each holds a key, and the oldest goes
# first, so flooding the agent with exchanges can't make it hoard them.
MAX_PAIRINGS = 8

# open() verdicts
OK = "ok"
WRONG = "wrong"
UNPAIRED = "unpaired"  # no such exchange: never was, pushed out, or spent on a wrong code
CLOSED = "closed"  # the session is over: out of time, out of tries, or finished


class SessionClosed(RuntimeError):
    """The session is over; nothing more is accepted."""


def new_code() -> str:
    return f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"


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
        self._pairings: "OrderedDict[str, Channel]" = OrderedDict()

    def pair(self, app_message: bytes) -> Tuple[str, bytes]:
        """Answer the app's opening key-exchange message.

        Returns an id for the exchange and the Pi's answer. Raises
        BadHandshake for anything that isn't a key-exchange message, and
        SessionClosed once the session is over.
        """
        if self.ended:
            raise SessionClosed(self.end_reason)
        # Outside the lock: a fraction of a second of pure-Python curve
        # arithmetic on a Pi Zero, which nothing else should wait on.
        answer, channel = pi_handshake(self.code, app_message)
        pairing = secrets.token_urlsafe(16)
        with self._lock:
            if self._ended():
                raise SessionClosed(self._end_reason)
            self._pairings[pairing] = channel
            while len(self._pairings) > MAX_PAIRINGS:
                self._pairings.popitem(last=False)
        return pairing, answer

    def open(
        self, pairing: Optional[str], sealed: bytes, purpose: bytes
    ) -> Tuple[str, Optional[bytes], Optional[Channel]]:
        """Open a message sent over an exchange: (verdict, plaintext, channel).

        A message that won't open counts as a wrong code -- it's the only way
        a wrong one ever shows -- and spends the exchange, so each exchange
        is one guess and no more.
        """
        with self._lock:
            if self._ended():
                return CLOSED, None, None
            channel = self._pairings.get(pairing or "")
        if channel is None:
            return UNPAIRED, None, None
        try:
            plaintext = channel.open(sealed, purpose)
        except BadSeal:
            with self._lock:
                self._pairings.pop(pairing or "", None)
                self._wrong += 1
                if self._wrong >= self._max_wrong and not self._end_reason:
                    self._end_reason = "too many wrong setup codes"
            return WRONG, None, None
        return OK, plaintext, channel

    def extend(self) -> bool:
        """Restart the clock (another hold of button C). False once the session is over."""
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
    if verdict == WRONG and not session.ended:
        left = session.wrong_codes_left
        return (
            "That setup code is wrong. Check the code on the InkyCal's screen "
            f"({left} {'try' if left == 1 else 'tries'} left)."
        )
    if verdict == UNPAIRED and not session.ended:
        return "That setup attempt is no longer open. Start again."
    if session.end_reason == "too many wrong setup codes":
        return (
            "Too many wrong setup codes, so setup mode has ended. "
            f"Hold down button C on the InkyCal for {HOLD_SECONDS} seconds to start again with a new code."
        )
    return f"Setup mode has ended. Hold down button C on the InkyCal for {HOLD_SECONDS} seconds to turn it back on."
