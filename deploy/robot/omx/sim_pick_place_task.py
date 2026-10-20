"""Fixed assisted SIM object task, judged by a separate read-only observer."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time


def judge_episode(samples, *, model, initial_z, goal, released_at, released):
    result = {'success': False, 'lift_m': 0., 'stable_sim_s': 0.,
              'xy_error_m': None, 'z_error_m': None}
    previous, stable_since = None, None
    try:
        if not all(math.isfinite(x) for x in (initial_z, *goal, released_at)):
            raise ValueError('nonfinite task inputs')
        for sample in samples:
            pose = sample['model_pose_base']
            clock = sample['clock']
            xyz = tuple(pose[key] for key in ('x_m', 'y_m', 'z_m'))
            finger = sample['gripper_position']
            if (sample['model_id'] != model or
                    not all(type(x) in (float, int) and math.isfinite(x) for x in (*xyz, clock, finger))
                    or clock < 0 or previous and clock <= previous[0]):
                raise ValueError('invalid object identity, clock or measurement')
            result['lift_m'] = max(result['lift_m'], xyz[2] - initial_z)
            result['xy_error_m'] = math.hypot(xyz[0] - goal[0], xyz[1] - goal[1])
            result['z_error_m'] = abs(xyz[2] - goal[2])
            if clock >= released_at:
                good = (result['xy_error_m'] <= 0.01 and result['z_error_m'] <= 0.005
                        and abs(finger - 1.) <= 0.05)
                if previous and previous[0] >= released_at:
                    dt = clock - previous[0]
                    good = good and dt <= 0.5 and math.dist(xyz, previous[1]) / dt <= 0.01
                stable_since = (clock if stable_since is None else stable_since) if good else None
                result['stable_sim_s'] = 0. if stable_since is None else clock - stable_since
            previous = clock, xyz
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        result['reason'] = str(error)
        return result
    result['success'] = bool(released and result['lift_m'] >= 0.03 and result['stable_sim_s'] >= 2.)
    return result


def run(directory):
    from g2_common import ROOT, configure_imports, controller_readiness
    from g2_ports import ObserverClient, isolation_guard, write_json
    from g2_runner import Children

    isolation_guard(ROOT)
    configure_imports()
    sys.path.insert(0, str(ROOT / 'operations/processes/cell'))
    from rosy_cell.cell import load_cell
    from rosy_cell.compiler import compile_job
    from rosy_cell.recipe import load_recipe
    cell_path = ROOT / 'operations/processes/cell/examples/omx_sim/cell.yaml'
    recipe_path = ROOT / 'operations/processes/cell/examples/omx_sim/recipe.yaml'
    recipe = load_recipe(recipe_path.read_text())
    task = compile_job(recipe, load_cell(cell_path.read_text()), tol_m=0.001)
    target = [step for step in task.steps if step.kind != 'pallet_done'][1].target
    goal = (target.x, target.y, target.z + recipe.box.grasp_depth - recipe.box.height / 2)
    directory.mkdir(mode=0o700)
    children = Children(directory)
    samples, attempts, error, success = [], 0, None, False
    started = time.monotonic()
    result = {'experiment': 'pick-place', 'sim_aid': True, 'sim_gripper_sensor': True,
              'controller': 'existing_rule_based_owner', 'training': 'NOT_RUN',
              'policy_evaluation': 'NOT_RUN', 'full_g2': False, 'goal_m': goal,
              'recipe_sha256': hashlib.sha256(recipe_path.read_bytes()).hexdigest(),
              'cell_sha256': hashlib.sha256(cell_path.read_bytes()).hexdigest()}
    try:
        domain = os.environ.get('ROS_DOMAIN_ID', '77')
        env = dict(os.environ, ROSY_SIM_REPO=str(ROOT), ROS_DOMAIN_ID=domain,
                   OMX_CELL_WORLD=str(ROOT / 'integrations/simulation/gazebo/worlds/omx_cell_workcell_sim_aid'),
                   OMX_CELL_LOG_DIR=str(directory), OMX_CELL_DOMAIN_ID=domain)
        children.start('gazebo-launch', ['bash', str(ROOT / 'deploy/robot/omx/run_cell_sim.sh')], env=env)
        observer_path = directory / 'observer.sock'
        children.start('observer', ['/usr/bin/python3', str(ROOT / 'deploy/robot/omx/g2_observer.py'),
                                   '--socket', str(observer_path), '--open-position', '1.0'], env=env)
        controller_readiness(timeout_s=90)
        children.assert_alive()
        observer = ObserverClient(observer_path)
        initial = observer('infeed_block', require_open=False)
        samples.append(initial)
        probe = children.start('teacher', ['/usr/bin/python3', str(ROOT / 'deploy/robot/omx/probe_cell_transfer.py'),
                               '--transfers', '0', '--journal-dir', str(directory / 'journal'),
                               '--out', str(directory / 'probe')], env=env)
        attempts = 1
        released_at, measurement_error = None, None
        while time.monotonic() - started < 600:
            try:
                observation = observer('infeed_block', require_open=probe.poll() is not None)
                if not samples or observation['clock'] != samples[-1]['clock']:
                    samples.append(observation)
                measurement_error = None
            except (OSError, RuntimeError) as exc:
                measurement_error = str(exc)
            if probe.poll() is not None:
                if probe.returncode != 0:
                    raise RuntimeError('existing object teacher failed with exit ' + str(probe.returncode))
                if measurement_error:
                    raise RuntimeError(measurement_error)
                if released_at is None:
                    released_at = samples[-1]['clock']
                if samples[-1]['clock'] - released_at >= 2.2:
                    break
            time.sleep(0.05)
        else:
            raise TimeoutError('object episode exceeded 600 wall seconds')
        evidence = json.loads((directory / 'probe/c3b-transfer.json').read_text())
        transfer = evidence['transfers'][0]
        metrics = judge_episode(samples, model='infeed_block', initial_z=initial['model_pose_base']['z_m'],
            goal=goal, released_at=released_at,
            released=bool(transfer['phases']['release'].get('release_receipt')
                          and transfer.get('sim_aid_detach_before_release', {}).get('confirmed')))
        result['metrics'] = metrics
        success = metrics['success']
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
    finally:
        cleanup = children.close()
        success = bool(success and cleanup)
        write_json(directory / 'observations.json', samples)
        result.update(attempts=attempts, successes=int(success),
                      success_rate=int(success)/attempts if attempts else None,
                      wall_s=time.monotonic()-started, error=error, cleanup_verified=cleanup,
                      result='PASS' if success else 'HOLD')
        write_json(directory / 'result.json', result)
    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--approve-isolated-simulation', action='store_true')
    parser.add_argument('--approve-startup-home', action='store_true')
    args = parser.parse_args()
    if not (args.approve_isolated_simulation and args.approve_startup_home):
        raise PermissionError('isolated SIM and bounded startup-home approvals are required')
    return run(args.evidence)


if __name__ == '__main__':
    raise SystemExit(main())
