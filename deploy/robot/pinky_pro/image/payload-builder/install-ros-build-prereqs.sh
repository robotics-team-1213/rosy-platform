#!/usr/bin/env bash
# D-553 addendum 3: the native ROS build prerequisites of a Pinky payload build,
# run as root inside the payload-builder image (make-builder-image.sh). Moved
# verbatim from the build-native-payload.yml step it replaced: the ROS apt
# source is checksum-pinned, ROS comes only from the image lock's dated
# snapshot (D-482) and the snapshot key is pinned by fingerprint.
# Run from the repository root (it reads deploy/robot/pinky_pro/image/inputs.lock.yaml).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
# Runner only (throwaway disk): no fsync per unpacked file and no
# man-db rebuild per apt transaction. The image build never sees this.
echo force-unsafe-io | tee /etc/dpkg/dpkg.cfg.d/90-rosy-ci-unsafe-io > /dev/null
rm -f /var/lib/man-db/auto-update
apt-get update -qq
apt-get install -y -qq \
  build-essential cmake curl gpg python3-yaml
ros_source=/tmp/ros2-apt-source.deb
curl --fail --location --proto '=https' --proto-redir '=https' \
  --output "$ros_source" \
  https://github.com/ros-infrastructure/ros-apt-source/releases/download/1.2.0/ros2-apt-source_1.2.0.noble_all.deb
ros_apt_source_sha256='0804d9b13db770eb87019be414cd78378835228ad5fa801fc88758596dd8f7e5'
printf '%s  %s\n' "$ros_apt_source_sha256" "$ros_source" \
  | sha256sum --check --strict
dpkg -i "$ros_source"
# D-482: pin ROS to the image's dated snapshot (single source: inputs.lock.yaml).
ros_snapshot_url="$(python3 -c "import yaml; print(yaml.safe_load(open('deploy/robot/pinky_pro/image/inputs.lock.yaml', encoding='utf-8-sig'))['ros']['apt_snapshot_url'])")"
[[ "$ros_snapshot_url" =~ ^http://snapshots\.ros\.org/jazzy/[0-9]{4}-[0-9]{2}-[0-9]{2}/ubuntu$ ]]
# D-482 addendum: the snapshot repo is signed by its own key, not the
# ros2-apt-source key. Fetch it by full fingerprint, keep it in its own
# keyring and trust it for the snapshot source only (Signed-By).
ros_snapshot_key_fpr="$(python3 -c "import yaml; print(yaml.safe_load(open('deploy/robot/pinky_pro/image/inputs.lock.yaml', encoding='utf-8-sig'))['ros']['apt_snapshot_key_fingerprint'])")"
[[ "$ros_snapshot_key_fpr" =~ ^[0-9A-F]{40}$ ]]
ros_snapshot_keyring=/etc/apt/keyrings/ros-snapshots-archive-keyring.gpg
curl --fail --location --proto '=https' --proto-redir '=https' \
  --output /tmp/ros-snapshots-key.asc \
  "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x${ros_snapshot_key_fpr}"
install -d -m 0755 /etc/apt/keyrings
gpg --dearmor < /tmp/ros-snapshots-key.asc | tee "$ros_snapshot_keyring" > /dev/null
chmod 0644 "$ros_snapshot_keyring"
ros_snapshot_key_got="$(gpg --show-keys --with-colons "$ros_snapshot_keyring" \
  | awk -F: '$1 == "pub" { want = 1; next } want && $1 == "fpr" { print $10; want = 0 }')"
if [[ "$ros_snapshot_key_got" != "$ros_snapshot_key_fpr" ]]; then
  echo "::error::ROS snapshot key fingerprint mismatch: got '${ros_snapshot_key_got}', want ${ros_snapshot_key_fpr}"
  exit 1
fi
# Replace the live packages.ros.org stanza with the snapshot stanza.
rm -f /etc/apt/sources.list.d/ros2.sources
printf 'Types: deb\nURIs: %s\nSuites: %s\nComponents: main\nSigned-By: %s\n' \
  "$ros_snapshot_url" "$(. /etc/os-release && echo "$VERSION_CODENAME")" "$ros_snapshot_keyring" \
  | tee /etc/apt/sources.list.d/ros2-snapshots.sources > /dev/null
grep -qx "URIs: $ros_snapshot_url" /etc/apt/sources.list.d/ros2-snapshots.sources
grep -qx "Signed-By: $ros_snapshot_keyring" /etc/apt/sources.list.d/ros2-snapshots.sources
if grep -rqs 'packages\.ros\.org' /etc/apt/sources.list /etc/apt/sources.list.d/; then
  echo "::error::a live packages.ros.org source is still configured"
  exit 1
fi
apt-get update -qq
apt-get install -y -qq \
  python3-colcon-common-extensions python3-rosdep \
  python3-pip python3-setuptools python3-wheel \
  ros-jazzy-ros-base ros-dev-tools
if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
  rosdep init
fi
rosdep update --rosdistro jazzy
