#!/usr/bin/env bash
# Isolated Gazebo calibration/mapping track run (ROS domain 227, partition pinky_calmap227).
#
# Ported 2026-09-22 (D-171) from the pre-absorption Rosy Control checkout
# (archive/legacy-rogic-20260913/Rosy Control/tools/gz/run_track260905.sh), where
# run_calibration_spaces.py still expects it. Changes from that script:
#   - package paths follow the absorbed tree: rosy_control/ -> control/;
#   - RIG_SINGLE_PROCESS=1 runs every component in one process
#     (RIG_COMPONENT=all) instead of one process per component;
#   - RIG_ESTOP_PROBE=1 starts rig_estop_probe.py, which presses the
#     simulation e-stop once calibration reaches validating_motion. The run
#     then must end in a failed calibration, never ready.
#   - D-185 R4: an overloaded box (mean load >= RIG_MAX_MEAN_LOAD, default 16) or a
#     stalled simulation (real-time factor < RIG_MIN_RTF, default 0.1) makes the run
#     environment-invalid: 'RIG ENVIRONMENT: INVALID' and exit 3 before any pass/fail.
#     Without rate evidence (no result, <10 s simulated) the verdict stays pass/fail.
#     Other Gazebo launchers take the same lock as they adopt it (staged, D-185 R4).
#     /tmp/rosy-gazebo.lock serialises Gazebo runs of every rig that takes it
#     (RIG_GZ_LOCK_WAIT seconds, default 1800; exit 4 when it stays busy).
# Run from anywhere on a Linux box with ROS 2 Jazzy, Gazebo Harmonic,
# ros_gz_bridge and slam_toolbox. Results land in /tmp/pinky-calmap227.
set -eo pipefail
cd "$(dirname "$0")/../.."
source /opt/ros/jazzy/setup.bash
set -u
export ROS_DOMAIN_ID=227 ROS_LOCALHOST_ONLY=1 GZ_IP=127.0.0.1
export GZ_PARTITION=pinky_calmap227 PYTHONPATH="$PWD:${PYTHONPATH:-}"
out=/tmp/pinky-calmap227
mkdir -p "$out"
exec 9>"$out/run.lock"
flock -n 9 || { echo 'A calibration mapping rig already owns this partition'; exit 1; }
exec 8>/tmp/rosy-gazebo.lock
flock -w "${RIG_GZ_LOCK_WAIT:-1800}" 8 || { echo 'Another Gazebo run holds /tmp/rosy-gazebo.lock'; exit 4; }
if [[ -n "${RIG_CALIBRATION_CASE:-}" ]]; then
  python3 -m tools.gz.calibration_spaces "$RIG_CALIBRATION_CASE" /tmp/pinky-calmap227
else
  python3 tools/gz/prepare_track_world.py
fi
python3 - "$out" <<'PY'
import sys, os, xml.etree.ElementTree as ET, yaml, shutil, time, json, hashlib, uuid, subprocess
from pathlib import Path
out=Path(sys.argv[1])
if (out/'stack.log').exists():
    archive=out/'archive'/str(time.time_ns())
    archive.mkdir(parents=True)
    camera_frames=out/'rendered-camera'
    if camera_frames.is_dir() and not camera_frames.is_symlink():
        camera_frames.rename(archive/'rendered-camera')
    for path in out.iterdir():
        if path.is_file() and path.suffix in ('.log','.json','.jsonl','.yaml','.pgm','.npz','.sdf','.txt'):
            shutil.copy2(path, archive/path.name)
run_id=uuid.uuid4().hex
# An old complete map is historical evidence, never this run's readiness.
for name in ('map.pgm','map.yaml','map_grid.npz','calibration.json','calibration.certificate.json','live_evidence.json',
             'track_samples.json','track_last_status.json','track_result.json',
             'track_map.npz','track_map.pgm','track_map.yaml','track_map_quality.json',
             'track_map_audit.json','track_result.png','obstacle-scenario.json',
             'decision-events.json','health-capture.json','scan-capture.json','realtime-adjustment.txt',
             'track_odometry.json','track_footprint_audit.json','estop_probe.json',
             'environment.json','environment_samples.jsonl'):
    (out/name).unlink(missing_ok=True)
