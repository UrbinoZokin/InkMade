"""The provisioning HTTP API, served for real on localhost.

Every write has to carry the setup code and has to be JSON. The JSON rule is
what keeps web pages out: a page can send a plain-text POST to any address
without asking, but not an application/json one, so a page opened on the same
network can't use the API even with a lucky code.
"""
import json

import pytest
import requests

from inkycal.provisioning import httpserver, wifi
from inkycal.provisioning.protocol import CODE_HEADER
from inkycal.provisioning.session import SetupSession

CODE = "482913"

# Straight to localhost: a proxy configured in the environment would otherwise
# be asked to fetch these.
http = requests.Session()
http.trust_env = False

TOKEN = {
    "token": "ya29.short-lived",
    "refresh_token": "1//long-lived-refresh",
    "client_id": "abc.apps.googleusercontent.com",
    "client_secret": "secret",
}


@pytest.fixture
def token_path(tmp_path, monkeypatch):
    path = tmp_path / "secrets" / "google_token.json"
    monkeypatch.setenv("GOOGLE_TOKEN_JSON", str(path))
    return path


@pytest.fixture
def api(token_path, monkeypatch):
    """A running server for one session. Yields (base_url, session)."""
    monkeypatch.setattr(
        wifi, "status", lambda: {"connected": True, "ssid": "Home", "ip": "192.168.1.50", "hostname": "inkycal"}
    )
    session = SetupSession(CODE, max_wrong=5)
    httpd = httpserver.serve(session, port=0, host="127.0.0.1")
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", session
    finally:
        httpd.shutdown()
        httpd.server_close()


def _post_token(base_url, *, code=CODE, body=None, content_type="application/json"):
    headers = {"Content-Type": content_type}
    if code is not None:
        headers[CODE_HEADER] = code
    data = json.dumps(TOKEN if body is None else body).encode("utf-8")
    return http.post(f"{base_url}/google-token", data=data, headers=headers, timeout=10)


def test_info_is_public_and_says_a_code_is_required(api):
    base_url, _session = api

    resp = http.get(f"{base_url}/info", timeout=10)

    assert resp.status_code == 200
    assert resp.json()["requires_pairing"] is True
    assert resp.json()["ip"] == "192.168.1.50"


def test_no_response_invites_other_websites_in(api):
    base_url, _session = api

    for resp in (http.get(f"{base_url}/info", timeout=10), _post_token(base_url)):
        assert "Access-Control-Allow-Origin" not in resp.headers


def test_the_right_code_delivers_the_token_and_ends_setup_mode(api, token_path):
    base_url, session = api

    resp = _post_token(base_url, code="482 913")

    assert resp.status_code == 200, resp.text
    assert json.loads(token_path.read_text(encoding="utf-8"))["refresh_token"] == TOKEN["refresh_token"]
    assert "path" not in resp.json(), "the response has no business naming where secrets live"
    assert session.ended
    assert session.end_reason == "Google token delivered"


def test_without_the_code_nothing_is_written(api, token_path):
    base_url, session = api

    resp = _post_token(base_url, code=None)

    assert resp.status_code == 401
    assert "setup code" in resp.json()["error"]
    assert not token_path.exists()
    assert session.wrong_codes_left == 5, "a missing code is not a guess"


def test_a_wrong_code_is_refused_and_counted(api, token_path):
    base_url, session = api

    resp = _post_token(base_url, code="000000")

    assert resp.status_code == 401
    assert "4 tries left" in resp.json()["error"]
    assert not token_path.exists()
    assert session.wrong_codes_left == 4


def test_five_wrong_codes_end_setup_mode_for_good(api, token_path):
    base_url, session = api

    statuses = [_post_token(base_url, code=f"00000{i}").status_code for i in range(5)]

    assert statuses == [401, 401, 401, 401, 403]
    assert session.ended
    late = _post_token(base_url)  # the right code, too late
    assert late.status_code == 403
    assert "Press button C" in late.json()["error"]
    assert not token_path.exists()


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", ""])
def test_only_json_is_accepted_even_with_the_code(api, token_path, content_type):
    """The POSTs a web page can send without the browser asking first."""
    base_url, session = api

    resp = _post_token(base_url, content_type=content_type)

    assert resp.status_code == 415
    assert not token_path.exists()
    assert session.wrong_codes_left == 5


def test_a_bad_token_is_rejected_without_ending_setup_mode(api, token_path):
    base_url, session = api

    resp = _post_token(base_url, body={"token": "no refresh token"})

    assert resp.status_code == 400
    assert not token_path.exists()
    assert not session.ended


def test_wifi_needs_the_code_too(api, monkeypatch):
    base_url, _session = api
    joined = []
    monkeypatch.setattr(wifi, "configure_wifi", lambda ssid, psk: joined.append((ssid, psk)) or (True, "ok"))

    refused = http.post(f"{base_url}/wifi", json={"ssid": "Evil", "psk": "x"}, timeout=10)
    accepted = http.post(
        f"{base_url}/wifi", json={"ssid": "Home", "psk": "secret"}, headers={CODE_HEADER: CODE}, timeout=10
    )

    assert refused.status_code == 401
    assert accepted.status_code == 200
    assert joined == [("Home", "secret")]


def test_unknown_paths_are_not_found(api):
    base_url, _session = api

    assert http.post(f"{base_url}/nope", json={}, headers={CODE_HEADER: CODE}, timeout=10).status_code == 404
    assert http.get(f"{base_url}/nope", timeout=10).status_code == 404
