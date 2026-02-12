## WORK IN PROGRESS
# InkyCal  
Daily calendar display for Raspberry Pi Zero 2 W + Inky Impressions 13.3" E-Ink

Displays today’s merged Google + iCloud calendar schedule in portrait mode.

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

curl -fsSL https://raw.githubusercontent.com/UrbinoZokin/InkMade/Calendar_debugging/scripts/bootstrap.sh | \
REPO_URL="https://github.com/UrbinoZokin/InkMade.git" bash

git fetch origin
git reset --hard origin/Calendar_debugging
chmod +x /opt/inkycal/scripts/update.sh
