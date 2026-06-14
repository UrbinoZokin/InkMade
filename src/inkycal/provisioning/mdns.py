"""Advertise the provisioning HTTP API over mDNS/Zeroconf.

This is how the companion app finds the Pi on the WiFi network without the
user typing an IP address. Advertising is best-effort: if zeroconf is not
installed or the network is down, the agent keeps running (the BLE path
still works).
"""
from __future__ import annotations

import socket
from typing import Optional

from .protocol import MDNS_SERVICE_TYPE, HTTP_PORT


class MdnsAdvertiser:
    def __init__(self, port: int = HTTP_PORT, device_id: str = "") -> None:
        self.port = port
        self.device_id = device_id or socket.gethostname()
        self._zc = None
        self._info = None

    def start(self, ip: Optional[str]) -> bool:
        try:
            from zeroconf import ServiceInfo, Zeroconf
        except ImportError:
            print("[mdns] zeroconf not installed; skipping advertisement")
            return False
        if not ip:
            print("[mdns] no IP yet; skipping advertisement")
            return False

        name = f"inkycal-{self.device_id}.{MDNS_SERVICE_TYPE}"
        self._info = ServiceInfo(
            MDNS_SERVICE_TYPE,
            name,
            addresses=[socket.inet_aton(ip)],
            port=self.port,
            properties={"id": self.device_id, "api": "/info"},
            server=f"{socket.gethostname()}.local.",
        )
        try:
            self._zc = Zeroconf()
            self._zc.register_service(self._info)
        except OSError as exc:
            print(f"[mdns] could not register service: {exc}")
            self._zc = None
            return False
        print(f"[mdns] advertising {name} at {ip}:{self.port}")
        return True

    def stop(self) -> None:
        if self._zc and self._info:
            try:
                self._zc.unregister_service(self._info)
                self._zc.close()
            except OSError:
                pass
        self._zc = None
        self._info = None
