#!/bin/bash
# usage: run-d763.sh <label>   (on the AI PC, detached; the runner owns Gazebo, both COREs and Fleet)
set -uo pipefail
R=$HOME/rosy-test/d763-sim; L="$1"
lock="$HOME/rosy-jobs/d763-s7-$$.lock"
echo "$$ sim 8 8" > "$lock"; trap 'rm -f "$lock"' EXIT
exec > "$R/artifacts/$L.log" 2>&1
echo "nonce $(date +%F_%T) $(hostname) load $(cat /proc/loadavg)"
set +u; source /opt/ros/jazzy/setup.bash; source "$R/venv/bin/activate"; source "$R/install/setup.bash"; set -u
export AMENT_PREFIX_PATH="$R/overlay:$AMENT_PREFIX_PATH"
export PYTHONPATH="$R/install/lib/python3.12/site-packages:${PYTHONPATH:-}"
export D763_LIVE_SHOTS="$R/live-shots.py" D763_FLEET_PY="$R/fleet-venv/bin/python" D763_PROBE_S=1500
systemd-run --user --scope -p MemoryMax=7G -p CPUQuota=1200% nice -n 10 timeout --signal=TERM --kill-after=20s 2100s \
  "$R/venv/bin/python" "$R/runner-s7.py" "$L"
echo "RUNNER_EXIT $? $(date +%T) load $(cat /proc/loadavg)"
date +%s > "$R/artifacts/$L.done"
