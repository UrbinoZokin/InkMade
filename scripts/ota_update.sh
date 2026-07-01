#!/usr/bin/env bash
#
# InkyCal over-the-air (OTA) updater.
#
# Checks the tracking branch on GitHub and, if the local checkout at
# /opt/inkycal is behind, pulls the new code and applies it in place:
#   - reinstalls Python dependencies only when requirements.txt changed
#   - refreshes the editable package install only when pyproject.toml changed
#   - reinstalls the systemd units only when systemd/ changed
#   - restarts the provisioning agent if it is running
#   - triggers a fresh display render with the new code
#
# It is normally run by inkycal-update.service on the inkycal-update.timer
# schedule, but can also be triggered by hand:
#
#     sudo systemctl start inkycal-update.service
#
# Behaviour is controlled by the `auto_update` section of config.yaml:
#
#     auto_update:
#       enabled: true      # set false to freeze the installed version
#       branch: "main"     # branch to track
#
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/inkycal}"
VENV_DIR="$APP_DIR/venv"
PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

log() { echo "[ota-update] $*"; }

if [ ! -d "$APP_DIR/.git" ]; then
  log "No git checkout at $APP_DIR; nothing to update."
  exit 0
fi

cd "$APP_DIR"

# This service runs as root while the checkout is usually owned by the app user
# (e.g. 'pi'). Tell git the checkout is trusted so it does not refuse with
# "detected dubious ownership in repository". Add the entry only once.
if ! git config --global --get-all safe.directory 2>/dev/null | grep -qx "$APP_DIR"; then
  git config --global --add safe.directory "$APP_DIR"
fi

OWNER="$(stat -c '%U' "$APP_DIR")"
GROUP="$(stat -c '%G' "$APP_DIR")"

# Read the settings we need from config.yaml using the venv's PyYAML, and let it
# also decide whether we're allowed to *apply* right now. apply_window="sleep"
# (the default) means updates are only applied during the overnight sleep window
# so they never disrupt daytime viewing; "anytime" applies as soon as found.
# Emits shell-friendly KEY=value lines; falls back to safe defaults on any error.
cfg_eval() {
  if [ ! -x "$PY" ]; then
    printf 'enabled=true\nbranch=main\nshould_apply=true\n'
    return
  fi
  "$PY" - "$APP_DIR/config.yaml" <<'PYEOF' 2>/dev/null || printf 'enabled=true\nbranch=main\nshould_apply=true\n'
import sys
from datetime import datetime, time

DEFAULTS = "enabled=true\nbranch=main\nshould_apply=true"
try:
    import yaml
    with open(sys.argv[1]) as f:
        data = yaml.safe_load(f) or {}
except Exception:
    print(DEFAULTS)
    raise SystemExit(0)

au = data.get("auto_update") or {}
enabled = bool(au.get("enabled", True))
branch = str(au.get("branch", "main")).strip() or "main"
apply_window = str(au.get("apply_window", "sleep")).strip().lower()

sleep_cfg = data.get("sleep") or {}
sleep_enabled = bool(sleep_cfg.get("enabled", True))

def parse_hhmm(value, default):
    try:
        hh, mm = str(value).split(":")
        return time(int(hh), int(mm))
    except Exception:
        return default

start = parse_hhmm(sleep_cfg.get("start", "22:30"), time(22, 30))
end = parse_hhmm(sleep_cfg.get("end", "06:30"), time(6, 30))

tzname = str(data.get("timezone", "America/Phoenix"))
try:
    from zoneinfo import ZoneInfo
    now_t = datetime.now(ZoneInfo(tzname)).timetz().replace(tzinfo=None)
except Exception:
    now_t = datetime.now().time()
now_t = now_t.replace(second=0, microsecond=0)

def in_window(t, s, e):
    return (s <= t < e) if s < e else (t >= s or t < e)

if apply_window == "anytime" or not sleep_enabled:
    should_apply = True
else:
    should_apply = in_window(now_t, start, end)

print(f"enabled={'true' if enabled else 'false'}")
print(f"branch={branch}")
print(f"should_apply={'true' if should_apply else 'false'}")
PYEOF
}

