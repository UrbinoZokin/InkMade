#!/usr/bin/env bash
#
# InkyCal power-on refresh.
#
# Run once per boot by inkycal-boot.service. E-ink keeps whatever was on the
# panel when the power went out, and the quarter-hour render deliberately skips
# the display when the schedule hash still matches what it painted last time --
# so without this, a device that has been unplugged for a day can come back up
# and sit there showing yesterday until something in the schedule happens to
# change. This forces one full repaint, unconditionally.
#
# Before rendering it waits, briefly and never fatally, for the two things the
# render is wrong without:
#
#   network - calendars, weather and travel times all come off the wire
#   clock   - the Pi has no battery-backed RTC, so a render that beats NTP
#             dates the screen from whenever the image last shut down
#
# Both waits are bounded. Timing out is not a failure: rendering offline puts
# the WiFi-offline marker in the status bar, which is exactly the feedback
# someone powering on a not-yet-provisioned device needs to see.
#
# Also usable by hand as a "refresh now, whatever is on screen":
#
#     sudo systemctl start inkycal-boot.service
#
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/inkycal}"
VENV="$APP_DIR/venv/bin/python"
STATE_DIR="${STATE_DIR:-/var/lib/inkycal}"

NETWORK_WAIT_S="${INKYCAL_BOOT_NETWORK_WAIT_S:-90}"
CLOCK_WAIT_S="${INKYCAL_BOOT_CLOCK_WAIT_S:-60}"

log() { echo "[boot-refresh] $*"; }

network_ready() {
  local rc=0
  # Plain nm-online (no -s) waits for the network to actually be online rather
  # than for NetworkManager's own startup to finish -- the latter completes
  # even when the WiFi never associated.
  if command -v nm-online >/dev/null 2>&1; then
    nm-online -q -t 1 >/dev/null 2>&1 || rc=$?
    if [ "$rc" -eq 0 ]; then
      return 0
    elif [ "$rc" -ne 2 ]; then
      # Not online yet. Don't let the looser route check below overrule that.
      return 1
    fi
    # rc=2: NetworkManager isn't running at all (a dhcpcd-based image), so it
    # is never going to answer. Fall through to the route check.
  fi
  [ -n "$(ip route show default 2>/dev/null)" ]
}

clock_ready() {
  local synced
  # No usable timedatectl means no time daemon to wait on. Anything that can't
  # answer -- missing binary, non-zero exit, empty answer -- is never going to
  # report in, so treat it as "nothing to wait for" rather than burning the
  # whole bound on every boot. Any NTP client (timesyncd, chrony) clears the
  # kernel's unsynchronised flag, which is what this reads.
  command -v timedatectl >/dev/null 2>&1 || return 0
  synced="$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" || return 0
  [ -z "$synced" ] || [ "$synced" = "yes" ]
}

wait_for() {
  local label="$1" seconds="$2" check="$3"
  local started=$SECONDS
  local deadline=$((SECONDS + seconds))

  if "$check"; then
    log "$label ready."
    return 0
  fi

  log "Waiting up to ${seconds}s for $label ..."
  while [ "$SECONDS" -lt "$deadline" ]; do
    sleep 2
    if "$check"; then
      log "$label ready after $((SECONDS - started))s."
      return 0
    fi
  done

  log "$label still not ready after ${seconds}s; rendering anyway."
  return 1
}

wait_for "network" "$NETWORK_WAIT_S" network_ready || true
wait_for "clock sync" "$CLOCK_WAIT_S" clock_ready || true

log "Local time is now $(date '+%Y-%m-%d %H:%M:%S %Z')."

# Load .env the same way scripts/update.sh does: tolerates quotes and avoids
# systemd's EnvironmentFile parsing quirks.
if [ -f "$APP_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$APP_DIR/.env"
  set +a
fi

log "Forcing a display refresh."
exec "$VENV" -m inkycal.main \
  --config "$APP_DIR/config.yaml" \
  --state "$STATE_DIR/state.json" \
  --force
