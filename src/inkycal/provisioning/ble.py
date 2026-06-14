"""BLE GATT peripheral used for first-time WiFi provisioning.

When the Pi has no WiFi yet, the companion app talks to it over Bluetooth
Low Energy. The app writes the SSID and passphrase, then writes "connect"
to the command characteristic. We join the network with nmcli and publish
the result (including the new IP) on the status characteristic so the app
can switch over to the faster WiFi/HTTP path.

Implemented with ``bluezero`` (BlueZ over D-Bus). bluezero is Linux-only,
which is exactly where this runs (the Pi). The module degrades gracefully:
if bluezero/BlueZ is unavailable it logs and returns without crashing the
agent, so the WiFi path still works.
"""
from __future__ import annotations

import json
import threading
from typing import Callable, Optional

from . import wifi
from .protocol import (
    BLE_LOCAL_NAME,
    BLE_SERVICE_UUID,
    BLE_CHAR_SSID_UUID,
    BLE_CHAR_PSK_UUID,
    BLE_CHAR_COMMAND_UUID,
    BLE_CHAR_STATUS_UUID,
    BLE_CHAR_INFO_UUID,
    CMD_CONNECT,
    STATUS_IDLE,
    STATUS_CONNECTING,
    STATUS_CONNECTED,
    STATUS_FAILED,
)


def _encode(text: str) -> list[int]:
    return list(text.encode("utf-8"))


def _decode(value) -> str:
    try:
        return bytes(value).decode("utf-8", errors="replace").strip()
    except (TypeError, ValueError):
        return ""


class BleProvisioner:
    """GATT peripheral that accepts WiFi credentials and applies them."""

    def __init__(self, info_provider: Callable[[], dict]) -> None:
        self._info_provider = info_provider
        self._ssid = ""
        self._psk = ""
        self._state = STATUS_IDLE
        self._message = ""
        self._peripheral = None
        self._status_char = None

    # --- characteristic callbacks ---
    def _on_write_ssid(self, value, options) -> None:
        self._ssid = _decode(value)
        print(f"[ble] received SSID ({len(self._ssid)} chars)")

    def _on_write_psk(self, value, options) -> None:
        self._psk = _decode(value)
        print(f"[ble] received passphrase ({len(self._psk)} chars)")

    def _on_write_command(self, value, options) -> None:
        cmd = _decode(value).lower()
        print(f"[ble] command: {cmd}")
        if cmd == CMD_CONNECT:
            # Run the (blocking) nmcli join off the D-Bus callback thread.
            threading.Thread(target=self._do_connect, daemon=True).start()

    def _read_status(self) -> list[int]:
        return _encode(self._status_json())

    def _read_info(self) -> list[int]:
        try:
            return _encode(json.dumps(self._info_provider()))
        except Exception:  # never let a read crash the stack
            return _encode("{}")

    # --- connection logic ---
    def _status_json(self) -> str:
        st = wifi.status()
        return json.dumps(
            {
                "state": self._state,
                "message": self._message,
                "wifi": "connected" if st["connected"] else "disconnected",
                "ssid": st["ssid"],
                "ip": st["ip"],
            }
        )

    def _set_state(self, state: str, message: str = "") -> None:
        self._state = state
        self._message = message
        self._notify_status()

    def _notify_status(self) -> None:
        if self._status_char is not None:
            try:
                self._status_char.set_value(_encode(self._status_json()))
            except Exception as exc:  # notify is best-effort
                print(f"[ble] status notify failed: {exc}")

    def _do_connect(self) -> None:
        self._set_state(STATUS_CONNECTING, f"Joining {self._ssid}")
        ok, message = wifi.configure_wifi(self._ssid, self._psk)
        if ok:
            self._set_state(STATUS_CONNECTED, message)
        else:
            self._set_state(STATUS_FAILED, message)

    # --- lifecycle ---
    def start(self) -> bool:
        """Build and publish the GATT peripheral. Returns False if BLE is unusable.

        Never raises: any BlueZ/D-Bus failure is logged and reported via the
        return value so the rest of the agent (HTTP/mDNS) keeps running.
        """
        try:
            from bluezero import adapter, peripheral
        except ImportError:
            print("[ble] bluezero not installed; BLE provisioning disabled")
            return False

        try:
            adapters = list(adapter.Adapter.available())
        except Exception as exc:  # dbus error querying BlueZ
            print(f"[ble] could not query Bluetooth adapters: {exc}")
            return False
        if not adapters:
            print("[ble] no Bluetooth adapter available")
            return False

        dongle = adapters[0]
        adapter_address = dongle.address

        # The adapter must be powered on, or advertising fails with
        # 'org.bluez.Error.Failed: Not Powered'. Power it on ourselves so the
        # agent is self-healing after a reboot or rfkill toggle.
        try:
            if not dongle.powered:
                print("[ble] adapter is off; powering it on")
                dongle.powered = True
        except Exception as exc:
            print(f"[ble] could not power on the adapter: {exc}")

        try:
            self._peripheral = peripheral.Peripheral(
                adapter_address, local_name=BLE_LOCAL_NAME
            )
            self._peripheral.add_service(srv_id=1, uuid=BLE_SERVICE_UUID, primary=True)

            self._peripheral.add_characteristic(
                srv_id=1, chr_id=1, uuid=BLE_CHAR_SSID_UUID,
                value=[], notifying=False, flags=["write", "write-without-response"],
                write_callback=self._on_write_ssid,
            )
            self._peripheral.add_characteristic(
                srv_id=1, chr_id=2, uuid=BLE_CHAR_PSK_UUID,
                value=[], notifying=False, flags=["write", "write-without-response"],
                write_callback=self._on_write_psk,
            )
            self._peripheral.add_characteristic(
                srv_id=1, chr_id=3, uuid=BLE_CHAR_COMMAND_UUID,
                value=[], notifying=False, flags=["write"],
                write_callback=self._on_write_command,
            )
            self._peripheral.add_characteristic(
                srv_id=1, chr_id=4, uuid=BLE_CHAR_STATUS_UUID,
                value=_encode(self._status_json()), notifying=False,
                flags=["read", "notify"], read_callback=self._read_status,
            )
            self._peripheral.add_characteristic(
                srv_id=1, chr_id=5, uuid=BLE_CHAR_INFO_UUID,
                value=[], notifying=False, flags=["read"],
                read_callback=self._read_info,
            )
        except Exception as exc:
            print(f"[ble] failed to build GATT peripheral: {exc}")
            return False

        # Keep a handle to the status characteristic for notifications.
        try:
            self._status_char = self._peripheral.characteristics[3]
        except (IndexError, AttributeError):
            self._status_char = None

        print(f"[ble] advertising '{BLE_LOCAL_NAME}' (service {BLE_SERVICE_UUID})")
        # publish() blocks running the GLib mainloop, so run it in a thread.
        threading.Thread(target=self._publish, name="inkycal-ble", daemon=True).start()
        return True

    def _publish(self) -> None:
        """Run bluezero's blocking publish loop, logging instead of crashing."""
        try:
            self._peripheral.publish()
        except Exception as exc:
            print(f"[ble] BLE advertising stopped: {exc}")
