"""HTTP client for the Pi's WiFi provisioning API.

Everything sent is sealed end to end (setupcrypto.py). The client first runs
the key exchange over /pair, keyed by the setup code, and the code itself is
never sent. An InkyCal without /pair is refused rather than sent anything in
the clear: an app that fell back to plaintext could be talked into it by
whoever wanted to read what it sends.
"""
from __future__ import annotations

import base64
import json
from typing import Optional

import requests

from . import setupcrypto
from .discovery import PiDevice

TOO_OLD = (
    "This InkyCal's software is too old for this app: it can't encrypt what "
    "you send it. Press button D on the InkyCal to update it, then try again."
)


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


class PiClient:
    def __init__(self, device: PiDevice, setup_code: str = "", timeout: float = 15.0):
        self.device = device
        self.setup_code = setup_code
        self.timeout = timeout
        self._pairing: Optional[str] = None
        self._channel: Optional[setupcrypto.Channel] = None

    def info(self) -> dict:
        resp = requests.get(
            f"{self.device.base_url}/info", timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def _pair(self) -> setupcrypto.Channel:
        handshake = setupcrypto.AppHandshake(self.setup_code)
        resp = requests.post(
            f"{self.device.base_url}/pair",
            json={"message": _b64(handshake.message)},
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            raise RuntimeError(TOO_OLD)
        if resp.status_code >= 400:
            raise RuntimeError(_error_text(resp))
        try:
            data = resp.json()
            channel = handshake.finish(base64.b64decode(data["message"]))
            self._pairing = str(data["pairing"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"The InkyCal's answer didn't make sense ({exc}).") from None
        self._channel = channel
        return channel

    def _send_sealed(
        self, path: str, payload: bytes, purpose: bytes, reply_purpose: bytes, timeout: float
    ) -> dict:
        channel = self._channel or self._pair()
        resp = requests.post(
            f"{self.device.base_url}{path}",
            json={"pairing": self._pairing, "sealed": _b64(channel.seal(payload, purpose))},
            timeout=timeout,
        )
        if resp.status_code >= 400:
            # A refused message spends the exchange on the Pi; start afresh next time.
            self._channel = self._pairing = None
            raise RuntimeError(_error_text(resp))
        try:
            reply = channel.open(base64.b64decode(resp.json()["sealed"]), reply_purpose)
            return json.loads(reply)
        except (KeyError, TypeError, ValueError):
            raise RuntimeError(
                "The reply didn't check out: whatever answered may not be your InkyCal."
            ) from None

    def upload_token(self, token_json: str) -> dict:
        return self._send_sealed(
            "/google-token",
            token_json.encode("utf-8"),
            setupcrypto.GOOGLE_TOKEN,
            setupcrypto.GOOGLE_TOKEN_REPLY,
            self.timeout,
        )

    def configure_wifi(self, ssid: str, psk: str) -> dict:
        reply = self._send_sealed(
            "/wifi",
            json.dumps({"ssid": ssid, "psk": psk}).encode("utf-8"),
            setupcrypto.WIFI,
            setupcrypto.WIFI_REPLY,
            max(self.timeout, 60),
        )
        if not reply.get("ok"):
            raise RuntimeError(reply.get("message") or "The InkyCal couldn't join that network.")
        return reply


def reachable(device: PiDevice, timeout: float = 4.0) -> Optional[dict]:
    """Return the device /info if it answers, else None."""
    try:
        resp = requests.get(f"{device.base_url}/info", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


def _error_text(resp: "requests.Response") -> str:
    try:
        return resp.json().get("error", resp.text)
    except ValueError:
        return resp.text or f"HTTP {resp.status_code}"
