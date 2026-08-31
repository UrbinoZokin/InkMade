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
- Contact birthdays from Google's Contacts calendar, grouped on their own row  
- Sorted by start time (all-day events first)  
- Portrait layout for 13.3" display  
- Updates every 15 minutes  
- Only refreshes screen when content changes (e-ink friendly)  
- Nightly sleep window with one-time “Sleeping…” banner  
- Weekly deep clean refresh to reduce ghosting  
- Over-the-air updates (pulls new code from GitHub on its own — no SSH)  
- Physical buttons: switch daily/weekly view, force refresh, force update  
- Presses are acknowledged on the display before the slow work starts  
- Button presses echo live to any SSH session (and the local console)  
- Everything starts on its own at power-on, with a forced display refresh  
- Fully automated install with virtualenv (no externally-managed errors)  
- systemd timers for reliability  

---

## 🔘 Physical buttons

The Inky Impression's 4 built-in buttons (labeled A/B/C/D on the board) are
wired up as follows:

| Button | Function |
| --- | --- |
| A | Toggle between the daily view (default) and a weekly view showing the next 7 days' event names (no times) |
| B | Force an immediate display refresh |
| C | Unused (reserved for future use) |
| D | Force an OTA update check, applying it right away if one is pending (bypasses the overnight `apply_window`) |

Pressing A or B re-renders instantly using the same code path as the
periodic timer, so credentials and file ownership stay consistent. Pressing
D asks `inkycal-update.service` to check GitHub and, if the checkout is
behind, apply the update immediately instead of waiting for the next
scheduled window.

### Seeing that a press registered

A press can't draw anything until it has fetched calendars, weather and
travel times — 10–60 seconds during which the panel sits completely still.
So before that work starts, the display puts up a short notice: *Switching
view… please wait*, *Refreshing… please wait* or *Checking for updates…
please wait*. The panel begins its visible flash a few seconds after the
press, which is the acknowledgement; the real content lands when the fetch
finishes, and for button D when the update run finishes (so the notice stays
up for the whole install).

A press that arrives while the previous one is still being acted on is
dropped, not queued — somebody pressing again because they aren't sure the
first press worked wants that press to have worked, not a second refresh
behind it. Without that, four impatient presses would mean four full flash
cycles back to back, which looks exactly like the malfunction they were
worried about. The extra presses show up in the journal (and in any SSH
session) as ignored.

The Impression has no partial refresh, so this costs one extra full-panel
repaint — content arrives roughly twice as slowly as before. Pick the trade
with `press_feedback` in `config.yaml`:

| Value | Behaviour |
| --- | --- |
| `banner` (default) | Keep the schedule on screen with a notice bar across the top |
| `wipe` | Clear the panel to a centred message |
| `none` | No acknowledgement — the display stays put until the new content is ready |

Button C shows nothing: no work follows it, so a notice would spend a full
refresh announcing that nothing happened.

### Watching presses over SSH

Every press is echoed to the terminals of everyone logged in, so if you're
SSH'd into the Pi you'll see the button announce itself as it's pressed:

```
[InkyCal] Button A (view) pressed: toggling daily/weekly view
```

Nothing to run or leave open — the line arrives in your shell (and on the
local console) as it happens, including for button C, which has no function
assigned. Presses always go to the journal too
(`journalctl -u inkycal-buttons -f`); set `echo_to_terminals: false` if you'd
rather have them there only.

Handled by `inkycal-buttons.service`, installed and enabled automatically by
`scripts/install.sh`. Configure it in `config.yaml`:

```yaml
buttons:
  enabled: true
  pin_view: 5
  pin_refresh: 6
  pin_unused: 25
  pin_update: 24
  bounce_time_ms: 300
  echo_to_terminals: true
  press_feedback: "banner"   # banner | wipe | none
```

Pin numbers are BCM GPIO numbers. The defaults match the 13.3" Inky
Impression; button C is wired to GPIO25 on that model instead of the GPIO16
used on the smaller 4"/5.7"/7.3" sizes — if you're on one of those, set
`pin_unused: 16`. Set `enabled: false` to disable the daemon entirely (or
`sudo systemctl disable --now inkycal-buttons.service`).

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

## 🔌 What happens when you plug it in

Installing once is the last hands-on step. From then on, every power-on brings
the whole thing up with no keyboard, SSH or button press:

| Unit | What it does at boot |
|---|---|
| `inkycal-boot.service` | Forces one full display refresh |
| `inkycal.timer` | Renders again 2 min in, then every quarter hour |
| `inkycal-update.timer` | Checks GitHub for over-the-air updates, then every 30 min |
| `inkycal-deepclean.timer` | Arms the weekly ghosting deep clean |
| `inkycal-buttons.service` | Makes the physical buttons live |
| `inkycal-provisioning.service` | BLE/mDNS setup agent, if you installed it |

