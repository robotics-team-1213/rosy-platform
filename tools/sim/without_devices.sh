#!/usr/bin/env bash
# Run a command as the calling user in a private mount namespace whose /dev holds no hardware nodes (only null,
# zero, full, random, urandom, tty and the host /dev/shm that DDS shared memory needs). For the sim cell owner on a
# test PC with cameras: its device guard stays as it is and is satisfied for real. Needs passwordless sudo
# (unprivileged user namespaces are blocked on the lab PCs). Usage: without_devices.sh ENV_FILE CMD...
# ENV_FILE is `export -p` output, re-read after the privilege drop (sudo strips LD_* and PATH).
set -euo pipefail
env_file=$1; shift
exec sudo -n unshare --mount --propagation private -- /bin/bash -euc '
uid=$1 gid=$2 env_file=$3; shift 3
shm=$(mktemp -d); mount --rbind /dev/shm "$shm"
mount -t tmpfs -o mode=755,nosuid tmpfs /dev
for node in "null 1 3" "zero 1 5" "full 1 7" "random 1 8" "urandom 1 9" "tty 5 0"; do
  read -r name major minor <<<"$node"; mknod -m 666 "/dev/$name" c "$major" "$minor"
done
mkdir /dev/shm; mount --move "$shm" /dev/shm; rmdir "$shm"
ln -s /proc/self/fd /dev/fd
exec setpriv --reuid="$uid" --regid="$gid" --init-groups /bin/bash -c ". \"\$0\"; exec \"\$@\"" "$env_file" "$@"
' _ "$(id -u)" "$(id -g)" "$env_file" "$@"
