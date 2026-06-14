"""InkyCal provisioning agent.

Runs on the Pi alongside the display program. It exposes two transports so
the companion app can configure the device:

  * Bluetooth LE  -- always available; used to set up WiFi the first time.
  * WiFi / HTTP   -- available once the Pi is on the network; faster, and
                     used to deliver the Google OAuth token.

The agent re-checks WiFi periodically and (re)starts the mDNS advertisement
when the Pi comes online -- e.g. right after the app provisions WiFi over
Bluetooth -- so the app can seamlessly switch to the WiFi path.
"""
from __future__ import annotations

import signal
import threading
import time

from . import wifi
from .ble import BleProvisioner
from .httpserver import info_payload, serve
from .mdns import MdnsAdvertiser
from .protocol import HTTP_PORT


def _device_id() -> str:
    return info_payload().get("id", "pi")


def run() -> int:
    print("== InkyCal provisioning agent ==")
    device_id = _device_id()

    # WiFi/HTTP transport is cheap to always run.
    serve(HTTP_PORT)

    # BLE transport for first-time setup (no-op if BlueZ/bluezero missing).
    ble = BleProvisioner(info_provider=info_payload)
    ble.start()

    # mDNS advertisement follows WiFi connectivity.
    mdns = MdnsAdvertiser(port=HTTP_PORT, device_id=device_id)
    advertised_ip: str | None = None

    stop = threading.Event()

    def _shutdown(*_args) -> None:
        print("\n[agent] shutting down")
        stop.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while not stop.is_set():
        st = wifi.status()
        ip = st["ip"] if st["connected"] else None
        if ip != advertised_ip:
            mdns.stop()
            if ip:
                mdns.start(ip)
            advertised_ip = ip
        stop.wait(15)

    mdns.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
