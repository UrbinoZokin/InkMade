from __future__ import annotations

import subprocess
from pathlib import Path

from inkycal.provisioning import ProvisioningPaths, ProvisioningService, parse_payload


def _completed(cmd: list[str], code: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, code, stdout=stdout, stderr=stderr)


def test_update_settings_merges_with_existing_config(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    config_path.write_text(
        """
timezone: America/Phoenix
poll_interval_minutes: 15
sleep:
  enabled: true
  start: "22:00"
  end: "06:00"
display:
  rotate_degrees: 90
  saturation: 0.0
""".strip()
        + "\n",
        encoding="utf-8",
    )

    service = ProvisioningService(ProvisioningPaths(config_path=config_path, env_path=env_path))
    service.update_settings(
        {
            "timezone": "America/New_York",
            "poll_interval_minutes": 10,
            "sleep": {"start": "21:30", "banner_text": "Sleeping"},
            "display": {"rotate_degrees": 180},
        }
    )

    import yaml

    out = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert out["timezone"] == "America/New_York"
    assert out["poll_interval_minutes"] == 10
    assert out["sleep"]["start"] == "21:30"
    assert out["sleep"]["banner_text"] == "Sleeping"
    assert out["display"]["rotate_degrees"] == 180


def test_set_icloud_credentials_updates_env_file(tmp_path: Path):
    env_path = tmp_path / ".env"
    config_path = tmp_path / "config.yaml"
    service = ProvisioningService(ProvisioningPaths(config_path=config_path, env_path=env_path))

    service.set_icloud_credentials("user@icloud.com", "abcd-1234")

    content = env_path.read_text(encoding="utf-8")
    assert 'ICLOUD_USERNAME="user@icloud.com"' in content
    assert 'ICLOUD_APP_PASSWORD="abcd-1234"' in content


def test_wifi_status_parses_nmcli_active_network(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/nmcli" if name == "nmcli" else None)

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return _completed(cmd, stdout="yes:HomeWiFi\nno:Other\n")

    service = ProvisioningService(ProvisioningPaths(config_path=config_path, env_path=env_path), runner=fake_runner)
    status = service.get_status()

    assert status["wifi"]["connected"] is True
    assert status["wifi"]["ssid"] == "HomeWiFi"


def test_parse_payload_requires_json_object():
    assert parse_payload('{"timezone": "America/Phoenix"}')["timezone"] == "America/Phoenix"

    try:
        parse_payload("[]")
    except ValueError as exc:
        assert "must be an object" in str(exc)
    else:
        raise AssertionError("Expected ValueError for non-object payload")


def test_start_connection_requires_continue_prompt_when_services_active(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/systemctl" if name == "systemctl" else None)

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["systemctl", "is-active"]:
            return _completed(cmd, stdout="active\n")
        return _completed(cmd)

    service = ProvisioningService(ProvisioningPaths(config_path=config_path, env_path=env_path), runner=fake_runner)
    status = service.start_connection()

    assert status["can_connect"] is True
    assert status["prompt_continue"] is True


def test_authorization_code_must_be_confirmed_then_matches(tmp_path: Path, monkeypatch):
    paths = ProvisioningPaths(
        config_path=tmp_path / "config.yaml",
        env_path=tmp_path / ".env",
        pairing_state_path=tmp_path / "pairing_state.json",
    )

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/systemctl" if name == "systemctl" else None)

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["systemctl", "is-active"]:
            return _completed(cmd, stdout="active\n")
        return _completed(cmd)

    service = ProvisioningService(paths, runner=fake_runner)

    try:
        service.create_authorization_code(continue_when_active=False)
    except ValueError as exc:
        assert "Confirmation required" in str(exc)
    else:
        raise AssertionError("Expected ValueError when services are active")

    auth = service.create_authorization_code(continue_when_active=True)
    code = auth["display_authorization_code"]
    assert len(code) == 6
    assert code.isdigit()

    mismatch = service.complete_connection("000000")
    assert mismatch["connected"] is False

    success = service.complete_connection(code)
    assert success["connected"] is True
