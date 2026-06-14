"""Find InkyCal devices on the local WiFi network via mDNS/Zeroconf."""
from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from typing import List, Optional

from .protocol import MDNS_SERVICE_TYPE, HTTP_PORT


@dataclass
class PiDevice:
    name: str
    host: str          # IP address
    port: int
    device_id: str = ""

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def discover(timeout: float = 5.0) -> List[PiDevice]:
    """Browse for ``_inkycal._tcp`` services for ``timeout`` seconds."""
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    except ImportError:
        return []

    found: dict[str, PiDevice] = {}

    class _Listener(ServiceListener):
        def _resolve(self, zc: "Zeroconf", type_: str, name: str) -> None:
            info = zc.get_service_info(type_, name, timeout=2000)
            if not info:
                return
            addresses = info.parsed_addresses() if hasattr(info, "parsed_addresses") else []
            if not addresses and info.addresses:
                addresses = [socket.inet_ntoa(a) for a in info.addresses]
            if not addresses:
                return
            props = {
                (k.decode() if isinstance(k, bytes) else k): (
                    v.decode() if isinstance(v, bytes) else v
                )
                for k, v in (info.properties or {}).items()
            }
            found[name] = PiDevice(
                name=name.replace("." + MDNS_SERVICE_TYPE, ""),
                host=addresses[0],
                port=info.port or HTTP_PORT,
                device_id=props.get("id", ""),
            )

        def add_service(self, zc, type_, name):
            self._resolve(zc, type_, name)

        def update_service(self, zc, type_, name):
            self._resolve(zc, type_, name)

        def remove_service(self, zc, type_, name):
            found.pop(name, None)

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, MDNS_SERVICE_TYPE, _Listener())
        time.sleep(timeout)
    finally:
        zc.close()

    return list(found.values())


def first(timeout: float = 5.0) -> Optional[PiDevice]:
    devices = discover(timeout=timeout)
    return devices[0] if devices else None
