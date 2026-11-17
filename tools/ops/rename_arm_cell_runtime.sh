#!/usr/bin/env bash
# D-1011 stage A: rename the arm cell runtime on the cell host (rosy-arm-cell).
#   cell-a -> arm-cell : compose project, /etc/rosy config dir, docker volume.
# DRY-RUN by default. Nothing changes unless --apply. Run as root on the cell host.
#
# Usage:
#   OPERATOR_HOME=/home/robttt tools/ops/rename_arm_cell_runtime.sh            # dry-run
#   OPERATOR_HOME=/home/robttt tools/ops/rename_arm_cell_runtime.sh --apply    # do it
#
# The script runs as root via sudo; the operator user's facts (session lock, job
# locks, motor-health state) live under OPERATOR_HOME (default /home/robttt).
# peer-cell-a keeps its compose service name: R's peer DNS alias depends on it.
# Renaming peer-cell-a / r-to-cell-a.token is a later step (D-1011).
#
# On any --apply failure after the switch starts, rollback runs automatically and
# brings the old cell-a stack back up. Manual equivalent (never rm -r; the config
# directory is moved, the old-path symlink removed with rm, the copied volume rm'd):
#   docker compose -p arm-cell --project-directory /etc/rosy/arm-cell down --timeout 30
#   [ -L /etc/rosy/cell-a ] && rm /etc/rosy/cell-a
#   mv /etc/rosy/arm-cell /etc/rosy/cell-a
#   docker volume rm arm-cell_arm_cell_data
#   docker compose -p cell-a --project-directory /etc/rosy/cell-a up -d --timeout 30
# Backups taken before the switch stay under /var/backups/rosy-rename.
set -euo pipefail

OLD_ID="cell-a"; NEW_ID="arm-cell"
OLD_UNIT="CELL-A"; NEW_UNIT="ARM-CELL"
OLD_DIR="/etc/rosy/${OLD_ID}"; NEW_DIR="/etc/rosy/${NEW_ID}"
OLD_VOLUME="${OLD_ID}_cell_a_data"; NEW_VOLUME="${NEW_ID}_arm_cell_data"
# compose.yaml keys (docker prefixes them with the project name at runtime)
OLD_VOLUME_KEY="cell_a_data"; NEW_VOLUME_KEY="arm_cell_data"
OLD_NETWORK_KEY="cell_a_backend"; NEW_NETWORK_KEY="arm_cell_backend"
# Real compose.yaml facts (2026-11-10): services fleet/vision/peer-cell-a, volume key
# cell_a_data mounted at /var/lib/rosy, network key cell_a_backend plus the external
# rosy-control-peers. Paths reference /etc/rosy/cell-a/..., /etc/rosy/control-unit/cell-a
# and /etc/rosy/workcell-observations/... (the latter two stay as they are).
SERVICES="fleet vision peer-cell-a"
BACKUP_ROOT="/var/backups/rosy-rename"
OPERATOR_HOME="${OPERATOR_HOME:-/home/robttt}"  # host operator user; never ~ (script runs as root)
SESSION_LOCK="${OPERATOR_HOME}/rosy-omx/session.lock"
JOBS_GLOB="${OPERATOR_HOME}/rosy-jobs/*.lock"
MOTOR_HEALTH_DIR="${OPERATOR_HOME}/.local/state/rosy/motor-health"
MOTOR_HEALTH_SCHEMA="rosy.motor-health.v1"
APPLY="${1:-}"

say() { printf '[rename-arm-cell] %s\n' "$*"; }
die() { printf '[rename-arm-cell] FATAL: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root on the cell host"
[ "$APPLY" = "--apply" ] || [ -z "$APPLY" ] || die "usage: $0 [--apply]"
DRY=$([ -z "$APPLY" ] && echo 1 || echo 0)

# --- guards: never rename while an arm session, job, or motor state is live -------
refuse_if_busy() {
  # The session lock file must exist (fail closed when missing) and be free.
  [ -e "$SESSION_LOCK" ] || die "session lock $SESSION_LOCK missing - fail closed"
  if ! flock -n "$SESSION_LOCK" true 2>/dev/null; then
    die "an arm session holds $SESSION_LOCK"
  fi
  local locks
  locks="$(ls $JOBS_GLOB 2>/dev/null || true)"
  [ -z "$locks" ] || die "active job locks: $locks"
  # Refuse unless every arm's motor-health file exists (fail closed when missing),
  # carries the known schema, and reports a torque-free status.
  local arm file status
  for arm in arm_a arm_b; do
    file="${MOTOR_HEALTH_DIR}/${arm}.json"
    [ -f "$file" ] || die "motor state missing (fail closed): $file"
    grep -q "\"${MOTOR_HEALTH_SCHEMA}\"" "$file" || die "unknown motor-health schema: $file"
    status="$(grep -o '"status"[[:space:]]*:[[:space:]]*"[^"]*"' "$file" \
              | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
    case "$status" in
      ended|stopped|torque_off) ;;
      *) die "arm ${arm} is not torque-free (status '${status:-unparsed}'): $file" ;;
    esac
  done
}

