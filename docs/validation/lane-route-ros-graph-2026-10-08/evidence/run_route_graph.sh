#!/bin/bash
set -eo pipefail
WS=/home/rosy/rosy_lfstop_ws
RUN=$WS/graph_replay
source /opt/ros/jazzy/setup.bash
source /home/rosy/rosy_bend_window_ws/install/setup.bash
source "$WS/install/setup.bash"
set -u
export ROS_DOMAIN_ID=97
export GZ_PARTITION=rosy_lfstop_graph
"$WS/install/control/lib/control/line_observer_node" --ros-args --params-file "$WS/install/control/share/control/config/line_follow.yaml" --params-file "$RUN/route_graph_params.yaml" > "$RUN/node.log" 2>&1 &
node_pid=$!
trap 'kill -INT "$node_pid" 2>/dev/null || true; wait "$node_pid" 2>/dev/null || true' EXIT
sleep 2
python3 "$RUN/route_graph_replay.py" "$WS/guard1/rec/frames.npz" "$RUN/result.json"
