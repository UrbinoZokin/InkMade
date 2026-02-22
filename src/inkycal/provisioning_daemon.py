"""BLE provisioning daemon skeleton for InkyCal.

This module intentionally focuses on orchestration and payload validation.
A production implementation should wire the GATT callbacks to BlueZ D-Bus.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CONFIG_PATH = Path("/opt/inkycal/config.yaml")
ENV_PATH = Path("/opt/inkycal/.env")


@dataclass
class ProvisioningSettings:
    timezone: str
    sleep_start: str
    sleep_end: str
    portrait_rotation: int
    refresh_minutes: int
    deep_clean_day: str
    deep_clean_time: str


class ProvisioningError(RuntimeError):
    """Raised when BLE provisioning input is invalid or an operation fails."""


class ProvisioningDaemon:
    """High-level BLE provisioning flow.

    Replace `on_*` methods with GATT characteristic handlers in BlueZ D-Bus.
    """

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self.state = "idle"

    def on_wifi_config(self, raw_payload: str) -> dict[str, Any]:
        payload = self._parse_json(raw_payload)
        ssid = payload.get("ssid", "").strip()
        password = payload.get("password", "")
        country = payload.get("country", "US").strip()
        if not ssid:
            raise ProvisioningError("Wi-Fi SSID is required")
        if len(password) < 8:
            raise ProvisioningError("Wi-Fi password must be at least 8 chars")

        self.state = "wifi_connecting"
        self._configure_wifi(ssid=ssid, password=password, country=country)
        self.state = "wifi_connected"
        return {"connected": True}

    def on_google_oauth_code(self, raw_payload: str) -> None:
        payload = self._parse_json(raw_payload)
        code = payload.get("code", "").strip()
        state = payload.get("state", "").strip()
        if not code or not state:
            raise ProvisioningError("Google OAuth code + state are required")

        # TODO: Validate state, exchange code for token using PKCE,
        # then persist token securely in /opt/inkycal/google_token.json.
        self.state = "icloud_pending"

    def on_icloud_config(self, raw_payload: str) -> None:
        payload = self._parse_json(raw_payload)
        username = payload.get("username", "").strip()
        app_password = payload.get("app_password", "").strip()
        if not username or not app_password:
            raise ProvisioningError("iCloud username and app_password are required")

        self._write_env({"ICAL_USER": username, "ICAL_PASS": app_password})
        self.state = "settings_pending"

    def on_settings(self, raw_payload: str) -> None:
        payload = self._parse_json(raw_payload)
        settings = ProvisioningSettings(
            timezone=payload["timezone"],
            sleep_start=payload["sleep_start"],
            sleep_end=payload["sleep_end"],
            portrait_rotation=int(payload["portrait_rotation"]),
            refresh_minutes=int(payload["refresh_minutes"]),
            deep_clean_day=payload["deep_clean_day"],
            deep_clean_time=payload["deep_clean_time"],
        )
        self._write_config(settings)
        self.state = "applying_changes"

    def on_apply(self) -> None:
        self._run(["systemctl", "restart", "inkycal.service"])
        self._run(["systemctl", "restart", "inkycal.timer"])
        self._run(["systemctl", "restart", "inkycal-deepclean.timer"])
        self.state = "done"

    def _configure_wifi(self, *, ssid: str, password: str, country: str) -> None:
        self._run(["nmcli", "radio", "wifi", "on"])
        self._run(
            [
                "nmcli",
                "device",
                "wifi",
                "connect",
                ssid,
                "password",
                password,
                "ifname",
                "wlan0",
                "--",
                "wifi-sec.key-mgmt",
                "wpa-psk",
                "wifi.country",
                country,
            ]
        )

    def _write_config(self, settings: ProvisioningSettings) -> None:
        lines = [
            f"timezone: {settings.timezone}",
            f"sleep_start: '{settings.sleep_start}'",
            f"sleep_end: '{settings.sleep_end}'",
            f"portrait_rotation: {settings.portrait_rotation}",
            f"refresh_minutes: {settings.refresh_minutes}",
            f"deep_clean_day: {settings.deep_clean_day}",
            f"deep_clean_time: '{settings.deep_clean_time}'",
            "",
        ]
        if self.dry_run:
            print("[dry-run] write config:")
            print("\n".join(lines))
            return
        CONFIG_PATH.write_text("\n".join(lines), encoding="utf-8")

    def _write_env(self, values: dict[str, str]) -> None:
        content = "\n".join(f"{k}={v}" for k, v in values.items()) + "\n"
        if self.dry_run:
            print(f"[dry-run] write {ENV_PATH}:\n{content}")
            return
        ENV_PATH.write_text(content, encoding="utf-8")

    def _run(self, cmd: list[str]) -> None:
        if self.dry_run:
            print(f"[dry-run] {' '.join(cmd)}")
            return
        subprocess.run(cmd, check=True)

    @staticmethod
    def _parse_json(raw_payload: str) -> dict[str, Any]:
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ProvisioningError("Invalid JSON payload") from exc
        if not isinstance(payload, dict):
            raise ProvisioningError("Payload must be an object")
        return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="InkyCal BLE provisioning daemon")
    parser.add_argument("--dry-run", action="store_true", help="log actions without writing")
    args = parser.parse_args()

    daemon = ProvisioningDaemon(dry_run=args.dry_run)
    print(f"Provisioning daemon initialized, current state={daemon.state}")
    print("Wire this class to BlueZ D-Bus GATT callbacks for production use.")


if __name__ == "__main__":
    main()