preconditions() {
  [ -d "$OLD_DIR" ] || die "$OLD_DIR not found (already renamed?)"
  [ -f "$OLD_DIR/compose.yaml" ] || die "$OLD_DIR/compose.yaml not found"
  [ ! -e "$NEW_DIR" ] || die "$NEW_DIR already exists"
  docker volume inspect "$OLD_VOLUME" >/dev/null 2>&1 || die "volume $OLD_VOLUME not found"
  if docker volume inspect "$NEW_VOLUME" >/dev/null 2>&1; then die "volume $NEW_VOLUME already exists"; fi
  command -v docker >/dev/null || die "docker not found"
  command -v flock >/dev/null || die "flock not found"
  refuse_if_busy
}

volume_manifest() { docker run --rm -v "$1:/data:ro" alpine sh -c \
                     'cd /data && find . -type f -print0 | sort -z | xargs -0 sha256sum'; }

stack_down_old() {
  # Down BEFORE backup and copy so sqlite/WAL inside the volume are quiescent.
  docker compose -p "$OLD_ID" --project-directory "$OLD_DIR" down --timeout 30 \
    || say "WARN: old project down had failures (was it running?)"
}

backup() {
  local stamp; stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$BACKUP_ROOT"
  cp -a "$OLD_DIR" "$BACKUP_ROOT/${OLD_ID}.${stamp}"
  docker run --rm -v "${OLD_VOLUME}:/from:ro" -v "${BACKUP_ROOT}/${OLD_VOLUME}.${stamp}:/to" \
    alpine sh -c 'cp -a /from/. /to/'
  printf '%s\n' "$stamp" > /run/rosy-rename-arm-cell.stamp
  say "backup: $BACKUP_ROOT/${OLD_ID}.${stamp} and ${BACKUP_ROOT}/${OLD_VOLUME}.${stamp}"
}

copy_volume() {
  docker volume create "$NEW_VOLUME" >/dev/null
  docker run --rm -v "${OLD_VOLUME}:/from:ro" -v "${NEW_VOLUME}:/to" alpine sh -c 'cp -a /from/. /to/'
  local old_manifest new_manifest
  old_manifest="$(volume_manifest "$OLD_VOLUME")"
  new_manifest="$(volume_manifest "$NEW_VOLUME")"
  # sha256 of every file, compared file by file (sorted manifest), not one rolled-up digest.
  [ "$old_manifest" = "$new_manifest" ] || die "sha256 mismatch after volume copy"
  say "volume copied and verified: $(printf '%s\n' "$old_manifest" | wc -l) files, every sha256 matches"
}

new_config_dir() {
  # ln -sfn onto the existing real directory would nest a link inside it: move the
  # directory to its new name, then point the old path at it with a symlink.
  mv "$OLD_DIR" "$NEW_DIR"
  if [ -f "$NEW_DIR/control-unit.yaml" ]; then
    sed -i.bak "s/\b${OLD_UNIT}\b/${NEW_UNIT}/g" "$NEW_DIR/control-unit.yaml"
  fi
  local compose="$NEW_DIR/compose.yaml"
  sed -i.bak -e "s/\b${OLD_VOLUME_KEY}\b/${NEW_VOLUME_KEY}/g" \
             -e "s/\b${OLD_NETWORK_KEY}\b/${NEW_NETWORK_KEY}/g" \
             -e "s#${OLD_DIR}\b#${NEW_DIR}#g" "$compose"
  if grep -Eq "${OLD_VOLUME_KEY}|${OLD_NETWORK_KEY}|${OLD_DIR}\b" "$compose"; then
    die "old volume/network keys or paths remain in $compose"
  fi
  grep -q "${NEW_VOLUME_KEY}" "$compose" || die "volume key ${NEW_VOLUME_KEY} missing after rewrite"
  grep -q "${NEW_NETWORK_KEY}" "$compose" || die "network key ${NEW_NETWORK_KEY} missing after rewrite"
  # /etc/rosy/control-unit/cell-a and /etc/rosy/workcell-observations stay untouched;
  # service peer-cell-a keeps its name (R's peer DNS alias depends on it).
  ln -s "$NEW_DIR" "$OLD_DIR"
  say "config: $NEW_DIR (project ${NEW_ID}), $OLD_DIR -> symlink"
}

