#!/bin/bash
# D-559 trail follow SIM on the model PC (never on the Windows laptop).
# Two Pinky in rosy_swarm_bench (6 x 6 m room), Nav2 + AMCL per robot (map frame), CORE per robot.
#
#   WS=~/rosy_trail_ws bash run_sim.sh <run-name> [--direct]      # nohup it
#
# The workspace holds a git-archive snapshot of the branch HEAD in src/rosy-platform, built with
#   colcon build --symlink-install --packages-up-to gz_sim core control description
# CORE Python deps (fastapi, uvicorn, websockets, pydantic) in $WS/pydeps, Fleet deps in $WS/pyfleet
# and $WS/pyextra (httpx), copied from an earlier SIM workspace on the same host.
WS=${WS:-$HOME/rosy_trail_ws}
NAME=${1:-r1}
PORT=${PORT:-8130}
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$WS" || exit 1
export PATH=/usr/bin:/bin:$PATH
source /opt/ros/jazzy/setup.bash; source install/setup.bash
export PYTHONPATH=$WS/pydeps:$WS/src/rosy-platform/operations/fleet:$WS/pyfleet:$WS/pyextra:$PYTHONPATH
# The `rosy.*` namespace packages (rosy.contracts.motion, ...) live in */src/rosy dirs, not colcon.
for d in $(find -L "$WS/src/rosy-platform" -path '*/.worktrees' -prune -o -type d -name rosy -path '*/src/rosy' -print); do
  PYTHONPATH=$(dirname "$d"):$PYTHONPATH
done
export PYTHONPATH
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-79} GZ_PARTITION=${GZ_PARTITION:-rosy_trail}
RUN=$WS/runs/$NAME; mkdir -p "$RUN"
# Stop every process of an earlier run of this partition (environment carries GZ_PARTITION).
for p in $(pgrep -u "$(id -u)"); do
  [ "$p" = "$$" ] && continue
  tr '\000' '\n' 2>/dev/null < /proc/$p/environ | grep -qx "GZ_PARTITION=$GZ_PARTITION" && kill "$p" 2>/dev/null
done
sleep 4
ros2 launch gz_sim gz_multi.launch.py robots:=2 mode:=nav core:=true headless:=true \
  world_name:=rosy_swarm_bench.world spawn_poses:="-1.8,-2.2,0;-2.4,-2.2,0" \
  api_port_base:=$PORT nav_composition:=true > "$RUN/launch.log" 2>&1 &
LPID=$!
cat > "$RUN/robots.yaml" <<YAML
robots:
  - {robot_id: rosy_01, base_url: "http://127.0.0.1:$PORT", token: rosy-dev-operator}
  - {robot_id: rosy_02, base_url: "http://127.0.0.1:$((PORT + 1))", token: rosy-dev-operator}
YAML
chmod 600 "$RUN/robots.yaml"
# trail_sim.py waits for both APIs and LOCALIZED (D-395 gate on follow) before arming.
uptime > "$RUN/ready.txt"
python3 "$HERE/trail_sim.py" --robots "$RUN/robots.yaml" --out "$RUN" "${@:2}" > "$RUN/driver.log" 2>&1
echo "driver exit $?" >> "$RUN/driver.log"
python3 "$HERE/analyze.py" "$RUN" > "$RUN/analyze.log" 2>&1
kill $LPID
sleep 3
for p in $(pgrep -u "$(id -u)"); do
  tr '\000' '\n' 2>/dev/null < /proc/$p/environ | grep -qx "GZ_PARTITION=$GZ_PARTITION" && kill "$p" 2>/dev/null
done
echo ALL_DONE >> "$RUN/driver.log"
