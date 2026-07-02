import os
from types import SimpleNamespace

from inkycal import buttons


def test_app_owner_ids_matches_directory_stat(tmp_path):
    st = os.stat(tmp_path)

    uid, gid = buttons._app_owner_ids(str(tmp_path))

    assert (uid, gid) == (st.st_uid, st.st_gid)


def test_app_owner_groups_falls_back_to_gid_on_lookup_failure(monkeypatch):
    monkeypatch.setattr(buttons.pwd, "getpwuid", lambda uid: (_ for _ in ()).throw(KeyError(uid)))

    groups = buttons._app_owner_groups(uid=999999, gid=42)

    assert groups == [42]


def test_spawn_env_merges_dotenv_without_mutating_os_environ(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('ICLOUD_USERNAME="me@example.com"\n', encoding="utf-8")
    monkeypatch.delenv("ICLOUD_USERNAME", raising=False)

    env = buttons._spawn_env(str(tmp_path))

    assert env["ICLOUD_USERNAME"] == "me@example.com"
    assert "ICLOUD_USERNAME" not in os.environ


def test_spawn_env_drops_bare_keys_dotenv_values_maps_to_none(tmp_path):
    (tmp_path / ".env").write_text("BARE_VAR\nGOOGLE_TOKEN_JSON=/tmp/token.json\n", encoding="utf-8")

    env = buttons._spawn_env(str(tmp_path))

    assert "BARE_VAR" not in env
    assert env["GOOGLE_TOKEN_JSON"] == "/tmp/token.json"
    assert all(v is not None for v in env.values())


def test_run_main_drops_privileges_and_forces_refresh(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        buttons.subprocess, "run", lambda *a, **kw: calls.append((a, kw)) or SimpleNamespace(returncode=0)
    )
    monkeypatch.setattr(buttons, "_spawn_env", lambda app_dir: {"FAKE": "1"})
    monkeypatch.setattr(buttons, "_app_owner_groups", lambda uid, gid: [gid, 999])

    app_dir = str(tmp_path)
    buttons._run_main(app_dir, "/opt/inkycal/config.yaml", "/var/lib/inkycal/state.json", toggle_view=False)

    (cmd,), kwargs = calls[0]
    assert cmd[-1] == "--force"
    assert "--toggle-view" not in cmd
    assert kwargs["cwd"] == app_dir
    assert kwargs["env"] == {"FAKE": "1"}
    assert kwargs["check"] is False
    # extra_groups is required, or setgroups() is never called and the child
    # keeps the daemon's (root's) supplementary groups instead of dropping to
    # the app user's real ones.
    assert kwargs["extra_groups"] == [kwargs["group"], 999]


def test_run_main_appends_toggle_view_flag(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        buttons.subprocess, "run", lambda *a, **kw: calls.append((a, kw)) or SimpleNamespace(returncode=0)
    )
    monkeypatch.setattr(buttons, "_spawn_env", lambda app_dir: {})
    monkeypatch.setattr(buttons, "_app_owner_groups", lambda uid, gid: [gid])

    buttons._run_main(str(tmp_path), "config.yaml", "state.json", toggle_view=True)

    (cmd,), _kwargs = calls[0]
    assert cmd[-2:] == ["--force", "--toggle-view"]


def test_run_main_reports_nonzero_exit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(buttons.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    monkeypatch.setattr(buttons, "_spawn_env", lambda app_dir: {})
    monkeypatch.setattr(buttons, "_app_owner_groups", lambda uid, gid: [gid])

    buttons._run_main(str(tmp_path), "config.yaml", "state.json", toggle_view=False)

    assert "exited with code 1" in capsys.readouterr().out


def test_trigger_force_update_writes_flag_file_and_starts_service(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        buttons.subprocess, "run", lambda *a, **kw: calls.append((a, kw)) or SimpleNamespace(returncode=0)
    )

    state_path = str(tmp_path / "state.json")
    buttons._trigger_force_update(state_path)

    (cmd,), kwargs = calls[0]
    # No --setenv=: systemctl start does not support it (only systemd-run does).
    assert cmd == ["systemctl", "start", "--no-block", "inkycal-update.service"]
    assert kwargs["check"] is False
    assert (tmp_path / buttons.FORCE_UPDATE_FLAG_NAME).exists()
