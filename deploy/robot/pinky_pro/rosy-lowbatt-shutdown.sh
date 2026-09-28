#!/usr/bin/env bash
#
# Halt the host when CORE reports the pack has reached deep discharge.
#
# CORE runs as uid 1000 with no host privilege, so it cannot halt anything. It
# writes an observation to a file; this script decides whether to act. That
# direction matters: there is no command channel, no socket and no
# authentication, and the worst a compromised CORE can achieve is a shutdown,
# which is the safe direction.
#
# What is being protected is the filesystem, not the cells. The pack's own
# protection board will cut off and save the cells, but from the Pi's point of
# view that is an unannounced power removal with the root filesystem mounted.
#
# Design: docs/plans/2026-09-02-battery-integrity-low-battery-alert-design.md
# ADR: D-27 (the one sanctioned halt; see also D-25)

set -euo pipefail

SENTINEL="${ROSY_LOWBATT_SENTINEL:-/var/lib/rosy/battery-shutdown-request.json}"

# A sentinel older than this is not evidence about the battery now. Because
# /var/lib/rosy is persistent, a file left behind by an unclean shutdown would
# otherwise halt the machine again on the next boot, and again after that.
ROSY_LOWBATT_MAX_AGE_S="${ROSY_LOWBATT_MAX_AGE_S:-900}"

# Refuse a grace period longer than this however the sentinel is written. The
# host bounds its own waiting rather than trusting a number from the container.
MAX_GRACE_S="${ROSY_LOWBATT_MAX_GRACE_S:-600}"

# Logging must never be the reason the machine fails to shut down. `logger` is
# normally present on Raspberry Pi OS, but under `set -e` a missing binary would
# abort the script before it ever reaches the halt.
log() {
    logger -t rosy-lowbatt -- "$*" 2>/dev/null || true
    printf '%s\n' "$*" >&2 || true
}

read_field() {
    # One field out of a small flat JSON document, without requiring jq on the
    # image. Returns empty when absent; every caller has a default.
    sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\{0,1\}\([^\",}]*\).*/\1/p" \
        "$SENTINEL" 2>/dev/null | head -n 1
}

fresh_enough() {
    local requested_at epoch now age
    requested_at="$(read_field requested_at)"
    if [ -z "$requested_at" ]; then
        log "sentinel has no requested_at; refusing to halt"
        return 1
    fi
    if ! epoch="$(date -d "$requested_at" +%s 2>/dev/null)"; then
        log "sentinel requested_at is unparseable ($requested_at); refusing to halt"
        return 1
    fi
    now="$(date +%s)"
    age=$(( now - epoch ))
    # A clock that jumped backwards makes age negative. Treat that as unusable
    # rather than as "very fresh".
    if [ "$age" -lt 0 ] || [ "$age" -gt "$ROSY_LOWBATT_MAX_AGE_S" ]; then
        log "sentinel is ${age}s old (max ${ROSY_LOWBATT_MAX_AGE_S}s); refusing to halt"
        return 1
    fi
    return 0
}

if [ ! -f "$SENTINEL" ]; then
    log "no sentinel present; nothing to do"
    exit 0
fi

if ! fresh_enough; then
    exit 0
fi

grace="$(read_field grace_seconds)"
grace="${grace%%.*}"
case "$grace" in
    ''|*[!0-9]*) grace=120 ;;
esac
[ "$grace" -gt "$MAX_GRACE_S" ] && grace="$MAX_GRACE_S"

log "low battery shutdown requested (percent=$(read_field percent), \
voltage=$(read_field voltage)); halting in ${grace}s unless it recovers"

sleep "$grace"

# CORE removes the sentinel when the level recovers, so plugging the robot in
# during the grace period cancels the shutdown with no other signalling. Both
# checks run again because the whole grace period has passed since the first.
if [ ! -f "$SENTINEL" ]; then
    log "sentinel withdrawn during the grace period; staying up"
    exit 0
fi

if ! fresh_enough; then
    exit 0
fi

log "halting now"
systemctl --no-block poweroff