(out/'mapping_metrics.json').write_text(json.dumps({'run_id':run_id, 'status':'pending',
    'map_raster_complete':False, 'raster_and_sampled_clearance_ok':False}))
root=ET.parse(str(out/'track.sdf'))
model=root.find(".//model[@name='pinky']")
# Spawn is chosen against the exact oriented collision walls.
plant=os.environ.get('RIG_PLANT', 'wheel')
if plant == 'velocity':
    model.remove(model.find("plugin[@name='gz::sim::systems::DiffDrive']"))
    for joint in list(model.findall('joint')):
        model.remove(joint)
    for link in list(model.findall('link')):
        if link.get('name') != 'base':
            model.remove(link)
    base=model.find("link[@name='base']")
    ET.SubElement(base, 'gravity').text='false'
    ET.SubElement(model, 'plugin', filename='gz-sim-velocity-control-system', name='gz::sim::systems::VelocityControl')
(out/'plant.txt').write_text(plant)
root.find('.//real_time_factor').text=os.environ.get('RIG_REALTIME_FACTOR', '1.0')
from tools.gz.c1_lidar import align_gpu_lidar
align_gpu_lidar(model.find('.//sensor'))
if os.environ.get('RIG_RENDERED_CAMERA') == '1':
    from tools.gz.obstacle_camera import add_camera
    add_camera(root.getroot())
root.write(out/'world.sdf')
identity=json.loads((out/'track_identity.json').read_text())
settings={'/**': {'ros__parameters': {'use_sim_time':True, 'robot_radius':identity['robot_radius_m'],
    'rotation_footprint_xy':[v for xy in identity['robot_geometry']['footprint_xy'] for v in xy],
    'simulation_motion_sweep_enabled':plant == 'wheel',
    'stop_distance':.14, 'clear_distance':.16,
    'imu_angular_velocity_unit':'rad_s', 'calibration_us_max_range':8.,
    'calibration_auto_motion':True, 'result_path':str(out/'calibration.json'),
    'obstacle_tracking_enabled':os.environ.get('RIG_TRACK_OBSTACLES') == '1'}}}
if os.environ.get('RIG_CALIBRATION_CASE'):
    settings['/**']['ros__parameters']['calibration_relocation_enabled']=True
    settings['/**']['ros__parameters']['calibration_after_relocation']=os.environ.get('RIG_CALIBRATION_AFTER','stay')
(out/'rig.yaml').write_text(yaml.safe_dump(settings))
slam=yaml.safe_load(Path('tools/gz/slam_sim.yaml').read_text())
slam['slam_toolbox']['ros__parameters']['resolution']=.02
if os.environ.get('RIG_TRACK_OBSTACLES') == '1':
    slam['slam_toolbox']['ros__parameters']['scan_topic']='/mapping/scan'
(out/'slam.yaml').write_text(yaml.safe_dump(slam))
source_paths=sorted(list(Path('control').rglob('*.py'))+list(Path('config').glob('*.yaml'))+
                    list(Path('tools/gz').glob('*.py'))+list(Path('tools/gz').glob('*.sh')))
