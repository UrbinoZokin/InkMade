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

```bash
curl -fsSL https://raw.githubusercontent.com/UrbinoZokin/InkMade/main/scripts/bootstrap.sh | \
  REPO_URL="https://github.com/UrbinoZokin/InkMade.git" bash
```

To pull the latest changes afterwards:

```bash
cd /opt/inkycal && \
  git fetch origin && \
  git reset --hard origin/main && \
  chmod +x /opt/inkycal/scripts/update.sh
```

## Google Calendar auth — Companion app (recommended)

The easiest way to get the Pi onto WiFi and connected to Google Calendar is the
**InkyCal Companion app** in [`companion/`](companion/). It runs on your
laptop, finds the Pi (WiFi first, Bluetooth fallback), sets up WiFi over
Bluetooth if the Pi isn't online yet, runs the Google sign-in in your browser,
and delivers the token to the Pi — no keyboard or monitor on the Pi needed.

**On the Pi**, install the provisioning agent once (after `scripts/install.sh`):

```bash
cd /opt/inkycal && ./scripts/install_provisioning.sh
```

This advertises the Pi over Bluetooth (`InkyCal-Setup`) and, once online, over
mDNS (`_inkycal._tcp`).

**On your laptop**, build/run the companion app — see
[`companion/README.md`](companion/README.md) for the one-click executable build
and a walkthrough of getting Google OAuth credentials.

## Google Calendar auth — manual (off-device)

The Pi runs headless, so the OAuth consent flow happens on another machine.

1. On a machine with a browser, install the helper dependencies and run:

   ```bash
   pip install google-auth google-auth-oauthlib
   python scripts/google_auth.py \
     --credentials ./google_credentials.json \
     --token ./google_token.json
   ```

2. Copy `google_token.json` to the Pi at the path referenced by
   `GOOGLE_TOKEN_JSON` in `/opt/inkycal/.env`
   (default: `/opt/inkycal/secrets/google_token.json`).

The Pi reads the token, refreshes the short-lived access token on its own
using the embedded refresh token, and never opens a browser.
