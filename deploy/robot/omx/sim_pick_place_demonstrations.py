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


TEACHER_STEP_RAD = .03
TEACHER_READBACK_LIMIT_RAD = .035


# pick-place-chunks scenarios (D-872): the box moved (x, y in m, world frame) or turned (deg), and which grasp
# yaw the chunk plan takes: the site's own, or turned by the box (the candidates the choices ledger compares)
SCENARIOS = {"nominal": (0.0, 0.0, 0.0, "site"), "offset": (0.012, -0.008, 0.0, "site"),
             "yaw-site": (0.0, 0.0, 20.0, "site"), "yaw-box": (0.0, 0.0, 20.0, "box")}


def camera_world(source, camera, output, box=None):
    """`box`: (dx, dy, dyaw_deg) applied to the infeed block's pose in the world file."""
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
    if box and any(box):
        pose = world.find("model[@name='infeed_block']/pose")
        if pose is None:
            raise ValueError('infeed block pose missing')
        x, y, z, roll, pitch, yaw = (float(v) for v in pose.text.split())
        pose.text = ' '.join(repr(v) for v in (x + box[0], y + box[1], z, roll, pitch, yaw + math.radians(box[2])))
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
        count = max(1, math.ceil(max(abs(b-a) for a, b in zip(left, right)) / TEACHER_STEP_RAD))
        targets.extend(tuple(a+(b-a)*step/count for a,b in zip(left,right))
                       for step in range(1, count))
        targets.append(tuple(right))
    return targets


def readback_target(current, desired):
    if (not current or set(current) != set(desired) or any(type(value) not in (int,float)
            or not math.isfinite(value) for values in (current,desired) for value in values.values())):
        raise ValueError('finite matching readback and target joint maps required')
    distance = max(abs(desired[n]-current[n]) for n in current)
    if distance <= TEACHER_READBACK_LIMIT_RAD:
        return dict(desired)
    fraction = TEACHER_STEP_RAD/distance
    return {name: current[name]+fraction*(desired[name]-current[name]) for name in current}


def dispatch_readback_target(desired, read_positions, send):
    previous = None
    for _ in range(8):
        current = read_positions()
        target = readback_target(current, desired)
        remaining = max(abs(desired[n]-current[n]) for n in current)
        if target != desired and previous is not None and remaining >= previous-.0001:
            raise RuntimeError('bounded_readback_step_no_progress')
        send(target)
        if target == desired:
            return
        previous = remaining
    raise RuntimeError('bounded_readback_step_limit')


def episode(directory, plan='analytic', scenario='nominal'):
    from g2_common import ROOT, controller_readiness
    from g2_ports import isolation_guard, write_json
    from g2_runner import Children
    isolation_guard(ROOT)
    directory.mkdir(mode=0o700)
    children = Children(directory)
    result = {'experiment': 'pick-place-demonstrations', 'plan': plan, 'attempts': 0, 'successes': 0,
              'sim_aid': True, 'training': 'NOT_RUN', 'policy_evaluation': 'NOT_RUN'}
    started, error, code = time.monotonic(), None, 1
    try:
        worlds = ROOT / 'integrations/simulation/gazebo/worlds'
        world = directory / 'camera-world.sdf'
        dx, dy, dyaw, grasp_yaw = SCENARIOS[scenario]
        binding = camera_world(worlds/'omx_cell_workcell_sim_aid.sdf',
                               worlds/'omx_pilot_workcell.sdf', world, box=(dx, dy, dyaw))
        binding['scenario'] = {'name': scenario, 'box_offset_m': [dx, dy], 'box_turn_deg': dyaw, 'grasp_yaw': grasp_yaw}
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
            '--world', str(world), '--observer', str(observer), '--plan', plan,
            '--box-turn-deg', str(dyaw if grasp_yaw == 'box' else 0.0)], env=env)
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


def run(directory, *, episodes=1, plan='analytic', scenario='nominal'):
    from g2_ports import write_json
    if type(episodes) is not int or not 1 <= episodes <= 3:
        raise ValueError('one to three episodes per bounded archive required')
    directory.mkdir(mode=0o700)
    results = []
    for index in range(episodes):
        path = directory / f'episode-{index+1}'
        code = episode(path, plan, scenario)
        results.append(json.loads((path/'result.json').read_text()))
        if code:
            break
    success = len(results) == episodes and all(r['result'] == 'PASS' for r in results)
    write_json(directory/'result.json', {'experiment': 'pick-place-demonstrations', 'plan': plan,
        'requested_episodes': episodes, 'episodes': results,
        'attempts': sum(r['attempts'] for r in results), 'successes': sum(r['successes'] for r in results),
        'cleanup_verified': all(r['cleanup_verified'] for r in results),
        'result': 'PASS' if success else 'HOLD', 'training': 'NOT_RUN', 'policy_evaluation': 'NOT_RUN'})
    return 0 if success else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--episodes', type=int, choices=(1, 2, 3), default=1)
    parser.add_argument('--plan', choices=('analytic', 'chunks'), default='analytic')
    parser.add_argument('--scenario', choices=tuple(SCENARIOS), default='nominal')
    parser.add_argument('--approve-isolated-simulation', action='store_true')
    parser.add_argument('--approve-startup-home', action='store_true')
    args = parser.parse_args()
    if not (args.approve_isolated_simulation and args.approve_startup_home):
        raise PermissionError('isolated SIM and bounded startup-home approvals required')
    raise SystemExit(run(args.evidence, episodes=args.episodes, plan=args.plan, scenario=args.scenario))