try:
    source_at_start=os.environ.get('RIG_SOURCE_COMMIT') or subprocess.check_output(
        ['git','rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL).strip()
except (OSError, subprocess.CalledProcessError):
    source_at_start='unknown (no git on this box; source_sha256 is authoritative)'
manifest={'run_id':run_id, 'recorded_unix_s':time.time(), 'plant':plant,
    'calibration_case':os.environ.get('RIG_CALIBRATION_CASE'),
    'single_process':os.environ.get('RIG_SINGLE_PROCESS') == '1',
    'estop_probe':os.environ.get('RIG_ESTOP_PROBE') == '1',
    'ros_domain':227, 'gazebo_partition':'pinky_calmap227',
    'world_sha256':hashlib.sha256((out/'world.sdf').read_bytes()).hexdigest(),
    'source_at_start':source_at_start,
    'source_sha256':{str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths},
    'robot_radius_m':settings['/**']['ros__parameters']['robot_radius'],
    'robot_geometry':identity['robot_geometry'],
    'physical_robot_verified':False,
    'auxiliary_sensors':('Rendered camera; synthetic IR; GT-derived IMU; lidar-derived US'
        if os.environ.get('RIG_RENDERED_CAMERA') == '1' else
        'Synthetic camera/IR; GT-derived IMU; lidar-derived US')}
(out/'run_manifest.json').write_text(json.dumps(manifest,indent=2))
PY
pids=()
cleanup() {
  for pid in "${pids[@]}"; do kill -TERM -- -"$pid" 2>/dev/null || true; done
  sleep 2
  for pid in "${pids[@]}"; do kill -KILL -- -"$pid" 2>/dev/null || true; done
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP
rig_start=$(date +%s.%N)
setsid gz sim -s -r --headless-rendering "$out/world.sdf" > "$out/gz.log" 2>&1 & pids+=($!)
# The recorder must not hold the rig locks, and exits with this script.
setsid python3 tools/gz/rig_environment.py record "$out" "$$" 8>&- 9>&- > "$out/environment.log" 2>&1 & pids+=($!)
sleep 4
if [[ "${RIG_TRACK_OBSTACLES:-0}" == 1 ]]; then
  setsid python3 -m control.obstacle_observer_node --ros-args -p use_sim_time:=true \
    > "$out/obstacle-observer.log" 2>&1 & pids+=($!)
  setsid python3 -m tools.gz.record_obstacle_decisions --ros-args -p use_sim_time:=true \
    > "$out/obstacle-recorder.log" 2>&1 & pids+=($!)
fi
if [[ "${RIG_RENDERED_CAMERA:-0}" == 1 ]]; then
  setsid ros2 run ros_gz_bridge parameter_bridge \
    '/pinky/rendered_camera@sensor_msgs/msg/Image[gz.msgs.Image' \
    --ros-args -p use_sim_time:=true > "$out/camera-bridge.log" 2>&1 & pids+=($!)
  setsid python3 -m tools.gz.rendered_camera_adapter --ros-args -p use_sim_time:=true \
    > "$out/camera.log" 2>&1 & pids+=($!)
fi
bridged=('/lidar/scan@sensor_msgs/msg/LaserScan[gz.msgs.LaserScan'
  '/odometry_gt@nav_msgs/msg/Odometry[gz.msgs.Odometry'
  '/model/pinky/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist')
# D-185 R6: Gazebo publishes /clock every physics step. RIG_CLOCK_HZ=N relays it at N messages
# per wall second through a throttled gz-transport subscription instead; unset keeps the bridge.
if [[ -z "${RIG_CLOCK_HZ:-}" ]]; then
  bridged+=('/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock')
else
  setsid python3 tools/gz/clock_relay.py "$RIG_CLOCK_HZ" 8>&- 9>&- > "$out/clock-relay.log" 2>&1 & pids+=($!)
fi
setsid ros2 run ros_gz_bridge parameter_bridge "${bridged[@]}" \
  --ros-args -p use_sim_time:=true -r /lidar/scan:=/scan -r /odometry_gt:=/odom_gz \
  -r /model/pinky/cmd_vel:=/cmd_vel > "$out/bridge.log" 2>&1 & pids+=($!)
if [[ "${RIG_SINGLE_PROCESS:-0}" == 1 ]]; then
  components=(all)
else
  components=(adapter safety calibration wander goal web)
fi
for component in "${components[@]}"; do
  log="$out/$component.log"
  if [[ "$component" == adapter || "$component" == all ]]; then log="$out/stack.log"; fi
  setsid env RIG_COMPONENT="$component" python3 tools/gz/calibration_mapping_rig.py --ros-args \
    --params-file config/robot.yaml --params-file config/wander.yaml \
    --params-file config/goal.yaml --params-file config/web.yaml \
    --params-file "$out/rig.yaml" \
    > "$log" 2>&1 & pids+=($!)
done
sleep 3
setsid ros2 launch slam_toolbox online_async_launch.py use_sim_time:=true \
  slam_params_file:="$out/slam.yaml" > "$out/slam.log" 2>&1 & pids+=($!)
if [[ "${RIG_ESTOP_PROBE:-0}" == 1 ]]; then
  setsid python3 tools/gz/rig_estop_probe.py "$out" > "$out/estop-probe.log" 2>&1 & pids+=($!)
fi

if [[ "${RIG_DECISION_PROBE:-0}" == 1 ]]; then
  setsid python3 tools/gz/rig_decision_probe.py > "$out/decision-probe.log" 2>&1 & pids+=($!)
fi
setsid python3 tools/gz/track_run_monitor.py > "$out/monitor.log" 2>&1 & pids+=($!)
if [[ "${RIG_OBSTACLE_SCENARIO:-0}" == 1 ]]; then
  setsid python3 -m tools.gz.obstacle_scenario --ros-args -p use_sim_time:=true \
    > "$out/obstacle-scenario.log" 2>&1 & pids+=($!)
  monitor_index=$((${#pids[@]}-2))
else
  monitor_index=$((${#pids[@]}-1))
fi
echo "Isolated exact-track run: $out"
wait "${pids[$monitor_index]}"
set +e
python3 tools/gz/rig_environment.py judge "$out"
environment=$?
set -e
if [[ $environment != 0 && $environment != 3 ]]; then
  echo "rig_environment judge crashed ($environment)"; exit "$environment"
fi
# Environment-invalid (3): the verdict below is still reported, marked not counted,
# and the run exits 3 - neither a pass nor a failure of the code under test.
export RIG_ENVIRONMENT_INVALID=$(( environment == 3 ))
python3 - "$out" <<'PY'
import json, os, sys
from pathlib import Path
out = Path(sys.argv[1])
result = json.loads((out/'track_result.json').read_text())
uncounted = os.environ.get('RIG_ENVIRONMENT_INVALID') == '1'
def verdict():
  if os.environ.get('RIG_ESTOP_PROBE') == '1':
    probe = json.loads((out/'estop_probe.json').read_text())
    assert probe.get('pressed') is True, f'e-stop probe never fired: {probe}'
    assert result['calibration_ready'] is not True, 'Calibration became ready after an e-stop during its trial'
    assert result['calibration_phase'] == 'failed', f"e-stop during a trial must fail it: {result['calibration_phase']}"
    # A trial that fails for another reason first proves nothing about the e-stop path.
    assert 'Emergency stop' in (result.get('message') or ''), f"failed, but not by the e-stop: {result.get('message')}"
  elif not os.environ.get('RIG_CALIBRATION_CASE'):
    assert result['calibration_ready'] is True, result['message']
  assert result['cmd_vel_publishers'] == ['safety_node'], 'Unexpected final command publisher'
  if os.environ.get('RIG_REQUIRE_COMPLETE') == '1':
    assert result['mapping_complete'] is True, 'Full fresh world-aligned map acceptance failed'
summary = json.dumps({k: result.get(k) for k in
    ('calibration_phase', 'calibration_ready', 'cmd_vel_publishers', 'elapsed_sim_s', 'message')})
if not uncounted:
  verdict()
  print('RIG VERDICT: PASS', summary)
else:
  try:
    verdict()
    print('RIG VERDICT (environment-invalid, not counted): PASS', summary)
  except (AssertionError, OSError, ValueError, KeyError) as error:
    print('RIG VERDICT (environment-invalid, not counted): FAIL', error, summary)
  sys.exit(3)
PY
if [[ "${RIG_REQUIRE_COMPLETE:-0}" == 1 ]]; then
  python3 -m tools.gz.track_map_audit "$out"
fi
