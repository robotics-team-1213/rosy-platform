#!/usr/bin/env bash
# D-1011 stage A: rename the arm cell runtime on the cell host (rosy-arm-cell).
#   cell-a -> arm-cell : compose project, /etc/rosy config dir, docker volume.
# Read-only preflight. Run as root on the cell host.
#
# Usage:
#   OPERATOR_HOME=/home/robttt tools/ops/rename_arm_cell_runtime.sh
#
# The script runs as root via sudo; the operator user's facts (session lock, job
# locks, motor-health state) live under OPERATOR_HOME (default /home/robttt).
# peer-cell-a keeps its compose service name: R's peer DNS alias depends on it.
# Renaming peer-cell-a / r-to-cell-a.token is a later step (D-1011).

set -euo pipefail

OLD_ID="cell-a"; NEW_ID="arm-cell"
OLD_DIR="/etc/rosy/${OLD_ID}"; NEW_DIR="/etc/rosy/${NEW_ID}"
OLD_VOLUME="${OLD_ID}_cell_a_data"; NEW_VOLUME="${NEW_ID}_arm_cell_data"
# Real compose.yaml facts (2026-11-10): services fleet/vision/peer-cell-a, volume key
# cell_a_data mounted at /var/lib/rosy, network key cell_a_backend plus the external
# rosy-control-peers. Paths reference /etc/rosy/cell-a/..., /etc/rosy/control-unit/cell-a
# and /etc/rosy/workcell-observations/... (the latter two stay as they are).
SERVICES="fleet vision peer-cell-a"
COMPOSE_NAMES=(compose.yaml)
COMPOSE_ENV=""
OPERATOR_HOME="${OPERATOR_HOME:-/home/robttt}"  # host operator user; never ~ (script runs as root)
SESSION_LOCK="${OPERATOR_HOME}/rosy-omx/session.lock"
JOB_DIR="${OPERATOR_HOME}/rosy-jobs"
MOTOR_HEALTH_DIR="${OPERATOR_HOME}/.local/state/rosy/motor-health"

say() { printf '[rename-arm-cell] %s\n' "$*"; }
die() { printf '[rename-arm-cell] FATAL: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root on the cell host"
[ "$#" -eq 0 ] || die "preflight only; live switch requires a ledger write fence, authenticated peer checks and updater handover"

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

main() {
  say "mode: preflight (operator home: $OPERATOR_HOME)"
  preconditions
  say "preflight passed; live switch still requires a ledger write fence, authenticated peer checks and updater handover"
}

main
