"""HTTP client for the Pi's WiFi provisioning API."""
from __future__ import annotations

from typing import Optional

import requests

from .discovery import PiDevice


class PiClient:
    def __init__(self, device: PiDevice, pairing_token: str = "", timeout: float = 15.0):
        self.device = device
        self.pairing_token = pairing_token
        self.timeout = timeout

    def _headers(self) -> dict:
        headers = {}
        if self.pairing_token:
            headers["X-Pairing-Token"] = self.pairing_token
        return headers

    def info(self) -> dict:
        resp = requests.get(
            f"{self.device.base_url}/info", timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def upload_token(self, token_json: str) -> dict:
        resp = requests.post(
            f"{self.device.base_url}/google-token",
            data=token_json.encode("utf-8"),
            headers={**self._headers(), "Content-Type": "application/json"},
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(_error_text(resp))
        return resp.json()

    def configure_wifi(self, ssid: str, psk: str) -> dict:
        resp = requests.post(
            f"{self.device.base_url}/wifi",
            json={"ssid": ssid, "psk": psk},
            headers=self._headers(),
            timeout=max(self.timeout, 60),
        )
        if resp.status_code >= 400:
            raise RuntimeError(_error_text(resp))
        return resp.json()


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
