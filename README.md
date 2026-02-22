## WORK IN PROGRESS
# InkyCal  
Daily calendar display for Raspberry Pi Zero 2 W + Inky Impressions 13.3" E-Ink

Displays today’s merged Google + iCloud calendar schedule in portrait mode.

Quick weather report for long events:

```bash
PYTHONPATH=src python -m inkycal.main --config config.yaml --long-events-weather-report
```

### Features

- Google Calendar + Apple iCloud (CalDAV) sync  
- Sorted by start time (all-day events first)  
- Portrait layout for 13.3" display  
- Updates every 15 minutes  
- Only refreshes screen when content changes (e-ink friendly)  
- Nightly sleep window with one-time “Sleeping…” banner  
- Weekly deep clean refresh to reduce ghosting  
- Fully automated install with virtualenv (no externally-managed errors)  
- systemd timers for reliability  

---

# 🚀 Quick Install (one command)

curl -fsSL https://raw.githubusercontent.com/UrbinoZokin/InkMade/main/scripts/bootstrap.sh | \
REPO_URL="https://github.com/UrbinoZokin/InkMade.git" bash

cd /opt/inkycal \
git fetch origin \
git reset --hard origin/main \
chmod +x /opt/inkycal/scripts/update.sh

---

## 📱 Bluetooth setup app (Flutter + iPhone) feasibility

Yes — this is a practical way to make first-time setup much easier for InkyCal devices.

### What the app can do

- Connect to the Raspberry Pi over BLE for out-of-band provisioning.
- Send Wi-Fi SSID/password and show connection status.
- Guide Google Calendar OAuth authorization from the phone and return the auth code to the Pi.
- Store/update iCloud CalDAV credentials and display settings (timezone, sleep window, rotation, refresh interval).

### Recommended architecture

1. **Pi-side provisioning daemon**
   - Python service running at boot.
   - Hosts a custom BLE GATT service (via BlueZ D-Bus).
   - Persists setup values into `config.yaml` and an env file for secrets.
   - Triggers service restart/reload after successful apply.
2. **Flutter mobile app**
   - Uses a setup wizard (`Wi-Fi` → `Calendar auth` → `Display settings`).
   - Talks to BLE characteristics for config/status.
   - Opens Google OAuth in the mobile browser and passes code back to the Pi.

### Important Apple/iOS reality check

- You can write the app in Flutter on non-macOS systems.
- For **App Store distribution**, Apple still requires final iOS archive/signing with Xcode tooling, which means access to macOS (local Mac or cloud macOS CI).
- If you only need in-house or test distribution, options exist (TestFlight/enterprise workflows), but signing still requires Apple developer tooling.

### Suggested BLE characteristic groups

- `device_info` (read)
- `setup_state` (notify)
- `wifi_config` (write)
- `wifi_status` (read/notify)
- `google_oauth_url` (read)
- `google_oauth_code` (write)
- `icloud_config` (write)
- `settings` (read/write)
- `apply_restart` (write)

### Security baseline

- Require BLE pairing/bonding before writes.
- Use a one-time setup code shown on e-ink screen for initial trust.
- Keep secrets out of world-readable config files.
- Rotate/revoke credentials from app when re-provisioning.

If you want, the next step is to add a concrete implementation plan in this repo (service interface contract + daemon skeleton + Flutter screen flow).

### ✅ Initial implementation in this repo

A first provisioning backend is now included so you can start wiring a Flutter app to real device config updates:

- `inkycal.provisioning_server` → local HTTP JSON API (intended to be called by a BLE bridge process).
- `POST /connection/start` checks if the Pi is reachable and whether active services require a continue prompt.
- `POST /connection/authorize` generates a random 6-digit on-screen authorization code.
- `POST /connection/complete` verifies the user-entered authorization code to finish pairing.
- `inkycal.provisioning` → core provisioning service (Wi-Fi via `nmcli`, config updates, `.env` secret updates, apply/restart).
- `inkycal.provisioning_cli` → command-line utility for manual testing.
- `systemd/inkycal-provisioning.service` → optional always-on provisioning API unit.

Example local checks on the Pi:

```bash
# 1) run provisioning API
PROVISIONING_API_TOKEN="change-me" PYTHONPATH=src python -m inkycal.provisioning_server

# 2) read setup status
curl -H "X-Setup-Token: change-me" http://127.0.0.1:8765/status

# 3) update timezone/poll interval
curl -X POST -H "Content-Type: application/json"   -H "X-Setup-Token: change-me"   -d '{"timezone":"America/Phoenix","poll_interval_minutes":10}'   http://127.0.0.1:8765/settings
```

This gives you a stable app-facing contract now, and you can later swap transport from local HTTP to direct BLE GATT characteristics without rewriting config logic.

