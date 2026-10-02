"""End-to-end encryption for InkyCal setup traffic, keyed by the code on the panel.

There are two copies of this file, the Pi's (src/inkycal/provisioning/) and
the companion app's (companion/inkycal_companion/), because the two halves
ship to different machines. A test keeps them byte-for-byte the same.

The setup code itself never crosses the network or Bluetooth. The app and the
Pi run SPAKE2, a password-authenticated key exchange -- the kind HomeKit and
Matter use to pair with a short code -- with the code as the password. They
end up sharing a key only if both used the same code. Anyone listening learns
nothing about the code or the key, not even enough to test guesses offline,
and anyone taking part gets exactly one guess per exchange, which the Pi
counts against its setup session.

Each message is then sealed with ChaCha20-Poly1305 under a key for its
direction, with a fresh random nonce and its purpose bound in as associated
data: a message can't be read, altered, replayed, reflected back at its
sender, or passed off as a different kind of message.
"""
from __future__ import annotations

import os
import threading

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from spake2 import SPAKE2_A, SPAKE2_B

# Who's who in the exchange. Both sides must use the same pair.
ID_APP = b"inkycal setup: companion app"
ID_PI = b"inkycal setup: pi"

NONCE_BYTES = 12

# What a sealed message is for. It only opens under the purpose it was sealed with.
WIFI = b"inkycal setup v1: wifi"
WIFI_REPLY = b"inkycal setup v1: wifi reply"
GOOGLE_TOKEN = b"inkycal setup v1: google token"
GOOGLE_TOKEN_REPLY = b"inkycal setup v1: google token reply"


def _password(code: str) -> bytes:
    """The code as the exchange uses it: its digits, however it was typed.

    The panel shows "482 913", so that, "482-913" and "482913" must all be the
    same password -- an exchange keyed by the spacing would make the right code
    look wrong.
    """
    return "".join(ch for ch in code if ch in "0123456789").encode("ascii")


class BadHandshake(ValueError):
    """The other side's key-exchange message isn't one."""


class BadSeal(ValueError):
    """A sealed message didn't open: a wrong setup code, tampering, or a replay."""


def _direction_key(shared_key: bytes, direction: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"inkycal setup v1 key: " + direction,
    ).derive(shared_key)


class Channel:
    """Seals and opens messages with the key from one completed exchange."""

    def __init__(self, shared_key: bytes, *, app_side: bool) -> None:
        to_pi = ChaCha20Poly1305(_direction_key(shared_key, b"app to pi"))
        to_app = ChaCha20Poly1305(_direction_key(shared_key, b"pi to app"))
        self._send, self._receive = (to_pi, to_app) if app_side else (to_app, to_pi)
        self._opened: set[bytes] = set()
        self._lock = threading.Lock()

    def seal(self, plaintext: bytes, purpose: bytes) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        return nonce + self._send.encrypt(nonce, plaintext, purpose)

    def open(self, sealed: bytes, purpose: bytes) -> bytes:
        sealed = bytes(sealed)
        nonce, body = sealed[:NONCE_BYTES], sealed[NONCE_BYTES:]
        with self._lock:
            if len(nonce) != NONCE_BYTES or nonce in self._opened:
                raise BadSeal("not a fresh sealed message")
            try:
                plaintext = self._receive.decrypt(nonce, body, purpose)
            except InvalidTag:
                raise BadSeal("the message did not open") from None
            self._opened.add(nonce)
        return plaintext


class AppHandshake:
    """The companion app's half of the exchange.

    Send `message` to the Pi, then pass its answer to finish().
    """

    def __init__(self, code: str) -> None:
        self._spake = SPAKE2_A(_password(code), idA=ID_APP, idB=ID_PI)
        self.message = self._spake.start()

    def finish(self, pi_message: bytes) -> Channel:
        try:
            shared_key = self._spake.finish(bytes(pi_message))
        except Exception as exc:  # spake2 raises several kinds for a malformed message
            raise BadHandshake(f"not a key-exchange message ({exc})") from None
        return Channel(shared_key, app_side=True)


def pi_handshake(code: str, app_message: bytes) -> tuple[bytes, Channel]:
    """The Pi's half: answer the app's message. Returns the answer and the channel.

    A wrong code still yields a channel -- one in which nothing the app sends
    will open. That is how a wrong code shows itself, and only then.
    """
    spake = SPAKE2_B(_password(code), idA=ID_APP, idB=ID_PI)
    answer = spake.start()
    try:
        shared_key = spake.finish(bytes(app_message))
    except Exception as exc:  # spake2 raises several kinds for a malformed message
        raise BadHandshake(f"not a key-exchange message ({exc})") from None
    return answer, Channel(shared_key, app_side=False)
