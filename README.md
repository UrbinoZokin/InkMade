## WORK IN PROGRESS
# InkyCal  
Daily calendar display for Raspberry Pi Zero 2 W + Inky Impressions 13.3" E-Ink

Displays today’s merged Google + iCloud calendar schedule in portrait mode.

Quick weather report for long events:

```bash
PYTHONPATH=src python -m inkycal.main --config config.yaml --long-events-weather-report
```

Generate/refresh Google OAuth token from CLI:

```bash
PYTHONPATH=src python -m inkycal.main \
  --google-oauth-init \
  --google-credentials /opt/inkycal/secrets/google_credentials.json \
  --google-token /opt/inkycal/secrets/google_token.json
```

For production use in Google Cloud Console:

1. OAuth consent screen should be **In production**.
2. Create an **OAuth client ID** of type **Desktop app**.
3. Download the client JSON to your credentials path.
4. Run the command above (use `GOOGLE_OAUTH_PORT=8080` if you need fixed SSH port forwarding).
5. Set `GOOGLE_CREDENTIALS_JSON` and `GOOGLE_TOKEN_JSON` in your `.env`.

OAuth loopback troubleshooting:
- If your browser fails on `localhost:<port>`, force IPv4 loopback: `GOOGLE_OAUTH_HOST=127.0.0.1`.
- If needed, set bind explicitly too: `GOOGLE_OAUTH_BIND_ADDR=127.0.0.1`.
- Avoid private LAN IPs (for example `192.168.x.x`) for callback host/bind; Google may reject with `device_id and device_name are required for private IP`.
- For remote auth over SSH tunneling, use a fixed `GOOGLE_OAUTH_PORT` and forward that same port.

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

cd /opt/inkycal \
git fetch origin \
git reset --hard origin/Calendar_debugging \
chmod +x /opt/inkycal/scripts/update.sh
