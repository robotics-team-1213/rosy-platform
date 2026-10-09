#!/usr/bin/env bash
# Service Control (D-524) on one Ubuntu host: site, ai, or model. Run once on each PC:
#
#   sudo deploy/site/install-host-control.sh --role site|ai|model [--dry-run] \
#        [--fleet-key "ssh-ed25519 AAAA... rosy-host-control" --from "<site PC address>,<docker subnet>"] \
#        [--make-fleet-key] [--units-user NAME]
#
# Installs, root-owned:
#   /usr/local/sbin/rosy-host-control         the allowlisted helper
#   /usr/local/sbin/rosy-host-control-remote  the forced command for the Fleet key
#   /etc/rosy/host-control/role               the role; the helper reads it, not the env
#   /etc/rosy/host-control/units-user         ai only: owner of the Pinky user units
#                                             (--units-user, default the login user)
#   /etc/sudoers.d/rosy-host-control          "<login user> ALL=(root) NOPASSWD: <helper>"
# With --fleet-key (and the required --from, an sshd `from=` pattern list: the site PC's
# address and, on the site PC itself, the Docker bridge subnet), the login user's
# authorized_keys gets one line that can run nothing but the forced command (same pattern as
# install-model-pc-guard.sh). A line holding the same key without exactly these options is
# replaced, with a warning.
# --make-fleet-key (site only) creates /etc/rosy/fleet-host-control/id_ed25519 when absent,
# root:10001 0440. That directory is outside the site config dir, so only the Fleet
# container mounts it (compose.yaml), never Vision. Prints the public key for --fleet-key.
# Then, on the site PC, write /etc/rosy/fleet-host-control/targets (`<role> <user>@<host
# name>` per line) and known_hosts (ssh-keyscan of each host name), and restart the stack.
# --from on each PC (D-530, applied 2026-10-09): site PC = the Docker pool 172.16.0.0/12 (the compose
# subnet changes when the stack restarts); model and AI PCs = "<site PC LAN address>". Targets use LAN
# addresses, not tailnet names: Tailscale SSH bypasses authorized_keys forced commands.
# Idempotent. --dry-run prints what would change and needs no root.
set -euo pipefail

DRY=0
ROLE=""
FLEET_KEY=""
FROM=""
MAKE_KEY=0
UNITS_USER=""
FLEET_DIR=/etc/rosy/fleet-host-control
USER_NAME=${SUDO_USER:-rosy}
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --role) ROLE=$2; shift ;;
    --fleet-key) FLEET_KEY=$2; shift ;;
    --from) FROM=$2; shift ;;
    --make-fleet-key) MAKE_KEY=1 ;;
    --units-user) UNITS_USER=$2; shift ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
case "$ROLE" in site|ai|model) ;; *) echo "--role site|ai|model is required" >&2; exit 2 ;; esac
if [ -n "$FLEET_KEY" ] && ! [[ "$FROM" =~ ^[0-9A-Fa-f.:/,*?-]+$ ]]; then
  echo "--fleet-key needs --from \"<site PC address>,<docker subnet>\"" >&2; exit 2
fi
HERE=$(cd "$(dirname "$0")" && pwd)
run() { if [ "$DRY" = 1 ]; then echo "+ $*"; else "$@"; fi; }
put() {  # put <path> <mode> <content>
  if [ "$DRY" = 1 ]; then echo "+ write $1 ($2)"; printf '%s\n' "$3" | sed 's/^/    /'; return; fi
  printf '%s\n' "$3" > "$1.tmp" && chmod "$2" "$1.tmp" && chown root:root "$1.tmp" && mv "$1.tmp" "$1"
}
[ "$DRY" = 1 ] || [ "$(id -u)" = 0 ] || { echo "run with sudo (or --dry-run)" >&2; exit 1; }

run install -o root -g root -m 0755 "$HERE/rosy-host-control" /usr/local/sbin/rosy-host-control
run install -o root -g root -m 0755 "$HERE/rosy-host-control-remote" /usr/local/sbin/rosy-host-control-remote
run install -d -o root -g root -m 0755 /etc/rosy /etc/rosy/host-control
put /etc/rosy/host-control/role 0644 "$ROLE"
[ "$ROLE" != ai ] || put /etc/rosy/host-control/units-user 0644 "${UNITS_USER:-$USER_NAME}"
put /etc/sudoers.d/rosy-host-control 0440 "$USER_NAME ALL=(root) NOPASSWD: /usr/local/sbin/rosy-host-control"
[ "$DRY" = 1 ] || visudo -cf /etc/sudoers.d/rosy-host-control >/dev/null

if [ -n "$FLEET_KEY" ]; then
  KEYS=/home/$USER_NAME/.ssh/authorized_keys
  LINE="from=\"$FROM\",command=\"/usr/local/sbin/rosy-host-control-remote\",restrict $FLEET_KEY"
  if [ "$DRY" = 1 ]; then echo "+ set in $KEYS: $LINE"
  elif ! grep -qxF "$LINE" "$KEYS" 2>/dev/null; then
    install -d -m 0700 -o "$USER_NAME" -g "$USER_NAME" "/home/$USER_NAME/.ssh"
    if grep -qF "$FLEET_KEY" "$KEYS" 2>/dev/null; then
      echo "warning: replacing a $KEYS line that holds the Fleet key with other options" >&2
      grep -vF "$FLEET_KEY" "$KEYS" > "$KEYS.tmp" || true
      mv "$KEYS.tmp" "$KEYS"
    fi
    printf '%s\n' "$LINE" >> "$KEYS" && chown "$USER_NAME:$USER_NAME" "$KEYS" && chmod 0600 "$KEYS"
  fi
fi

if [ "$MAKE_KEY" = 1 ]; then
  [ "$ROLE" = site ] || { echo "--make-fleet-key is for the site PC" >&2; exit 2; }
  KEY=$FLEET_DIR/id_ed25519
  run install -d -o root -g 10001 -m 0750 "$FLEET_DIR"
  if [ ! -f "$KEY" ]; then
    run ssh-keygen -q -t ed25519 -N "" -C rosy-host-control -f "$KEY"
    run chown root:10001 "$KEY"
    run chmod 0440 "$KEY"
  fi
  echo "Fleet Service Control public key (give to --fleet-key on site, ai, and model):"
  [ "$DRY" = 1 ] || cat "$KEY.pub"
fi
echo "done. Check: sudo -l -U $USER_NAME; cat /etc/rosy/host-control/role"
