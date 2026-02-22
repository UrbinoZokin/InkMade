from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from .provisioning import ProvisioningService


class ProvisioningRequestHandler(BaseHTTPRequestHandler):
    service_factory: Callable[[], ProvisioningService] = ProvisioningService
    api_token: str | None = None

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self) -> bool:
        if not self.api_token:
            return True
        provided = self.headers.get("X-Setup-Token", "")
        return provided == self.api_token

    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length else b"{}"
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_GET(self) -> None:  # noqa: N802
        if not self._check_auth():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        if self.path != "/status":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return

        service = self.service_factory()
        self._send_json(HTTPStatus.OK, service.get_status())

    def do_POST(self) -> None:  # noqa: N802
        if not self._check_auth():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        service = self.service_factory()
        try:
            data = self._read_json()
            if self.path == "/wifi":
                result = service.set_wifi(data.get("ssid", ""), data.get("password", ""))
            elif self.path == "/icloud":
                service.set_icloud_credentials(data.get("username", ""), data.get("app_password", ""))
                result = {"ok": True}
            elif self.path == "/google-paths":
                service.set_google_oauth_paths(
                    credentials_json=data.get("credentials_json"),
                    token_json=data.get("token_json"),
                )
                result = {"ok": True}
            elif self.path == "/settings":
                service.update_settings(data)
                result = {"ok": True}
            elif self.path == "/apply":
                result = service.apply(restart_service=bool(data.get("restart_service", True)))
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return

        self._send_json(HTTPStatus.OK, result)


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    token = os.environ.get("PROVISIONING_API_TOKEN")
    ProvisioningRequestHandler.api_token = token
    server = ThreadingHTTPServer((host, port), ProvisioningRequestHandler)
    print(f"InkyCal provisioning API listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server(
        host=os.environ.get("PROVISIONING_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("PROVISIONING_API_PORT", "8765")),
    )
