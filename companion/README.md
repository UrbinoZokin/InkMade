# InkyCal Companion App

A small desktop app that finds your InkyCal Raspberry Pi, gets it onto WiFi
(over Bluetooth, the first time), and runs the **Google Calendar
authorization** for you — then delivers the resulting token to the Pi so your
events show up on the display. No keyboard or monitor on the Pi required.

## What it does

1. **Finds your InkyCal.** It looks on your WiFi first (via mDNS). If the Pi
   isn't online yet, it falls back to **Bluetooth**.
2. **Sets up WiFi over Bluetooth** (only if needed). You type your home WiFi
   name and password; the app sends them to the Pi over BLE, the Pi joins the
   network, and the app switches to the faster WiFi connection.
3. **Signs in with Google.** It opens your browser, you approve read-only
   calendar access, and the token is created on *your* machine.
4. **Delivers the token to the Pi** over WiFi. The display refreshes shortly
   after.

Connection priority is **WiFi first, then Bluetooth**, exactly as required —
Bluetooth is used for the initial WiFi setup and as a fallback.

## One-click install / executable

The easiest path is a packaged executable (no Python needed by the end user):

```bash
cd companion
python -m pip install -r requirements.txt pyinstaller
python build_executable.py
```

This produces `dist/InkyCal-Setup` (`.exe` on Windows). Double-click it to run.
Build it once per operating system you want to support — PyInstaller does not
cross-compile.

### Run from source (developers)

```bash
cd companion
python -m pip install -r requirements.txt
python -m inkycal_companion            # GUI
python -m inkycal_companion --cli --help   # headless / scripted
```

## Before you start: Google credentials

You need an OAuth **client-secrets** file (one-time, from Google Cloud Console):

1. Create a project at <https://console.cloud.google.com/>.
2. Enable the **Google Calendar API**.
3. Under *APIs & Services → Credentials*, create an **OAuth client ID** of type
   **Desktop app** and download the JSON.
4. In the app, click *Browse…* and select that JSON, then *Sign in*.

The downloaded JSON identifies the app, not your account — you still approve
access in the browser, and the token grants **read-only** calendar access.

## CLI usage

```bash
# Pi already on WiFi (discovered automatically):
inkycal-companion --cli --credentials client_secret.json

# Pi offline — set up WiFi over Bluetooth in one shot:
inkycal-companion --cli --credentials client_secret.json \
  --ssid "MyHomeWiFi" --psk "wifi-password"

# Skip discovery and target a known IP:
inkycal-companion --cli --credentials client_secret.json --host 192.168.1.50
```

## Platform notes

- **Bluetooth** uses `bleak`, which works on Windows 10+, macOS 11+, and Linux
  (BlueZ). On macOS the OS will prompt for Bluetooth permission the first time.
- **mDNS** discovery uses `zeroconf`; your computer and the Pi must be on the
  same network/subnet.
- If discovery is blocked by your network, use `--host <pi-ip>`.

## Pairing token (optional)

If the Pi sets `INKYCAL_PAIR_TOKEN` in its `.env`, pass the same value with
`--pairing-token` (CLI) so the token upload is authorized.
