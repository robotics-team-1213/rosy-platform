#!/usr/bin/env bash
# D-1011 stage A: rename the arm cell runtime on the cell host (rosy-arm-cell).
#   cell-a -> arm-cell : compose project, /etc/rosy config dir, docker volume.
# DRY-RUN by default. Nothing changes unless --apply. Run as root on the cell host.
#
# Usage:
#   tools/ops/rename_arm_cell_runtime.sh            # dry-run: show what would happen
#   tools/ops/rename_arm_cell_runtime.sh --apply    # actually rename (stack down -> up)
#
# Rollback (printed at the end and on failure of any --apply step):
#   docker compose -p arm-cell --project-directory /etc/rosy/arm-cell down
#   rm /etc/rosy/cell-a            # remove the symlink (only if it is one!)
#   mv /etc/rosy/cell-a.bak.<ts> /etc/rosy/cell-a
#   docker run --rm -v arm-cell_arm_cell_data:/to -v cell-a_cell_a_data:/from alpine \
#     sh -c 'rm -rf /to/* && cp -a /from/. /to/' && docker volume rm arm-cell_arm_cell_data
#   docker compose -p cell-a --project-directory /etc/rosy/cell-a up -d
set -euo pipefail

OLD_ID="cell-a"; NEW_ID="arm-cell"
OLD_UNIT="CELL-A"; NEW_UNIT="ARM-CELL"
OLD_DIR="/etc/rosy/${OLD_ID}"; NEW_DIR="/etc/rosy/${NEW_ID}"
OLD_VOLUME="${OLD_ID}_cell_a_data"; NEW_VOLUME="${NEW_ID}_arm_cell_data"
BACKUP_ROOT="/var/backups/rosy-rename"
APPLY="${1:-}"

