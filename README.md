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
- Google Tasks shown as a separate “Reminders” region (due today + overdue)  
- Sorted by start time (all-day events first)  
- Portrait layout for 13.3" display  
- Updates every 15 minutes  
- Only refreshes screen when content changes (e-ink friendly)  
- Nightly sleep window with one-time “Sleeping…” banner  
- Weekly deep clean refresh to reduce ghosting  
- Over-the-air updates (pulls new code from GitHub on its own — no SSH)  
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

## 🔄 Over-the-air updates (no SSH)

Once installed, the Pi keeps itself up to date. You can hand the device to
someone (e.g. a parent), push a fix from your laptop, and the display updates
itself — no SSH or screen needed.

**Checking.** On every 15-minute refresh, the display checks GitHub to see if
this checkout is behind the tracked branch. This is cheap (a `git fetch` that
finds nothing is a couple of tiny requests — ~96/day is well within GitHub's
limits, and no auth token is used), so there's no rate-limit concern.

**Showing status.** When an update is available, the bottom status bar (next to
the WiFi icon) shows **"Update pending"** in red, along with **"Software updated
&lt;date&gt;"** — the date the program was last updated. So you get visible
confirmation on the screen that your push was received.

**Applying.** A systemd timer (`inkycal-update.timer`) runs
`scripts/ota_update.sh` and, when it finds the checkout behind, pulls and
applies the update:

- reinstalls Python dependencies only when `requirements.txt` changed
- reinstalls the systemd units only when anything under `systemd/` changed
- restarts the provisioning agent if it's running
- triggers a fresh display render with the new code

By default this is done **only during the overnight sleep window**, so the
screen never restarts while someone's looking at it during the day (it shows the
"Sleeping…" banner overnight anyway). Set `apply_window: anytime` to apply as
soon as an update is found instead.

Configure it in `config.yaml`:

```yaml
auto_update:
  enabled: true          # set false to freeze the installed version
  branch: "main"         # branch to track
  apply_window: "sleep"  # "sleep" = only overnight; "anytime" = as soon as found
```

Useful commands (on the Pi):

```bash
# Update right now instead of waiting for the timer
sudo systemctl start inkycal-update.service

# Watch what it did
journalctl -u inkycal-update.service -n 50

# See when it will next run
systemctl list-timers inkycal-update.timer

# Turn auto-updates off entirely
sudo systemctl disable --now inkycal-update.timer
```

> **Note:** the updater does a `git reset --hard` to the tracked branch, so the
> device always converges to GitHub's `main`. Your `config.yaml`, `.env` and
> `secrets/` are gitignored and are never touched. **Existing installs** need to
> register the new timer once — pull the code (command above) and re-run
> `./scripts/install.sh` (or re-run the one-command bootstrap). After that the
> updates are automatic and the installer step is never needed again.

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

> **Reminders / Google Tasks:** the token now requests both
> `calendar.readonly` and `tasks.readonly`. If you generated your token before
> Tasks support was added, re-run the sign-in flow (companion app or
> `scripts/google_auth.py`) to grant the new scope — otherwise the calendar
> keeps working and the Reminders region simply stays empty. Disable it any
> time with `calendars.google.tasks_enabled: false` in `config.yaml`.

The Pi reads the token, refreshes the short-lived access token on its own
using the embedded refresh token, and never opens a browser.
