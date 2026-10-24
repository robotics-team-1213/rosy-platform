#!/usr/bin/env bash
# Install the native runtime support tree into DESTINATION so it runs without
# the repository around it (D-174 F1). The image build installs two copies:
# the immutable /opt/rosy/native-runtime and the per-release
# deploy/robot/native in a release. Both must import their helpers from their own directory.
set -euo pipefail

[[ $# -eq 1 ]] || { echo "usage: $0 DESTINATION" >&2; exit 2; }
DESTINATION="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_TOOLS="$(cd "$SCRIPT_DIR/../release" && pwd)"

[[ ! -e "$DESTINATION" ]] || { echo "destination already exists: $DESTINATION" >&2; exit 1; }
mkdir -p "$(dirname "$DESTINATION")"
cp -a "$SCRIPT_DIR" "$DESTINATION"
[[ -f "$DESTINATION/mapping_approval.py" ]] || {
    echo "native mapping_approval.py is missing" >&2
    exit 1
}
find "$DESTINATION" -name '__pycache__' -type d -prune -exec rm -rf {} +
# Build-time only: it resolves ../release, which does not exist on a device.
rm -f -- "$DESTINATION/install-native-runtime.sh"
# native_release.py imports signing; it is standard-library only.
cp "$RELEASE_TOOLS/signing.py" "$DESTINATION/signing.py"
for helper in host_agent.py host_agent_server.py host_lane_perception.py ssh_pairing.py network.py network_transaction.py nm_network.py; do
    cp "$RELEASE_TOOLS/$helper" "$DESTINATION/$helper"
done
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
mkdir -p "$DESTINATION/recovery-web"
cp "$REPO_ROOT/shared/web/tokens.css" "$REPO_ROOT/shared/web/components.css" "$DESTINATION/recovery-web/"
# Old clients first receive the bridge without installing feature services.
if [[ "${ROSY_BOOT_SUPPORT:-feature}" == bridge ]]; then
    rm -f -- "$DESTINATION/rosy-network-users.service" "$DESTINATION/rosy-network-agent.service" \
        "$DESTINATION/rosy-network-recovery.service" "$DESTINATION/rosy-network-recovery.timer"
else
    python3 -B "$DESTINATION/image_layer_boot.py" build-catalog \
        --source "$SCRIPT_DIR/../image/first-boot" --destination "$DESTINATION/image-layer/boot"
fi
# D-805: the site-wide update gate rosy-auto-update.service checks first (one source for every host).
cp "$SCRIPT_DIR/../../../hosts/common/host-state/rosy-update-gate" "$DESTINATION/rosy-update-gate"
cp "$SCRIPT_DIR/../../../hosts/common/rosy_time_sync.py" "$DESTINATION/rosy_time_sync.py"
# D-388: the udev rules and modprobe options the image installs, carried in
# every copy so sync-image-layer.py has a signed source for them on a robot
# that only receives payload releases.
mkdir -p "$DESTINATION/image-layer/udev" "$DESTINATION/image-layer/modprobe"
cp "$SCRIPT_DIR/../udev/"*.rules "$DESTINATION/image-layer/udev/"
cp "$SCRIPT_DIR/../modprobe/"*.conf "$DESTINATION/image-layer/modprobe/"
