#!/bin/bash
# D-763 SIM check rig on the AI PC: one venv (CORE + Fleet + probe) and a colcon build of current main.
set -uo pipefail
R=$HOME/rosy-test/d763-sim
lock="$HOME/rosy-jobs/d763-sim-build-$$.lock"
echo "$$ sim 6 6" > "$lock"; trap 'rm -f "$lock"' EXIT
exec > "$R/artifacts/setup.log" 2>&1
echo "nonce $(date +%F_%T) $(hostname)"
cd "$R/source"
for V in venv:deploy/robot/pinky_pro/requirements-core.txt fleet-venv:deploy/site/requirements-fleet.txt; do
  N=${V%%:*}; Q=${V#*:}
  if [ ! -f "$R/$N/.ok" ]; then
    rm -rf "$R/$N"; /usr/bin/python3 -m venv --system-site-packages "$R/$N"
    nice -n 15 "$R/$N/bin/python" -m pip install -q -r "$Q" httpx 'setuptools>=68' wheel playwright && touch "$R/$N/.ok"
    echo "PIP_EXIT $N $?"
  fi
done
set +u; source /opt/ros/jazzy/setup.bash; source "$R/venv/bin/activate"; set -u
read -r -a roots <<< "$(python3 tools/harness/colcon_roots.py)"
systemd-run --user --scope -p MemoryMax=6G -p CPUQuota=800% nice -n 10 timeout --signal=TERM --kill-after=15s 1800s \
  python3 /usr/bin/colcon --log-base "$R/log" build --base-paths "${roots[@]}" \
  --packages-up-to core control description gz_sim pinky_pro --merge-install --parallel-workers 4 \
  --build-base "$R/build" --install-base "$R/install" \
  --cmake-args -DBUILD_TESTING=OFF -DPython3_EXECUTABLE="$R/venv/bin/python" > "$R/artifacts/build.log" 2>&1
echo "BUILD_EXIT $?"
tail -5 "$R/artifacts/build.log"
date +%s > "$R/artifacts/setup.done"
