#!/usr/bin/env bash
# /mnt/f 웍트리 → WSL 네이티브 ~/rosy 이관(시뮬 런타임용). 9p 병목 회피.
set -e
SRC="/mnt/f/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/pilot-teleop"
DST="$HOME/rosy"
echo "== src size =="
du -sh "$SRC/src" "$SRC/tools" 2>/dev/null || true
echo "== kill stuck launch =="
killall -9 ros2 gz ruby python3 parameter_bridge create 2>/dev/null || true
sleep 1
echo "== copy =="
mkdir -p "$DST"
tar -C "$SRC" \
  --exclude=./build --exclude=./install --exclude=./log \
  --exclude=./.git --exclude=./docs --exclude=./deploy \
  --exclude=./reference --exclude=./private --exclude=./.worktrees \
  --exclude=./.claude --exclude=./.codegraph --exclude=./.omc --exclude=./.omo \
  --exclude=./.github --exclude=./.impeccable --exclude=./.pytest_cache \
  --exclude=./.ruff_cache --exclude=./data --exclude=./firmware \
  -cf - . | tar -C "$DST" -xf -
echo "== copied =="
du -sh "$DST"
ls "$DST"
