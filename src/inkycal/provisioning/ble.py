"""BLE GATT peripheral used for first-time WiFi provisioning.

When the Pi has no WiFi yet, the companion app talks to it over Bluetooth
Low Energy:

  1. The app writes its half of the key exchange (setupcrypto.py) to the
     pair characteristic, and reads the Pi's half back from it.
  2. It writes the SSID and passphrase, sealed with the key from that
     exchange, to the wifi characteristic. We join the network with nmcli
     and publish the result (including the new IP) on the status
     characteristic so the app can switch over to the faster WiFi/HTTP path.

Neither the setup code on the panel nor the WiFi passphrase ever goes over
the air in the clear: the code never goes at all. A sealed message that
won't open is a wrong code, and counts against the setup session.

Every value written is framed with a 2-byte big-endian length. A value longer
than one Bluetooth packet reaches us as several writes, each with its offset,
and a sealed message only opens whole -- opening a piece would count as a
wrong code.

Only advertised while setup mode is on: the agent that runs this exits when
the session ends, and BlueZ drops the advertisement with it.

Implemented with ``bluezero`` (BlueZ over D-Bus). bluezero is Linux-only,
which is exactly where this runs (the Pi). The module degrades gracefully:
if bluezero/BlueZ is unavailable it logs and returns without crashing the
agent, so the WiFi path still works.
"""
from __future__ import annotations

import json
import threading
from typing import Callable, Optional

from . import setupcrypto, wifi
from .protocol import (
    BLE_LOCAL_NAME,
    BLE_SERVICE_UUID,
    BLE_CHAR_STATUS_UUID,
    BLE_CHAR_INFO_UUID,
    BLE_CHAR_PAIR_UUID,
    BLE_CHAR_WIFI_UUID,
    STATUS_IDLE,
    STATUS_CONNECTING,
    STATUS_CONNECTED,
    STATUS_FAILED,
)
from .session import CLOSED, OK, SessionClosed, SetupSession, refusal


def _encode(text: str) -> list[int]:
    return list(text.encode("utf-8"))


def _offset(options) -> int:
    try:
        return int((options or {}).get("offset", 0) or 0)
    except (TypeError, ValueError):
        return 0


class _Reassembly:
    """Puts a framed value back together from however many writes it came in."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def add(self, value, options) -> Optional[bytes]:
        """Take one write. Returns the whole value once all of it is here."""
        offset = _offset(options)
        if offset == 0:
            self._buffer = bytearray()
        elif offset != len(self._buffer):
            self._buffer = bytearray()  # a piece out of place: wait for a fresh start
            return None
        self._buffer.extend(bytes(value))
        if len(self._buffer) < 2:
            return None
        size = int.from_bytes(self._buffer[:2], "big")
        if len(self._buffer) < 2 + size:
            return None
        whole = bytes(self._buffer[2:2 + size])
        self._buffer = bytearray()
        return whole


class BleProvisioner:
    """GATT peripheral that accepts sealed WiFi credentials and applies them."""

    def __init__(self, info_provider: Callable[[], dict], session: SetupSession) -> None:
        self._info_provider = info_provider
        self._session = session
        self._pair_in = _Reassembly()
        self._wifi_in = _Reassembly()
        self._pairing: Optional[str] = None
        self._answer = b""
        self._state = STATUS_IDLE
        self._message = ""
        self._peripheral = None
        self._status_char = None

    # --- characteristic callbacks ---
    def _on_write_pair(self, value, options) -> None:
        message = self._pair_in.add(value, options)
        if message is None:
            return
        self._pairing, self._answer = None, b""
        try:
            self._pairing, self._answer = self._session.pair(message)
        except setupcrypto.BadHandshake as exc:
            print(f"[ble] key exchange refused: {exc}")
            self._set_state(STATUS_FAILED, "That wasn't a setup key exchange. Start again.")
            return
        except SessionClosed:
            self._set_state(STATUS_FAILED, refusal(CLOSED, self._session))
            return
        print("[ble] key exchange answered")

    def _read_pair(self, options) -> list[int]:
        return list(self._answer[_offset(options):])

    def _on_write_wifi(self, value, options) -> None:
        sealed = self._wifi_in.add(value, options)
        if sealed is None:
            return
        # An exchange carries one message: a retry starts a fresh exchange.
        pairing, self._pairing = self._pairing, None
        verdict, plaintext, _channel = self._session.open(pairing, sealed, setupcrypto.WIFI)
        if verdict != OK:
            print(f"[ble] WiFi settings refused: setup code {verdict}")
            self._set_state(STATUS_FAILED, refusal(verdict, self._session))
            return
        try:
            request = json.loads(plaintext)
            ssid, psk = str(request["ssid"]), str(request.get("psk", ""))
        except (ValueError, KeyError, TypeError):
            self._set_state(STATUS_FAILED, "Those weren't WiFi settings.")
            return
        print(f"[ble] received WiFi settings ({len(ssid)}-character network name)")
        # Run the (blocking) nmcli join off the D-Bus callback thread.
        threading.Thread(target=self._do_connect, args=(ssid, psk), daemon=True).start()

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

    def _do_connect(self, ssid: str, psk: str) -> None:
        self._set_state(STATUS_CONNECTING, f"Joining {ssid}")
        ok, message = wifi.configure_wifi(ssid, psk)
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
                srv_id=1, chr_id=1, uuid=BLE_CHAR_STATUS_UUID,
                value=_encode(self._status_json()), notifying=False,
                flags=["read", "notify"], read_callback=self._read_status,
            )
            # Kept for notifications.
            self._status_char = self._peripheral.characteristics[-1]
            self._peripheral.add_characteristic(
                srv_id=1, chr_id=2, uuid=BLE_CHAR_INFO_UUID,
                value=[], notifying=False, flags=["read"],
                read_callback=self._read_info,
            )
            self._peripheral.add_characteristic(
                srv_id=1, chr_id=3, uuid=BLE_CHAR_PAIR_UUID,
                value=[], notifying=False, flags=["read", "write"],
                read_callback=self._read_pair, write_callback=self._on_write_pair,
            )
            self._peripheral.add_characteristic(
                srv_id=1, chr_id=4, uuid=BLE_CHAR_WIFI_UUID,
                value=[], notifying=False, flags=["write"],
                write_callback=self._on_write_wifi,
            )
        except Exception as exc:
            print(f"[ble] failed to build GATT peripheral: {exc}")
            return False

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
