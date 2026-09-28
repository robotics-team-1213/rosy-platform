#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROSY_ENV_FILE:-$SCRIPT_DIR/.env}"
ACTION="${1:-}"
MODE="${ROSY_RUNTIME_MODE:-core}"
BACKEND="${ROSY_NAVIGATION_BACKEND:-}"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "error: Rosy environment file not found: $ENV_FILE" >&2
    exit 1
fi

if [[ -z "${ROSY_RUNTIME_MODE+x}" ]]; then
    configured_mode="$(sed -n 's/^ROSY_RUNTIME_MODE=//p' "$ENV_FILE" | tail -n 1)"
    configured_mode="${configured_mode%$'\r'}"
    MODE="${configured_mode:-core}"
fi

if [[ -z "$BACKEND" ]]; then
    configured_backend="$(sed -n 's/^ROSY_NAVIGATION_BACKEND=//p' "$ENV_FILE" | tail -n 1)"
    configured_backend="${configured_backend%$'\r'}"
    BACKEND="${configured_backend:-localization}"
fi

cd "$SCRIPT_DIR"

# shellcheck source=config/resolve-mode.sh
source "$SCRIPT_DIR/config/resolve-mode.sh"
MODE="$(resolve_runtime_mode "$MODE" "$SCRIPT_DIR/config/board.yaml")" || exit 2
export ROSY_RUNTIME_MODE="$MODE"

case "$BACKEND" in
    localization|slam)
        ;;
    *)
        echo "error: ROSY_NAVIGATION_BACKEND must be localization|slam, got '$BACKEND'" >&2
        exit 2
        ;;
esac
if [[ "$BACKEND" == "slam" && "$MODE" != "hardware" ]]; then
    echo "error: slam backend requires hardware runtime mode" >&2
    exit 2
fi
export ROSY_NAVIGATION_BACKEND="$BACKEND"

compose() {
    docker compose --env-file "$ENV_FILE" "$@"
}

if [[ "$BACKEND" == "slam" ]]; then
    ROSY_CAPABILITIES_FILE="capabilities.hardware-mapping.yaml"
    ROSY_MAPS_MOUNT_MODE=rw
else
    ROSY_CAPABILITIES_FILE="capabilities.${MODE}.yaml"
    ROSY_MAPS_MOUNT_MODE=ro
fi
export ROSY_CAPABILITIES_FILE ROSY_MAPS_MOUNT_MODE

CAP_FILE="$SCRIPT_DIR/config/$ROSY_CAPABILITIES_FILE"
PROF_FILE="$SCRIPT_DIR/config/profile.${MODE}.yaml"
if [[ ! -f "$CAP_FILE" || ! -f "$PROF_FILE" ]]; then
    echo "error: missing board overlay for mode '$MODE' ($CAP_FILE / $PROF_FILE)" >&2
    exit 2
fi

case "$ACTION" in
    up)
        if [[ "$MODE" == "core" ]]; then
            compose up -d --remove-orphans rosy-core
        elif [[ "$MODE" == "motor" ]]; then
            compose --profile motor up -d --remove-orphans rosy-core rosy-motor
        else
            compose --profile hardware up -d --remove-orphans
        fi
        ;;
    down)
        compose --profile motor --profile hardware down --timeout 10
        ;;
    status)
        compose --profile motor --profile hardware ps
        ;;
    *)
        echo "usage: $0 {up|down|status}" >&2
        exit 2
        ;;
esac
