import subprocess

import pytest

from inkycal import updates


def _git(cwd, *args):
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo_with_origin(tmp_path):
    """A checkout on 'main' with a local bare origin it can fetch from."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "seed"
    app = tmp_path / "app"

    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)

    # Seed the origin with one commit on main.
    subprocess.run(["git", "init", str(work)], check=True, capture_output=True)
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "Tester")
    _git(work, "checkout", "-B", "main")
    (work / "marker.txt").write_text("v1\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "v1")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-u", "origin", "main")

    subprocess.run(["git", "clone", str(origin), str(app)], check=True, capture_output=True)
    _git(app, "config", "user.email", "t@example.com")
    _git(app, "config", "user.name", "Tester")

    return {"origin": origin, "seed": work, "app": app}


def test_reports_up_to_date(repo_with_origin):
    status = updates.check_for_update(branch="main", app_dir=str(repo_with_origin["app"]))
    assert status.available is False
    assert status.behind == 0
    assert status.checked is True
    assert status.error == ""


def test_detects_when_behind(repo_with_origin):
    seed = repo_with_origin["seed"]
    (seed / "marker.txt").write_text("v2\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "v2")
    _git(seed, "push", "origin", "main")

    status = updates.check_for_update(branch="main", app_dir=str(repo_with_origin["app"]))
    assert status.available is True
    assert status.behind == 1
    assert status.local != status.remote


def test_bad_app_dir_falls_back_to_running_repo():
    # A bogus app_dir should fall back to the repo this code runs from rather
    # than crash; the call always returns a well-formed status.
    status = updates.check_for_update(branch="main", app_dir="/nonexistent/path/xyz")
    assert isinstance(status.available, bool)


def test_find_repo_dir_returns_none_without_any_checkout(tmp_path, monkeypatch):
    # Neutralize every fallback candidate so none resolve to a real checkout.
    monkeypatch.setattr(updates, "DEFAULT_APP_DIR", str(tmp_path / "nope"))
    fake_file = tmp_path / "pkg" / "inkycal" / "updates.py"
    fake_file.parent.mkdir(parents=True)
    fake_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(updates, "__file__", str(fake_file))

    assert updates.find_repo_dir(app_dir=str(tmp_path / "missing")) is None

    status = updates.check_for_update(branch="main", app_dir=str(tmp_path / "missing"))
    assert status.available is False
    assert status.error == "no git checkout found"
