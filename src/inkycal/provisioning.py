from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict

import yaml

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass
class ProvisioningPaths:
    config_path: Path = Path("/opt/inkycal/config.yaml")
    env_path: Path = Path("/opt/inkycal/.env")


class ProvisioningService:
    """Provisioning helpers consumed by a BLE/mobile setup transport."""

    def __init__(self, paths: ProvisioningPaths | None = None, runner: CommandRunner | None = None) -> None:
        self.paths = paths or ProvisioningPaths()
        self.runner = runner or self._run_command

    def get_status(self) -> Dict[str, Any]:
        return {
            "wifi": self._get_wifi_status(),
            "config": self._load_config(),
            "env": {
                "has_icloud_username": bool(self._load_env().get("ICLOUD_USERNAME")),
                "has_icloud_app_password": bool(self._load_env().get("ICLOUD_APP_PASSWORD")),
                "has_google_credentials_path": bool(self._load_env().get("GOOGLE_CREDENTIALS_JSON")),
                "has_google_token_path": bool(self._load_env().get("GOOGLE_TOKEN_JSON")),
            },
        }

    def set_wifi(self, ssid: str, password: str) -> Dict[str, Any]:
        ssid = ssid.strip()
        if not ssid:
            raise ValueError("Wi-Fi SSID is required.")

        if shutil.which("nmcli") is None:
            return {"connected": False, "error": "nmcli not installed"}

        cmd = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            cmd.extend(["password", password])

        result = self.runner(cmd)
        ok = result.returncode == 0
        return {
            "connected": ok,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }

    def set_icloud_credentials(self, username: str, app_password: str) -> None:
        self._update_env(
            {
                "ICLOUD_USERNAME": username.strip(),
                "ICLOUD_APP_PASSWORD": app_password.strip(),
            }
        )

    def set_google_oauth_paths(self, credentials_json: str | None = None, token_json: str | None = None) -> None:
        updates: Dict[str, str] = {}
        if credentials_json:
            updates["GOOGLE_CREDENTIALS_JSON"] = credentials_json
        if token_json:
            updates["GOOGLE_TOKEN_JSON"] = token_json
        if updates:
            self._update_env(updates)

    def update_settings(self, settings: Dict[str, Any]) -> None:
        config = self._load_config()

        if "timezone" in settings:
            config["timezone"] = settings["timezone"]
        if "poll_interval_minutes" in settings:
            config["poll_interval_minutes"] = int(settings["poll_interval_minutes"])

        sleep = config.setdefault("sleep", {})
        if "sleep" in settings and isinstance(settings["sleep"], dict):
            sleep_updates = settings["sleep"]
            for key in ("enabled", "start", "end", "banner_text"):
                if key in sleep_updates:
                    sleep[key] = sleep_updates[key]

        display = config.setdefault("display", {})
        if "display" in settings and isinstance(settings["display"], dict):
            display_updates = settings["display"]
            for key in ("rotate_degrees", "saturation", "border"):
                if key in display_updates:
                    display[key] = display_updates[key]

        self._write_config(config)

    def apply(self, restart_service: bool = True) -> Dict[str, Any]:
        if not restart_service:
            return {"restarted": False}

        if shutil.which("systemctl") is None:
            return {"restarted": False, "error": "systemctl not available"}

        result = self.runner(["systemctl", "restart", "inkycal.timer", "inkycal-deepclean.timer"])
        return {
            "restarted": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }

    def _load_config(self) -> Dict[str, Any]:
        if not self.paths.config_path.exists():
            return {}
        return yaml.safe_load(self.paths.config_path.read_text(encoding="utf-8")) or {}

    def _write_config(self, data: Dict[str, Any]) -> None:
        self.paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def _load_env(self) -> Dict[str, str]:
        values: Dict[str, str] = {}
        if not self.paths.env_path.exists():
            return values
        for raw_line in self.paths.env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
        return values

    def _update_env(self, updates: Dict[str, str]) -> None:
        env = self._load_env()
        env.update(updates)
        lines = [f'{key}="{value}"' for key, value in sorted(env.items())]
        self.paths.env_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _get_wifi_status(self) -> Dict[str, Any]:
        if shutil.which("nmcli") is None:
            return {"connected": False, "error": "nmcli not installed"}

        result = self.runner(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"])
        if result.returncode != 0:
            return {"connected": False, "error": result.stderr.strip()}

        for line in result.stdout.splitlines():
            if line.startswith("yes:"):
                return {"connected": True, "ssid": line.split(":", 1)[1]}
        return {"connected": False}

    @staticmethod
    def _run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, check=False, text=True, capture_output=True)


def parse_payload(payload: str) -> Dict[str, Any]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON payload: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON payload must be an object.")
    return data