ENABLED=true
CFG_BRANCH=main
SHOULD_APPLY=true
while IFS='=' read -r _k _v; do
  case "$_k" in
    enabled) ENABLED="$_v" ;;
    branch) CFG_BRANCH="$_v" ;;
    should_apply) SHOULD_APPLY="$_v" ;;
  esac
done <<EOF
$(cfg_eval)
EOF
BRANCH="${OTA_BRANCH:-$CFG_BRANCH}"

case "$ENABLED" in
  true|True|1|yes) ;;
  *)
    log "auto_update.enabled is '$ENABLED' in config.yaml; skipping."
    exit 0
    ;;
esac

log "Checking for updates on origin/$BRANCH ..."

# Fetch with a few retries; the Pi's network (or GitHub) can be briefly flaky.
fetched=0
delay=2
for attempt in 1 2 3 4; do
  if git fetch --quiet origin "$BRANCH"; then
    fetched=1
    break
  fi
  log "git fetch failed (attempt $attempt); retrying in ${delay}s..."
  sleep "$delay"
  delay=$((delay * 2))
done
if [ "$fetched" -ne 1 ]; then
  log "Could not reach origin after retries; will try again next run."
  exit 0
fi

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

if [ "$LOCAL" = "$REMOTE" ]; then
  log "Already up to date ($LOCAL)."
  exit 0
fi

# An update is available. Unless we're allowed to apply now (apply_window), hold
# off — the display shows "Update pending" and we'll apply during the overnight
# sleep window when nobody's looking.
if [ "$SHOULD_APPLY" != "true" ]; then
  log "Update available (${LOCAL:0:9} -> ${REMOTE:0:9}), but outside the apply window; deferring to the overnight sleep window."
  exit 0
fi

log "Update available: ${LOCAL:0:9} -> ${REMOTE:0:9}. Pulling origin/$BRANCH ..."

OLD="$LOCAL"
# origin/main is the source of truth for a deployed device: converge to it even
# if the local checkout somehow diverged. Tracked local edits are discarded;
# config.yaml, .env and secrets/ are gitignored and left untouched.
git reset --hard "origin/$BRANCH"
NEW="$(git rev-parse HEAD)"

# Keep the checkout owned by the app user after pulling as root.
chown -R "$OWNER:$GROUP" "$APP_DIR"

CHANGED="$(git diff --name-only "$OLD" "$NEW" 2>/dev/null || true)"

# Keep helper scripts executable (mirrors install.sh).
chmod +x "$APP_DIR"/scripts/*.sh 2>/dev/null || true

if printf '%s\n' "$CHANGED" | grep -qx 'requirements.txt'; then
  log "requirements.txt changed; reinstalling Python dependencies..."
  "$PIP" install -r "$APP_DIR/requirements.txt"
fi
if printf '%s\n' "$CHANGED" | grep -qx 'pyproject.toml'; then
  log "pyproject.toml changed; refreshing package install..."
  "$PIP" install -e "$APP_DIR"
fi

if printf '%s\n' "$CHANGED" | grep -q '^systemd/'; then
  log "systemd units changed; reinstalling..."
  cp "$APP_DIR/systemd/"*.service "$APP_DIR/systemd/"*.timer /etc/systemd/system/
  # Match install.sh: run the display services as the repo owner, not root.
  sed -i "s/^User=.*/User=$OWNER/" \
    /etc/systemd/system/inkycal.service \
    /etc/systemd/system/inkycal-deepclean.service 2>/dev/null || true
  systemctl daemon-reload
  systemctl enable inkycal.timer inkycal-deepclean.timer inkycal-update.timer \
    >/dev/null 2>&1 || true
fi

# Restart the long-running provisioning agent so it picks up new code.
if systemctl is-active --quiet inkycal-provisioning.service; then
  log "Restarting provisioning agent..."
  systemctl restart inkycal-provisioning.service || true
fi

# Trigger an immediate re-render with the new code. --no-block so we don't wait
# on the render service's ExecStartPre sleep.
log "Update applied (${NEW:0:9}). Triggering a display refresh..."
systemctl start --no-block inkycal.service || true

log "Done."
