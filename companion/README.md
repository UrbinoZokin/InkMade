# InkyCal Companion App

A small desktop app that finds your InkyCal Raspberry Pi, gets it onto WiFi
(over Bluetooth, the first time), and runs the **Google Calendar
authorization** for you — then delivers the resulting token to the Pi so your
events show up on the display. No keyboard or monitor on the Pi required.

## What it does

0. **You hold down button C on the InkyCal for 3 seconds.** That turns on *setup mode* for 10
   minutes, and the screen shows a one-time **setup code**. The InkyCal only
   listens for the app while setup mode is on, and refuses anything that isn't
   sealed with that code. (One that has no WiFi or Google token yet starts in
   setup mode by itself.)
1. **Finds your InkyCal.** It looks on your WiFi first (via mDNS). If the Pi
   isn't online yet, it falls back to **Bluetooth**. You type in the setup
   code.
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
# Pi already on WiFi (discovered automatically). Asks for the setup code:
inkycal-companion --cli --credentials client_secret.json

# Pi offline — set up WiFi over Bluetooth in one shot:
inkycal-companion --cli --credentials client_secret.json \
  --ssid "MyHomeWiFi" --psk "wifi-password" --setup-code 482913

# Skip discovery and target a known IP:
inkycal-companion --cli --credentials client_secret.json --host 192.168.1.50
```

## Platform notes

- **Bluetooth** uses `bleak`, which works on Windows 10+, macOS 11+, and Linux
  (BlueZ). On macOS the OS will prompt for Bluetooth permission the first time.
- **mDNS** discovery uses `zeroconf`; your computer and the Pi must be on the
  same network/subnet.
- If discovery is blocked by your network, use `--host <pi-ip>`.

## Setup code

Everything the app sends — WiFi over Bluetooth, WiFi or the Google token over
the network — is sealed with a key made from the 6-digit code on the
InkyCal's screen, and only an InkyCal showing that code can open it. The code
itself never leaves your computer: the app and the Pi agree the key with
SPAKE2, a password-authenticated key exchange, so anyone listening sees only
ciphertext and can't even test guesses at the code. The GUI asks for it in
step 1; the CLI takes `--setup-code` (or asks). It is good for one setup
session: 10 minutes after button C was last held, until the Google token
is delivered, or until 5 wrong codes have been tried, whichever comes first.
After that, hold C again for a new code.

The app won't fall back to sending anything in the clear. An InkyCal whose
software predates this says so instead: press button D on it to update it
(over WiFi), then try again.

If the app can't find the InkyCal, check that its screen shows a setup code —
outside setup mode it isn't listening at all.

`INKYCAL_PAIR_TOKEN` (a fixed token in the Pi's `.env`) is no longer used; the
code on the screen replaces it. `--pairing-token` still works as another name
for `--setup-code`.
