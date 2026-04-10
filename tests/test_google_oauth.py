from pathlib import Path

from inkycal import calendar_google


def test_google_oauth_private_ip_falls_back_to_loopback(monkeypatch, tmp_path):
    creds_path = tmp_path / "credentials.json"
    token_path = tmp_path / "token.json"
    creds_path.write_text("{}", encoding="utf-8")

    class FakeCreds:
        def to_json(self):
            return '{"token":"fake"}'

    class FakeFlow:
        def run_local_server(self, **kwargs):
            self.kwargs = kwargs
            return FakeCreds()

    fake_flow = FakeFlow()

    monkeypatch.setenv("GOOGLE_OAUTH_HOST", "192.168.1.13")
    monkeypatch.setenv("GOOGLE_OAUTH_BIND_ADDR", "192.168.1.13")
    monkeypatch.setenv("GOOGLE_OAUTH_PORT", "48025")
    monkeypatch.setattr(
        calendar_google.InstalledAppFlow,
        "from_client_secrets_file",
        lambda *_args, **_kwargs: fake_flow,
    )

    calendar_google._get_creds(str(creds_path), str(token_path))

    assert fake_flow.kwargs["host"] == "127.0.0.1"
    assert fake_flow.kwargs["bind_addr"] == "127.0.0.1"
    assert fake_flow.kwargs["port"] == 48025
    assert Path(token_path).exists()
