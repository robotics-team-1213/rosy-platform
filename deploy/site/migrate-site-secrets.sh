#!/bin/sh
# Move the site secrets out of the config dir (D-524 security review). Run as root on the site PC.
#   sudo sh migrate-site-secrets.sh [--dry-run]
# Idempotent; mv keeps owners and modes. Moves /etc/rosy/site/secrets to /etc/rosy/site-secrets, points ROSY_SITE_SECRETS_DIR
# in site.env at it, and leaves a symlink at the old path for host units not yet updated. The
# symlink is safe: Vision mounts only site-cameras.yaml, and Fleet already owns these secrets.
# Then restart the stack: systemctl restart rosy-site-stack.service
set -eu
OLD=/etc/rosy/site/secrets
NEW=/etc/rosy/site-secrets
ENVF=/etc/rosy/site/site.env
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
run() { if [ "$DRY" = 1 ]; then echo "+ $*"; else "$@"; fi; }
[ "$(id -u)" = 0 ] || [ "$DRY" = 1 ] || { echo "run as root" >&2; exit 1; }

if [ -d "$OLD" ] && [ ! -L "$OLD" ]; then
  [ ! -e "$NEW" ] || { echo "both $OLD and $NEW exist; merge by hand" >&2; exit 1; }
  run mv "$OLD" "$NEW"
  run ln -s "$NEW" "$OLD"
fi
if [ -f "$ENVF" ] && grep -q '^ROSY_SITE_SECRETS_DIR=' "$ENVF"; then
  run sed -i "s#^ROSY_SITE_SECRETS_DIR=.*#ROSY_SITE_SECRETS_DIR=$NEW#" "$ENVF"
fi
echo "secrets dir: $NEW"
