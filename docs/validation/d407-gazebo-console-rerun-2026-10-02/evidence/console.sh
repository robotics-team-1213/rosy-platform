#!/bin/bash
# D-407 rerun: the real Fleet console (rosy_fleet console) on 127.0.0.1:8096 with the sim
# CORE (127.0.0.1:8095) in robots.yaml and a fleet_pairing_token matching run_sim.sh HUB=1.
#   ROBOT_ID=<CORE robot id> bash console.sh      (foreground; WSL, /rosy_d407_ws)
WS=${WS:-/rosy_d407_ws}
ROBOT_ID=${ROBOT_ID:?set ROBOT_ID to the CORE robot id}
RUN=$WS/d407/fleet; rm -rf "$RUN"; mkdir -p "$RUN"; chmod 700 "$RUN"
cd "$WS" || exit 1
source /opt/ros/jazzy/setup.bash; source install/setup.bash
cat > "$RUN/robots.yaml" <<YAML
robots:
  - robot_id: $ROBOT_ID
    base_url: http://127.0.0.1:${CORE_PORT:-8095}
    token: rosy-dev-operator
    fleet_pairing_token: d407-sim-pairing
YAML
chmod 600 "$RUN/robots.yaml"
exec python3 -m fleet.cli console --robots "$RUN/robots.yaml" --host 127.0.0.1 --port 8096 \
  --token d407-console --events-db "$RUN/events.db" --tasks-db "$RUN/tasks.db" \
  --no-localization-service \n  --site-config "$(ros2 pkg prefix gz_sim)/share/gz_sim/config/fleet_sim_site.yaml"