say() { printf '[rename-arm-cell] %s\n' "$*"; }
die() { printf '[rename-arm-cell] FATAL: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root on the cell host"
[ "$APPLY" = "--apply" ] || [ -z "$APPLY" ] || die "usage: $0 [--apply]"
DRY=$([ -z "$APPLY" ] && echo 1 || echo 0)

# --- guards: never rename while an arm session, job, or torque is live -----------
refuse_if_busy() {
  if flock -n ~/rosy-omx/session.lock true 2>/dev/null; then :; else
    die "an arm session holds ~/rosy-omx/session.lock"
  fi
  local locks
  locks="$(ls ~/rosy-jobs/*.lock 2>/dev/null || true)"
  [ -z "$locks" ] || die "active job locks: $locks"
  # any motor-health state showing torque on = arms may be holding a load
  local state
  for state in /run/rosy/omx/*/motor-health.json; do
    [ -e "$state" ] || continue
    if grep -Eq '"torque[^"]*"[[:space:]]*:[[:space:]]*(true|1|"on")' "$state" 2>/dev/null; then
      die "motor torque is on: $state"
    fi
  done
}

preconditions() {
  [ -d "$OLD_DIR" ] || die "$OLD_DIR not found (already renamed?)"
  [ ! -e "$NEW_DIR" ] || die "$NEW_DIR already exists"
  docker volume inspect "$OLD_VOLUME" >/dev/null 2>&1 || die "volume $OLD_VOLUME not found"
  docker volume inspect "$NEW_VOLUME" >/dev/null 2>&1 && die "volume $NEW_VOLUME already exists" || true
  command -v docker >/dev/null || die "docker not found"
  refuse_if_busy
}

volume_file_count() { docker run --rm -v "$1:/data:ro" alpine sh -c 'find /data -type f | wc -l'; }
volume_sha256()    { docker run --rm -v "$1:/data:ro" alpine sh -c \
                      'cd /data && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum'; }

backup() {
  local stamp; stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$BACKUP_ROOT"
  cp -a "$OLD_DIR" "$BACKUP_ROOT/${OLD_ID}.${stamp}"
  docker run --rm -v "${OLD_VOLUME}:/from:ro" -v "${BACKUP_ROOT}/${OLD_VOLUME}.${stamp}:/to" \
    alpine sh -c 'cp -a /from/. /to/'
  say "backup: $BACKUP_ROOT/${OLD_ID}.${stamp} and ${BACKUP_ROOT}/${OLD_VOLUME}.${stamp}"
  printf '%s\n' "$stamp" > /run/rosy-rename-arm-cell.stamp
}

copy_volume() {
  docker volume create "$NEW_VOLUME" >/dev/null
  docker run --rm -v "${OLD_VOLUME}:/from:ro" -v "${NEW_VOLUME}:/to" alpine sh -c 'cp -a /from/. /to/'
  local old_n new_n old_s new_s
  old_n="$(volume_file_count "$OLD_VOLUME")"; new_n="$(volume_file_count "$NEW_VOLUME")"
  old_s="$(volume_sha256 "$OLD_VOLUME")";     new_s="$(volume_sha256 "$NEW_VOLUME")"
  [ "$old_n" = "$new_n" ] || die "file count mismatch after copy: $old_n vs $new_n"
  [ "$old_s" = "$new_s" ] || die "sha256 mismatch after copy"
  say "volume copied and verified: $new_n files, digest ${new_s%% *}"
}

new_config_dir() {
  cp -a "$OLD_DIR" "$NEW_DIR"
  # unit id and compose project rename inside the copied config; peer names keep R as-is
  if [ -f "$NEW_DIR/control-unit.yaml" ]; then
    sed -i.bak "s/\b${OLD_UNIT}\b/${NEW_UNIT}/g" "$NEW_DIR/control-unit.yaml"
  fi
  ln -sfn "$NEW_DIR" "$OLD_DIR"   # old path stays reachable as a symlink
  say "config: $NEW_DIR created (project ${NEW_ID}), $OLD_DIR -> symlink"
}

stack_down_up() {
  docker compose -p "$OLD_ID" --project-directory "$OLD_DIR" down --timeout 30 \
    || say "WARN: old project down had failures (was it running?)"
  docker compose -p "$NEW_ID" --project-directory "$NEW_DIR" up -d --timeout 30
}

verify_healthy() {
  sleep 5
  local bad
  bad="$(docker compose -p "$NEW_ID" ps --format '{{.Name}} {{.Health}} {{.State}}' \
        | grep -v ' healthy running' || true)"
  [ -z "$bad" ] || die "containers not healthy under ${NEW_ID}:
$bad"
  say "all ${NEW_ID} containers healthy"
}

rollback_help() {
  cat <<EOF
[rename-arm-cell] ROLLBACK commands:
  docker compose -p ${NEW_ID} --project-directory ${NEW_DIR} down --timeout 30
  rm ${NEW_DIR}   # remove the copied dir (keep the backup!)
  [ -L ${OLD_DIR} ] && rm ${OLD_DIR}   # remove the symlink only if it is one
  docker volume rm ${NEW_VOLUME}
  docker compose -p ${OLD_ID} --project-directory ${OLD_DIR} up -d --timeout 30
  backups: ${BACKUP_ROOT}/ (config + volume snapshots)
EOF
}

main() {
  say "mode: $([ "$DRY" = 1 ] && echo DRY-RUN || echo APPLY)"
  preconditions
  if [ "$DRY" = 1 ]; then
    say "would: backup $OLD_DIR + volume $OLD_VOLUME to $BACKUP_ROOT"
    say "would: create volume $NEW_VOLUME, copy data, verify file counts + sha256"
    say "would: create $NEW_DIR (project ${NEW_ID}), keep $OLD_DIR as symlink"
    say "would: compose -p $OLD_ID down, compose -p $NEW_ID up -d, check health"
    rollback_help
    say "dry-run complete; re-run with --apply to change anything"
    exit 0
  fi
  backup
  copy_volume
  new_config_dir
  if ! stack_down_up || ! verify_healthy; then
    rollback_help
    die "switch failed; follow the rollback commands above"
  fi
  rollback_help
  say "rename complete. Update R's control-unit.yaml (peers key, manifest revision) in the same window."
}

main
