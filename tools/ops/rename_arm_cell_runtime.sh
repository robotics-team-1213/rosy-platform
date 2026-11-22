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
# Rollback uses the untouched old configuration and volume. The failed copy
# and backup are retained for inspection under the new name and BACKUP_ROOT.
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
COMPOSE_NAMES=(compose.yaml)
COMPOSE_ENV=""
BACKUP_ROOT="/var/backups/rosy-rename"
OPERATOR_HOME="${OPERATOR_HOME:-/home/robttt}"  # host operator user; never ~ (script runs as root)
SESSION_LOCK="${OPERATOR_HOME}/rosy-omx/session.lock"
JOB_DIR="${OPERATOR_HOME}/rosy-jobs"
MOTOR_HEALTH_DIR="${OPERATOR_HOME}/.local/state/rosy/motor-health"
BACKUP_DIR=""
ORIGINAL_DIR=""
NEW_STACK_STARTED=0
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
  exec {SESSION_FD}<"$SESSION_LOCK"
  if ! flock -nx "$SESSION_FD"; then
    die "an arm session holds $SESSION_LOCK"
  fi
  [ -d "$JOB_DIR" ] && [ -r "$JOB_DIR" ] && [ -x "$JOB_DIR" ] || die "cannot inspect the job lock directory"
  local -a locks
  shopt -s nullglob
  locks=("$JOB_DIR"/*.lock)
  shopt -u nullglob
  [ "${#locks[@]}" -eq 0 ] || die "active job locks"
  # Terminal snapshots can be old and are not current bus measurements.
  python3 - "$MOTOR_HEALTH_DIR" <<'PY'
import json
import sys
import time
from pathlib import Path

now = time.time()
for arm in ("arm_a", "arm_b", "arm_s"):
    try:
        health = json.loads((Path(sys.argv[1]) / f"{arm}.json").read_text())
        motors = health["motors"]
        measured = (
            health["schema_version"] == "rosy.motor-health.v1"
            and health["owner_id"] == arm
            and health["status"] == "active"
            and 0 <= now - health["observed_at"] <= 10
            and len(motors) == health["expected_motor_count"] == 6
            and {motor["id"] for motor in motors} == set(range(11, 17))
            and all(
                motor["group"] == arm
                and motor["observed_at"] == health["observed_at"]
                and motor["fault"] is False
                and motor["torque_enabled"] is False
                for motor in motors
            )
        )
    except (OSError, ValueError, KeyError, TypeError):
        measured = False
    if not measured:
        sys.exit(f"[rename-arm-cell] FATAL: {arm} lacks fresh complete passive torque-OFF evidence")
PY
}

compose() {
  local project="$1" directory="$2" name
  local -a args=(-p "$project" --project-directory "$directory")
  shift 2
  if [ -n "$COMPOSE_ENV" ]; then args+=(--env-file "$directory/$COMPOSE_ENV"); fi
  for name in "${COMPOSE_NAMES[@]}"; do args+=(-f "$directory/$name"); done
  docker compose "${args[@]}" "$@"
}

verify_old_compose() {
  local id provenance first="" name
  local -a containers
  id="$(docker ps -aq --filter "label=com.docker.compose.project=$OLD_ID")"
  readarray -t containers <<<"$id"
  [ "${#containers[@]}" -eq 3 ] || die "unexpected live Compose service set in $OLD_ID"
  for id in "${containers[@]}"; do
    provenance="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}|{{index .Config.Labels "com.docker.compose.project.working_dir"}}|{{index .Config.Labels "com.docker.compose.project.environment_file"}}' "$id")"
    [ -z "$first" ] || [ "$provenance" = "$first" ] || die "live Compose provenance differs across containers"
    first="$provenance"
  done
  case "$first" in
    "$OLD_DIR/compose.yaml|$OLD_DIR|") ;;
    "$OLD_DIR/compose.yaml|$OLD_DIR|$OLD_DIR/.env") COMPOSE_ENV=".env" ;;
    "$OLD_DIR/compose.yaml,$OLD_DIR/compose.d1039.yaml|$OLD_DIR|$OLD_DIR/cell-a.env")
      COMPOSE_NAMES+=(compose.d1039.yaml)
      COMPOSE_ENV="cell-a.env"
      ;;
    *) die "live Compose provenance differs from the supported layouts" ;;
  esac
  for name in "${COMPOSE_NAMES[@]}" ${COMPOSE_ENV:+"$COMPOSE_ENV"}; do
    [ -f "$OLD_DIR/$name" ] && [ ! -L "$OLD_DIR/$name" ] || die "missing or symlinked Compose input: $name"
  done
  compose "$OLD_ID" "$OLD_DIR" config --quiet
  verify_fleet_mount "$OLD_ID" "$OLD_DIR" "$OLD_VOLUME"
  verify_healthy "$OLD_ID" "$OLD_DIR"
}

refuse_legacy_updater() {
  local unit state key value loaded active installed
  for unit in rosy-cell-autoupdate.timer rosy-cell-autoupdate.service; do
    state="$(systemctl show --property=LoadState,ActiveState,UnitFileState "$unit")" ||
      die "cannot verify legacy updater unit $unit"
    loaded= active= installed=
    while IFS='=' read -r key value; do
      case "$key" in
        LoadState) loaded="$value" ;;
        ActiveState) active="$value" ;;
        UnitFileState) installed="$value" ;;
      esac
    done <<<"$state"
    case "$active" in
      inactive|failed) ;;
      *) die "legacy updater $unit is active or unverified" ;;
    esac
    case "$loaded:$installed" in
      not-found:|loaded:disabled|masked:masked|masked:masked-runtime|loaded:masked|loaded:masked-runtime) ;;
      loaded:static) [ "$unit" = rosy-cell-autoupdate.service ] || die "legacy updater $unit is not disabled" ;;
      *) die "legacy updater $unit is enabled or unverified" ;;
    esac
  done
}

preconditions() {
  [ -d "$OLD_DIR" ] || die "$OLD_DIR not found (already renamed?)"
  [ -f "$OLD_DIR/compose.yaml" ] || die "$OLD_DIR/compose.yaml not found"
  [ ! -e "$NEW_DIR" ] && [ ! -L "$NEW_DIR" ] || die "$NEW_DIR already exists"
  command -v docker >/dev/null || die "docker not found"
  command -v flock >/dev/null || die "flock not found"
  docker volume inspect "$OLD_VOLUME" >/dev/null 2>&1 || die "volume $OLD_VOLUME not found"
  if docker volume inspect "$NEW_VOLUME" >/dev/null 2>&1; then die "volume $NEW_VOLUME already exists"; fi
  refuse_legacy_updater
  verify_old_compose
  refuse_if_busy
  if [ "$DRY" = 0 ] && [ "${#COMPOSE_NAMES[@]}" -gt 1 ]; then
    die "live overlay switch requires an authenticated peer check, a ledger write fence and updater handover"
  fi
}

volume_manifest() { docker run --rm -v "$1:/data:ro" alpine sh -ec \
                     'set -o pipefail; cd /data; find . -type f -print0 | sort -z | xargs -0 -r sha256sum'; }

stack_down_old() {
  # Down BEFORE backup and copy so sqlite/WAL inside the volume are quiescent.
  local running
  compose "$OLD_ID" "$OLD_DIR" down --timeout 30
  running="$(docker ps -q --filter "volume=$OLD_VOLUME")"
  [ -z "$running" ] || die "old volume still has a running consumer"
}

backup() {
  mkdir -p "$BACKUP_ROOT"
  BACKUP_DIR="$(mktemp -d "$BACKUP_ROOT/$OLD_ID.XXXXXXXX")"
  cp -a "$OLD_DIR" "$BACKUP_DIR/config"
  mkdir "$BACKUP_DIR/data"
  docker run --rm -v "${OLD_VOLUME}:/from:ro" -v "$BACKUP_DIR/data:/to" \
    alpine sh -c 'cp -a /from/. /to/'
  say "backup: $BACKUP_DIR"
}

copy_volume() {
  local old_manifest backup_manifest new_manifest
  old_manifest="$(volume_manifest "$OLD_VOLUME")"
  backup_manifest="$(volume_manifest "$BACKUP_DIR/data")"
  [ -n "$old_manifest" ] && [ "$old_manifest" = "$backup_manifest" ] || die "missing or mismatched backup file hashes"
  docker volume create "$NEW_VOLUME" >/dev/null
  docker run --rm -v "${OLD_VOLUME}:/from:ro" -v "${NEW_VOLUME}:/to" alpine sh -c 'cp -a /from/. /to/'
  new_manifest="$(volume_manifest "$NEW_VOLUME")"
  # sha256 of every file, compared file by file (sorted manifest), not one rolled-up digest.
  [ -n "$old_manifest" ] && [ "$old_manifest" = "$new_manifest" ] || die "missing or mismatched file hashes after volume copy"
  say "volume copied and verified: $(printf '%s\n' "$old_manifest" | wc -l) files, every sha256 matches"
}

new_config_dir() {
  # Keep the original Compose and configuration intact until verification passes.
  cp -a "$OLD_DIR" "$NEW_DIR"
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
  compose "$NEW_ID" "$NEW_DIR" config --quiet
}

stack_up_new() {
  NEW_STACK_STARTED=1
  compose "$NEW_ID" "$NEW_DIR" up -d --wait --wait-timeout 30
}

verify_fleet_mount() {
  local project="$1" directory="$2" volume="$3" cid mount
  cid="$(compose "$project" "$directory" ps -q fleet)" || return 1
  [ -n "$cid" ] || { say "fleet container not found under $project"; return 1; }
  mount="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/rosy"}}{{.Name}}{{end}}{{end}}' "$cid")" || return 1
  [ "$mount" = "$volume" ] || { say "fleet does not mount $volume at /var/lib/rosy"; return 1; }
}

verify_healthy() {
  local project="$1" directory="$2" service cid health bad=""
  for service in $SERVICES; do
    cid="$(compose "$project" "$directory" ps -q "$service")" || return 1
    if [ -z "$cid" ]; then bad+="${service}=not-running "; continue; fi
    # A container without a healthcheck is NOT healthy: only an explicit healthy
    # status passes, so a missing healthcheck definition fails the switch.
    health="$(docker inspect --format \
      '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$cid")" || return 1
    [ "$health" = "healthy" ] || bad+="${service}=${health} "
  done
  if [ -n "$bad" ]; then
    say "FATAL: containers not verifiably healthy under $project: $bad"
    return 1
  fi
  say "all $project containers healthy: $SERVICES"
}

rollback() {
  say "switch failed - rolling back automatically"
  if [ "$NEW_STACK_STARTED" -eq 1 ]; then
    compose "$NEW_ID" "$NEW_DIR" down --timeout 30 || return 1
    local running
    running="$(docker ps -q --filter "label=com.docker.compose.project=$NEW_ID")" || return 1
    [ -z "$running" ] || return 1
  fi
  if [ -n "$ORIGINAL_DIR" ] && [ -d "$ORIGINAL_DIR" ]; then
    if [ -L "$OLD_DIR" ]; then
      [ "$(readlink "$OLD_DIR")" = "$NEW_DIR" ] && unlink "$OLD_DIR" || return 1
    fi
    [ ! -e "$OLD_DIR" ] && mv "$ORIGINAL_DIR" "$OLD_DIR" || return 1
  fi
  compose "$OLD_ID" "$OLD_DIR" up -d --wait --wait-timeout 30 || return 1
  verify_fleet_mount "$OLD_ID" "$OLD_DIR" "$OLD_VOLUME" || return 1
  verify_healthy "$OLD_ID" "$OLD_DIR" || return 1
  say "rollback verified: old stack uses $OLD_VOLUME and original configuration"
}

on_exit() {
  local status=$?
  trap - EXIT
  if [ "$status" -ne 0 ] && ! rollback; then
    say "FATAL: rollback could not be verified. Both data volumes were retained."
  fi
  exit "$status"
}

main() {
  local original_parent
  say "mode: $([ "$DRY" = 1 ] && echo DRY-RUN || echo APPLY) (operator home: $OPERATOR_HOME)"
  preconditions
  if [ "$DRY" = 1 ]; then
    say "would: bring the old stack down first (quiesce sqlite/WAL): compose -p $OLD_ID down"
    say "would: backup $OLD_DIR + volume $OLD_VOLUME to $BACKUP_ROOT"
    say "would: create volume $NEW_VOLUME, copy data, verify sha256 of every file"
    say "would: copy and rewrite Compose under $NEW_DIR, retain $OLD_DIR until verification"
    say "would: start $NEW_ID, verify its volume and health, then replace $OLD_DIR with a symlink"
    say "on failure: stop the new stack before restoring the original, retain both volumes"
    say "dry-run complete; re-run with --apply to change anything"
    exit 0
  fi
  trap on_exit EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  stack_down_old
  backup
  copy_volume
  new_config_dir
  stack_up_new
  verify_fleet_mount "$NEW_ID" "$NEW_DIR" "$NEW_VOLUME"
  verify_healthy "$NEW_ID" "$NEW_DIR"
  # Keep the final directory move atomic even if /etc and the backup root differ.
  original_parent="$(mktemp -d "$OLD_DIR.original.XXXXXXXX")"
  ORIGINAL_DIR="$original_parent/config"
  mv "$OLD_DIR" "$ORIGINAL_DIR"
  ln -s "$NEW_DIR" "$OLD_DIR"
  trap - EXIT INT TERM
  say "rename complete. Update R's control-unit.yaml (peers key, manifest revision) in the same window."
  say "later step (D-1011): rename peer service peer-cell-a and R's token file r-to-cell-a.token."
}

main
