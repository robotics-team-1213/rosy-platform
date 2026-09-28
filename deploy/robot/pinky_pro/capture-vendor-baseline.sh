#!/usr/bin/env bash
# capture-vendor-baseline.sh — Pinky Pro vendor stock image (card A) evidence capture.
#
# READ-ONLY: every command here only reads system state. The only write target is
# the evidence directory given as $1 (default ~/vendor-baseline-<timestamp>).
# It never modifies system state: no service control, no package install, no
# kernel module loading, no bus probing by default.
#
# Purpose: close the UNKNOWN list of docs/plans/2026-09-21-pinky-pro-os-research.md
# (§11: distro string, image build surface, boot config, udev, systemd autostart,
# pin mapping, pinkylib location, wifi_setup.sh) and produce reference values that
# Rosy OS commissioning (G0-G5) and the parity checklist compare against.
#
# Usage:
#   bash capture-vendor-baseline.sh [OUTDIR]          # passive capture
#   PROBE_I2C=1 bash capture-vendor-baseline.sh       # opt-in i2cdetect bus probe
#
# Run it ON the booted vendor system (SSH `pinky@192.168.4.1`) or copy the script
# there first. Some items need root (dmesg, /boot on some images); rerun the whole
# script under `sudo -E bash capture-vendor-baseline.sh` if those come back empty —
# the script itself never asks for a password.
#
# After capture: copy OUTDIR off the robot, review it for site/device secrets,
# and run the repository secret scanner before selectively landing evidence.
# Never commit the raw directory merely because known keys were redacted.

set -u
set -o pipefail

OUT="${1:-$HOME/vendor-baseline-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUT"

# cap NAME COMMAND... — best-effort capture; absence and failure are both
# recorded findings, neither aborts the run.
cap() {
  local name="$1"; shift
  ( "$@" ) > "$OUT/$name.txt" 2>&1
  local rc=$?
  if [ $rc -ne 0 ]; then
    echo "(exit=$rc — item may be absent or denied)" >> "$OUT/$name.txt"
  fi
}

# Known credential-shaped assignments are redacted before they reach disk.
# This is defense in depth, not a claim that arbitrary command output is safe.
cap_redacted() {
  local name="$1"; shift
  ( "$@" 2>&1 | sed -E \
      's/((passw(or)?d|passphrase|psk|token|secret|api[_-]?key)[[:space:]]*[:=][[:space:]]*)[^[:space:]]+/\1[redacted]/Ig' \
  ) > "$OUT/$name.txt"
  local rc=$?
  if [ $rc -ne 0 ]; then
    echo "(exit=$rc — item may be absent or denied)" >> "$OUT/$name.txt"
  fi
}

echo "capture target: $OUT (read-only evidence; no system mutation)"

# --- OS identity (research doc UNKNOWN 1) ---
cap os-release          cat /etc/os-release
cap uname               uname -a
cap proc-version        cat /proc/version
cap os-derivatives      lsb_release -a

# --- boot config (UNKNOWN 5) ---
cap boot-config-fw      cat /boot/firmware/config.txt
cap boot-config-legacy  cat /boot/config.txt
cap cmdline-fw          cat /boot/firmware/cmdline.txt
cap cmdline-legacy      cat /boot/cmdline.txt
cap boot-listing        ls -la /boot /boot/firmware

# --- udev / device mapping (UNKNOWN 5, 6) ---
cap udev-rules          cat /etc/udev/rules.d/*.rules
cap udev-rules-listing  ls -la /etc/udev/rules.d
cap device-nodes        ls -l /dev/ttyAMA* /dev/ttyS* /dev/i2c-* /dev/spi* /dev/video* /dev/gpiomem
cap user-groups         id
cap group-membership    getent group dialout gpio i2c spi video
cap dmesg-tail          dmesg

# --- systemd autostart (UNKNOWN 4, 7) ---
cap systemd-enabled     systemctl list-unit-files --state=enabled
cap systemd-running     systemctl list-units --type=service --state=running
cap systemd-ros-like    systemctl list-unit-files
cap rc-local            cat /etc/rc.local
cap_redacted crontab-root crontab -l
cap cron-listing        ls -la /etc/cron.d /etc/cron.daily
cap autostart-listing   ls -la /home/*/.config/autostart /etc/xdg/autostart

# --- network / provisioning (AP mode, netplan vs NetworkManager) ---
cap_redacted netplan-configs cat /etc/netplan/*.yaml
cap netplan-listing     ls -la /etc/netplan
cap networkmanager      nmcli general status
cap wifi-setup-locate   find /home -maxdepth 3 -name 'wifi_setup.sh'
cap_redacted wifi-setup-body cat /home/*/wifi_setup.sh
cap_redacted bashrc-ros-exports grep -n ROS /home/*/.bashrc /root/.bashrc
cap hosts-resolv        cat /etc/hosts /etc/resolv.conf

# --- vendor closed-source surface (UNKNOWN 3, 8) ---
cap pip-pinkylib        pip3 show pinkylib
cap pinkylib-location   python3 -c "import pinkylib; print(pinkylib.__file__)"
cap pip-relevant        pip3 list
cap home-layout         ls -la /home /home/*
cap opt-listing         ls -la /opt
cap pinky-test-locate   find /home -maxdepth 3 -name 'pinky_test*'

# --- running processes ---
cap_redacted process-snapshot ps aux

# --- optional active probe (OFF by default: i2cdetect writes address bytes on the bus) ---
if [ "${PROBE_I2C:-0}" = "1" ]; then
  cap i2cdetect-bus0    i2cdetect -y 0
  cap i2cdetect-bus1    i2cdetect -y 1
fi

# --- ROS graph (best-effort; works only where the ROS env is already set up) ---
cap ros-install-scan    ls /opt/ros
cap ros2-node-list      timeout 8 ros2 node list
cap ros2-topic-list     timeout 8 ros2 topic list

# --- integrity of the capture itself ---
( cd "$OUT" && sha256sum ./*.txt > "$OUT/SHA256SUMS.txt" )
echo "done: $OUT (SHA256SUMS.txt covers every captured file)"
echo "no system state was modified; i2c probe ran only if PROBE_I2C=1"
