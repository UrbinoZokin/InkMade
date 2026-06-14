import json

import pytest

from inkycal.provisioning import tokenstore


VALID_TOKEN = {
    "token": "ya29.short-lived",
    "refresh_token": "1//long-lived-refresh",
    "client_id": "abc.apps.googleusercontent.com",
    "client_secret": "secret",
    "scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
}


def test_validate_token_accepts_valid():
    data = tokenstore.validate_token(json.dumps(VALID_TOKEN))
    assert data["refresh_token"] == "1//long-lived-refresh"


def test_validate_token_rejects_non_json():
    with pytest.raises(ValueError):
        tokenstore.validate_token("not json")


def test_validate_token_rejects_missing_fields():
    incomplete = {"token": "x"}
    with pytest.raises(ValueError):
        tokenstore.validate_token(json.dumps(incomplete))


def test_validate_token_rejects_blank_refresh():
    token = dict(VALID_TOKEN, refresh_token="")
    with pytest.raises(ValueError):
        tokenstore.validate_token(json.dumps(token))


def test_save_token_writes_atomically(tmp_path):
    dest = tmp_path / "secrets" / "google_token.json"
    written = tokenstore.save_token(json.dumps(VALID_TOKEN), path=str(dest))
    assert written == str(dest)
    on_disk = json.loads(dest.read_text(encoding="utf-8"))
    assert on_disk["refresh_token"] == VALID_TOKEN["refresh_token"]


def test_save_token_rejects_bad_payload(tmp_path):
    dest = tmp_path / "google_token.json"
    with pytest.raises(ValueError):
        tokenstore.save_token("{}", path=str(dest))
    assert not dest.exists()


def test_token_present_reflects_file(tmp_path, monkeypatch):
    dest = tmp_path / "google_token.json"
    monkeypatch.setenv("GOOGLE_TOKEN_JSON", str(dest))
    assert tokenstore.token_present() is False
    tokenstore.save_token(json.dumps(VALID_TOKEN), path=str(dest))
    assert tokenstore.token_present() is True
