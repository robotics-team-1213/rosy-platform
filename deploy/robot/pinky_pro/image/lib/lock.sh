#!/usr/bin/env bash
# Scalar reader for the image scripts' already-validated lock sections.
lock_value() {
    local section="$1" wanted="$2"
    awk -v section="$section" -v wanted="$wanted" '
        $0 ~ "^" section ":[[:space:]]*$" { inside=1; next }
        inside && /^[^[:space:]]/ { exit }
        inside {
            key=$1; sub(/:$/, "", key)
            if (key == wanted) { $1=""; sub(/^[[:space:]]+/, ""); sub(/\r$/, ""); print; exit }
        }
    ' "$LOCK"
}
