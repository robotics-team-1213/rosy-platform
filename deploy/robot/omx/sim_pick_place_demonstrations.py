"""Collect one real RGB assisted-SIM transfer in the protected native seat."""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import time
import xml.etree.ElementTree as ET


def camera_world(source, camera, output):
    tree, pilot = ET.parse(source), ET.parse(camera)
    world = tree.getroot().find('world')
    if world.attrib.get('name') != 'omx_cell_workcell':
        raise ValueError('unexpected object world')
    if world.find("model[@name='workcell_camera']") is not None:
        raise ValueError('camera already present')
    for query in ("plugin[@name='gz::sim::systems::Sensors']", "model[@name='workcell_camera']"):
        node = pilot.getroot().find('world/' + query)
        if node is None:
            raise ValueError('pinned camera source missing')
        world.append(copy.deepcopy(node))
    with Path(output).open('xb') as stream:
        tree.write(stream, encoding='utf-8', xml_declaration=True)
    return {key: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for key, path in [('source_sha256', source), ('camera_source_sha256', camera),
                              ('derived_sha256', output)]}


def short_targets(points):
    if (not points or not points[0] or
            any(len(p) != len(points[0]) or any(type(v) not in (int, float) or not math.isfinite(v)
                                               for v in p) for p in points)):
        raise ValueError('finite equal-dimensional waypoints required')
    targets = []
    for left, right in zip(points, points[1:]):
        count = max(1, math.ceil(max(abs(b-a) for a, b in zip(left, right)) / .035))
        targets.extend(tuple(a+(b-a)*step/count for a,b in zip(left,right))
                       for step in range(1, count))
        targets.append(tuple(right))
    return targets


def run(directory):
    from g2_common import ROOT, controller_readiness
    from g2_ports import isolation_guard, write_json
    from g2_runner import Children
    isolation_guard(ROOT)
    directory.mkdir(mode=0o700)
    children = Children(directory)
    result = {'experiment': 'pick-place-demonstrations', 'attempts': 0, 'successes': 0,
              'sim_aid': True, 'training': 'NOT_RUN', 'policy_evaluation': 'NOT_RUN'}
    started, error, code = time.monotonic(), None, 1
    try:
        worlds = ROOT / 'integrations/simulation/gazebo/worlds'
        world = directory / 'camera-world.sdf'
        binding = camera_world(worlds/'omx_cell_workcell_sim_aid.sdf',
                               worlds/'omx_pilot_workcell.sdf', world)
        write_json(directory/'world-binding.json', binding)
        domain = os.environ.setdefault('ROS_DOMAIN_ID', '77')
        env = dict(os.environ, ROSY_SIM_REPO=str(ROOT), ROS_DOMAIN_ID=domain,
                   OMX_CELL_WORLD=str(world.with_suffix('')), OMX_CELL_LOG_DIR=str(directory),
                   OMX_CELL_DOMAIN_ID=domain, LIBGL_ALWAYS_SOFTWARE='1')
        children.start('gazebo-launch', ['bash', str(ROOT/'deploy/robot/omx/run_cell_sim.sh')], env=env)
        children.start('camera-bridge', ['ros2', 'run', 'ros_gz_bridge', 'parameter_bridge',
            '/workcell_camera/image@sensor_msgs/msg/Image[gz.msgs.Image',
            '/workcell_camera/camera_info@sensor_msgs/msg/CameraInfo[gz.msgs.CameraInfo'], env=env)
        observer = directory/'observer.sock'
        children.start('observer', ['/usr/bin/python3', str(ROOT/'deploy/robot/omx/g2_observer.py'),
                       '--socket', str(observer), '--open-position', '1.0'], env=env)
        controller_readiness(timeout_s=90)
        children.assert_alive()
        teacher = children.start('teacher', ['/usr/bin/python3',
            str(ROOT/'deploy/robot/omx/sim_pick_place_teacher.py'), '--evidence', str(directory),
            '--world', str(world), '--observer', str(observer)], env=env)
        result['attempts'] = 1
        code = teacher.wait(timeout=900)
        receipt = json.loads((directory/'teacher-result.json').read_text())
        result['teacher'] = receipt
        result['successes'] = int(code == 0 and receipt.get('success') is True)
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
    finally:
        cleanup = children.close()
        result.update(error=error, cleanup_verified=cleanup, wall_s=time.monotonic()-started)
        result['result'] = 'PASS' if result['successes'] and cleanup and not error else 'HOLD'
        write_json(directory/'result.json', result)
    return 0 if result['result'] == 'PASS' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--approve-isolated-simulation', action='store_true')
    parser.add_argument('--approve-startup-home', action='store_true')
    args = parser.parse_args()
    if not (args.approve_isolated_simulation and args.approve_startup_home):
        raise PermissionError('isolated SIM and bounded startup-home approvals required')
    raise SystemExit(run(args.evidence))
