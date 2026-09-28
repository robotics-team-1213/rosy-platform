#!/usr/bin/env bash
# Explicit bootstrap, independent of the future GitHub repository.
set -euo pipefail
[[ "${EUID}" == 0 ]] || { echo 'run as root on the prepared Pi host' >&2; exit 1; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${1:-}" in
    '') ;;
    --activate-boot)
        /usr/local/bin/rosy-release status --json | python3 -c \
            'import json,sys; s=json.load(sys.stdin); sys.exit(0 if s.get("activation") and not s.get("recovery_hold") else 1)'
        systemctl stop rosy-runtime.service
        install -m 0644 "$SCRIPT_DIR/rosy-release-runtime.service" /etc/systemd/system/rosy-runtime.service
        install -m 0644 "$SCRIPT_DIR/rosy-release-recovery.service" /etc/systemd/system/rosy-release-recover.service
        systemctl daemon-reload
        systemctl enable --now rosy-runtime.service
        exit 0
        ;;
    *) echo 'usage: install-update-tools.sh [--activate-boot]' >&2; exit 2 ;;
esac
command -v python3 >/dev/null
command -v openssl >/dev/null
command -v zstd >/dev/null
install -d -m 0755 /opt/rosy/deploy/release /etc/rosy /var/cache/rosy /var/lib/rosy
install -d -m 0755 /etc/rosy/trusted-release-keys
SOURCE="$(cd "$SCRIPT_DIR/../release" && pwd)"
if [[ "$SOURCE" != /opt/rosy/deploy/release ]]; then
    install -m 0644 "$SOURCE/"*.py /opt/rosy/deploy/release/
    install -m 0644 "$SOURCE/manifest.schema.json" /opt/rosy/deploy/release/
fi
install -m 0755 "$SCRIPT_DIR/rosy-release" /usr/local/bin/rosy-release
install -m 0644 "$SCRIPT_DIR/rosy-update-check.service" /etc/systemd/system/
install -m 0644 "$SCRIPT_DIR/rosy-update-check.timer" /etc/systemd/system/
systemctl daemon-reload
echo 'Update tools installed. Timer and managed boot are not enabled until enrollment.'