stack_up_new() {
  docker compose -p "$NEW_ID" --project-directory "$NEW_DIR" up -d --timeout 30
}

verify_fleet_mount() {
  local cid mounts mount_point
  cid="$(docker compose -p "$NEW_ID" ps -q fleet)"
  [ -n "$cid" ] || die "fleet container not found under project ${NEW_ID}"
  mounts="$(docker inspect --format '{{range .Mounts}}{{.Name}} {{.Destination}}{{"\n"}}{{end}}' "$cid")"
  mount_point="$(printf '%s\n' "$mounts" | awk -v v="$NEW_VOLUME" '$1 == v {print $2}')"
  [ -n "$mount_point" ] || die "fleet does not mount $NEW_VOLUME - aborting and rolling back"
  say "fleet mounts $NEW_VOLUME at $mount_point"
}

verify_healthy() {
  sleep 5
  local service cid health bad=""
  for service in $SERVICES; do
    cid="$(docker compose -p "$NEW_ID" ps -q "$service" || true)"
    if [ -z "$cid" ]; then bad+="${service}=not-running "; continue; fi
    # A container without a healthcheck is NOT healthy: only an explicit healthy
    # status passes, so a missing healthcheck definition fails the switch.
    health="$(docker inspect --format \
      '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$cid")"
    [ "$health" = "healthy" ] || bad+="${service}=${health} "
  done
  if [ -n "$bad" ]; then
    die "containers not verifiably healthy under ${NEW_ID}: $bad"
  fi
  say "all ${NEW_ID} containers healthy: $SERVICES"
}

rollback() {
  say "switch failed - rolling back automatically"
  docker compose -p "$NEW_ID" --project-directory "$NEW_DIR" down --timeout 30 >/dev/null 2>&1 \
    || say "WARN: ${NEW_ID} project down had failures (may not have come up)"
  if [ -L "$OLD_DIR" ]; then
    rm "$OLD_DIR" || say "WARN: could not remove symlink $OLD_DIR"
  fi
  if [ -d "$NEW_DIR" ] && [ ! -e "$OLD_DIR" ]; then
    mv "$NEW_DIR" "$OLD_DIR" || say "WARN: could not restore $NEW_DIR to $OLD_DIR"
  fi
  docker volume rm "$NEW_VOLUME" >/dev/null 2>&1 || true
  if ! docker compose -p "$OLD_ID" --project-directory "$OLD_DIR" up -d --timeout 30; then
    say "FATAL: automatic rollback could not bring the old stack up; run it by hand:"
    say "  docker compose -p ${OLD_ID} --project-directory ${OLD_DIR} up -d --timeout 30"
    return 1
  fi
  say "rollback complete: old stack ${OLD_ID} is back up from ${OLD_DIR}"
}

main() {
  say "mode: $([ "$DRY" = 1 ] && echo DRY-RUN || echo APPLY) (operator home: $OPERATOR_HOME)"
  preconditions
  if [ "$DRY" = 1 ]; then
    say "would: bring the old stack down first (quiesce sqlite/WAL): compose -p $OLD_ID down"
    say "would: backup $OLD_DIR + volume $OLD_VOLUME to $BACKUP_ROOT"
    say "would: create volume $NEW_VOLUME, copy data, verify sha256 of every file"
    say "would: mv $OLD_DIR -> $NEW_DIR, rewrite unit id + compose keys/paths, symlink $OLD_DIR -> $NEW_DIR"
    say "would: compose -p $NEW_ID up -d, verify fleet mounts $NEW_VOLUME, check health of: $SERVICES"
    say "on any failure: automatic rollback (old stack ${OLD_ID} back up)"
    say "dry-run complete; re-run with --apply to change anything"
    exit 0
  fi
  if ! (
    stack_down_old
    backup
    copy_volume
    new_config_dir
    stack_up_new
    verify_fleet_mount
    verify_healthy
  ); then
    rollback || true
    die "switch failed and was rolled back; backups: $BACKUP_ROOT"
  fi
  say "rename complete. Update R's control-unit.yaml (peers key, manifest revision) in the same window."
  say "later step (D-1011): rename peer service peer-cell-a and R's token file r-to-cell-a.token."
}

main