**Why the forced refresh.** E-ink holds its last image with the power off, and
the quarter-hour render deliberately *skips* the panel when the schedule hasn't
changed — that's what keeps a display this size from ghosting. Together those
two mean a Pi that has been unplugged can come back up and sit there showing a
stale day indefinitely, because as far as it can tell nothing needs repainting.
`inkycal-boot.service` repaints unconditionally, so what you see after a power
cut is always current.

Before rendering it waits — briefly, and never fatally — for the two things the
render is wrong without: a network to fetch calendars over, and a clock that NTP
has corrected (the Pi has no battery-backed RTC, so a render that beats the time
sync would date the screen from whenever it was last shut down). If either wait
runs out it renders anyway; an offline render shows the WiFi-offline marker in
the status bar, which is the feedback a not-yet-provisioned device should give.

The same unit is a convenient "repaint now, whatever is on screen":

```bash
# Force a refresh by hand, exactly the way a power-on does it
sudo systemctl start inkycal-boot.service

# See what it did
journalctl -u inkycal-boot.service -n 50

# What is armed to start at boot
systemctl list-unit-files 'inkycal*'
systemctl list-timers --all | grep inkycal
```

Turn the power-on refresh off with `sudo systemctl disable inkycal-boot.service`;
the quarter-hour timer still runs.

> **Existing installs** pick this up automatically on the next over-the-air
> update — the updater enables the new unit itself. There's nothing to re-run.

### When the display stops updating

E-ink keeps its last image, so "frozen" and "crashed" look identical on the
wall. Work from the journal rather than the panel:

```bash
# Did the quarter-hour render run, and what did it decide?
journalctl -u inkycal.service -n 100

# Same for the power-on repaint and the updater
journalctl -u inkycal-boot.service -n 50
journalctl -u inkycal-update.service -n 50

# Is the timer still armed and firing?
systemctl list-timers --all | grep inkycal
```

Every run prints its verdict, and each one points somewhere different:

| Log line | What it means |
|---|---|
| `No schedule change; skipping display refresh` | Working as designed — nothing changed, and the panel is repainted at least hourly regardless. |
| `In sleep window; skipping poll/refresh` | Check `sleep.start`/`sleep.end` in `config.yaml`. Collapsing the window to a single time does *not* disable sleep; set `sleep.enabled: false` for that. |
| `... starting from a blank state` | `/var/lib/inkycal/state.json` was damaged (an SD-card write cut short by a power loss). It repairs itself on this run; the only cost is one extra repaint. |
| `Display still busy` / `rendering unlocked` | Two refreshes wanted the panel at once. Harmless — the render goes ahead either way. |
| A Python traceback | The run died before reaching the panel, and will keep dying until the cause is fixed. The last line names it. |

Nothing in the journal at all means the render never ran — check the timer above,
then `systemctl status inkycal.service`.

To rule the schedule logic out entirely, force a repaint by hand:

```bash
sudo systemctl start inkycal-boot.service
```

If that paints and the quarter-hour runs don't, the problem is the timer or the
skip logic, not the calendars or the panel.

## 🔄 Over-the-air updates (no SSH)

Once installed, the Pi keeps itself up to date. You can hand the device to
someone (e.g. a parent), push a fix from your laptop, and the display updates
itself — no SSH or screen needed.

**Checking.** On every 15-minute refresh, the display checks GitHub to see if
this checkout is behind the tracked branch. This is cheap (a `git fetch` that
finds nothing is a couple of tiny requests — ~96/day is well within GitHub's
limits, and no auth token is used), so there's no rate-limit concern.

**Showing status.** When an update is available, the bottom status bar (next to
the WiFi icon) shows **"Update pending"** in red — visible confirmation on the
screen that your push was received.

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

> **Birthdays:** Google keeps the birthdays it derives from Google Contacts in
> a separate read-only calendar
> (`addressbook#contacts@group.v.calendar.google.com`), which is not part of
> `primary`. InkyCal adds it automatically — it needs no OAuth scope beyond the
> `calendar.readonly` the token already has — and the day's birthdays render as
> their own “Birthdays: …” row. Turn it off with
> `calendars.google.birthdays_enabled: false`. Apple does **not** publish the
> equivalent iCloud Contacts birthday calendar over CalDAV (it is generated
> on-device), so iCloud birthdays only appear if you keep them in a real
> calendar — one named “Birthdays” is picked up and grouped the same way.

> **Reminders / Google Tasks:** the token now requests both
> `calendar.readonly` and `tasks.readonly`. If you generated your token before
> Tasks support was added, re-run the sign-in flow (companion app or
> `scripts/google_auth.py`) to grant the new scope — otherwise the calendar
> keeps working and the Reminders region simply stays empty. Disable it any
> time with `calendars.google.tasks_enabled: false` in `config.yaml`.

The Pi reads the token, refreshes the short-lived access token on its own
using the embedded refresh token, and never opens a browser.
