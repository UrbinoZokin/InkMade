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
STATE_DIR="${STATE_DIR:-/var/lib/inkycal}"
FORCE_UPDATE_FLAG="$STATE_DIR/force_update"

log() { echo "[ota-update] $*"; }

if [ ! -d "$APP_DIR/.git" ]; then
  log "No git checkout at $APP_DIR; nothing to update."
  exit 0
fi

cd "$APP_DIR"

OWNER="$(stat -c '%U' "$APP_DIR")"
GROUP="$(stat -c '%G' "$APP_DIR")"

# This service runs as root, but git runs as the checkout's owner (e.g. 'pi'),
# the same user the quarter-hour render runs it as. Root running git in a
# checkout it doesn't own is refused as "dubious ownership" unless root's global
# git config says otherwise, and systemd gives this unit no $HOME to keep that
# config in (no User= line): every scheduled run used to die right there with
# "fatal: $HOME not set". Root's fetches also left root-owned files in .git
# that the render's own fetch then couldn't write to.
if [ "$(id -u)" -eq 0 ] && [ "$OWNER" != "root" ]; then
  RUN_AS_OWNER=true
  git_as_owner() { runuser -u "$OWNER" -- git -C "$APP_DIR" "$@"; }
else
  RUN_AS_OWNER=false
  git_as_owner() { git -C "$APP_DIR" "$@"; }
fi

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

# The force-update button (see inkycal.buttons) drops this flag file to
# bypass the apply_window gate and apply a pending update immediately. It's
# a one-shot trigger: always consume it here so it can't linger and force
# a future *scheduled* check to apply outside its normal window.
if [ -f "$FORCE_UPDATE_FLAG" ]; then
  log "Force-update flag present; applying regardless of apply_window."
  SHOULD_APPLY=true
  rm -f "$FORCE_UPDATE_FLAG"
fi

case "$ENABLED" in
  true|True|1|yes) ;;
  *)
    log "auto_update.enabled is '$ENABLED' in config.yaml; skipping."
    exit 0
    ;;
esac

log "Checking for updates on origin/$BRANCH ..."

# Anything root has left in the checkout -- earlier versions of this script ran
# git as root, and so does a `sudo git pull` by hand -- stops the owner's git
# from writing there. Hand it back first. Only files that need it are touched,
# and venv/ is skipped: git never writes to it, and it's thousands of files.
if [ "$RUN_AS_OWNER" = true ]; then
  find "$APP_DIR" -path "$VENV_DIR" -prune -o \
    \( ! -user "$OWNER" -o ! -group "$GROUP" \) -exec chown -h "$OWNER:$GROUP" {} + \
    || log "Could not hand every file in $APP_DIR back to $OWNER; continuing."
fi

# Fetch with a few retries; the Pi's network (or GitHub) can be briefly flaky.
fetched=0
delay=2
for attempt in 1 2 3 4; do
  if git_as_owner fetch --quiet origin "$BRANCH"; then
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

LOCAL="$(git_as_owner rev-parse HEAD)"
REMOTE="$(git_as_owner rev-parse "origin/$BRANCH")"

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
git_as_owner reset --hard "origin/$BRANCH"
NEW="$(git_as_owner rev-parse HEAD)"

# git ran as the app user, but pip below still runs as root. Keep the whole
# checkout, venv/ included, owned by the app user.
chown -R "$OWNER:$GROUP" "$APP_DIR"

CHANGED="$(git_as_owner diff --name-only "$OLD" "$NEW" 2>/dev/null || true)"

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
  # Match install.sh: run the display services as the repo owner, not root, and
  # rewrite Group= alongside User= -- a unit left on the packaged Group=pi will
  # not start on a device whose user was named anything else at first boot.
  sed -i -e "s/^User=.*/User=$OWNER/" -e "s/^Group=.*/Group=$GROUP/" \
    /etc/systemd/system/inkycal.service \
    /etc/systemd/system/inkycal-boot.service \
    /etc/systemd/system/inkycal-deepclean.service 2>/dev/null || true
  systemctl daemon-reload
  # inkycal-boot.service is in this list so a device that gets the power-on
  # refresh over the air, rather than from a fresh install.sh run, still has it
  # armed for its next boot. No --now: this run triggers its own render below.
  systemctl enable inkycal.timer inkycal-deepclean.timer inkycal-update.timer \
    inkycal-boot.service >/dev/null 2>&1 || true
  # --now here (unlike the timers above): a device that gets this feature via
  # OTA rather than a fresh install.sh run has never had this unit running,
  # so plain `enable` would only symlink it for next boot.
  systemctl enable --now inkycal-buttons.service >/dev/null 2>&1 || true
fi

# Restart the long-running provisioning agent so it picks up new code.
if systemctl is-active --quiet inkycal-provisioning.service; then
  log "Restarting provisioning agent..."
  systemctl restart inkycal-provisioning.service || true
fi

# Restart the button daemon so it picks up new code (e.g. new pin config).
if systemctl is-active --quiet inkycal-buttons.service; then
  log "Restarting buttons daemon..."
  systemctl restart inkycal-buttons.service || true
fi

# Trigger an immediate re-render with the new code. --no-block so we don't wait
# on the render service's ExecStartPre sleep.
log "Update applied (${NEW:0:9}). Triggering a display refresh..."
systemctl start --no-block inkycal.service || true

log "Done."
