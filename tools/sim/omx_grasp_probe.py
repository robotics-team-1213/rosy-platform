"""D-866 §2 Isaac switch condition "gripper grasp repeat": grip the infeed block, lift it, set it back, N times.

Runs against any D-877 backend through the shared layer's /arm_controller/follow_joint_trajectory, with the
teacher's own grasp geometry (top-down IK, recipe grasp depth, width-matched gripper close). No sim aid: the
block rises only if the simulated fingers hold it. The block pose comes from /sim/object_tf, so a backend that
publishes authored rather than simulated poses fails here.
A trial passes when the block rises at least LIFT_FRACTION of the gripper's lift and, set back, rests within
REST_DRIFT_M of where it was picked.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOINTS = ('joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1')
ACTION = '/arm_controller/follow_joint_trajectory'
OBJECTS = '/sim/object_tf'
BLOCK = 'infeed_block'
LIFT_M = .05
LIFT_FRACTION = .8
REST_DRIFT_M = .02
SPEED_RAD_S = .5


def judge(trial):
    """A trial's verdict from its measured block heights and positions (pure, for tests)."""
    rose = trial['block_lifted_z'] - trial['block_start_z']
    drift = math.dist(trial['block_start_xy'], trial['block_rest_xy'])
    return {'rose_m': rose, 'rest_drift_m': drift,
            'held': rose >= LIFT_FRACTION * LIFT_M, 'rested': drift <= REST_DRIFT_M}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--trials', type=int, default=5)
    parser.add_argument('--ready-s', type=float, default=300)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT/'deploy/robot/omx'))
    from g2_common import configure_imports  # the teacher's source paths, so both plan the grasp alike
    configure_imports()
    sys.path.insert(0, str(ROOT/'operations/processes/cell'))
    import rclpy
    from rclpy.action import ActionClient
    from builtin_interfaces.msg import Duration
    from control_msgs.action import FollowJointTrajectory
    from sensor_msgs.msg import JointState
    from tf2_msgs.msg import TFMessage
    from trajectory_msgs.msg import JointTrajectoryPoint
    from omx_adapter.kinematics import OmxKinematics, TopDownPose
    from omx_adapter.pose_plan import CellPlanningProfile
    from rosy_cell.cell import load_cell
    from rosy_cell.compiler import compile_job
    from rosy_cell.recipe import load_recipe

    profile = CellPlanningProfile.load(ROOT/'deploy/robot/omx/sim/cell_profile.yaml')
    kin = OmxKinematics.load()
    cell_path = ROOT/'operations/processes/cell/examples/omx_sim/cell.yaml'
    recipe = load_recipe(cell_path.with_name('recipe.yaml').read_text())
    box, close = recipe.box, profile.gripper_close_for_width(recipe.box.width)
    # The teacher's grasp yaw: the job's pick step, which squeezes the block's width. Only x, y, z are observed.
    pick_yaw = next(s for s in compile_job(recipe, load_cell(cell_path.read_text()), tol_m=.001).steps
                    if s.kind != 'pallet_done').target.yaw

    rclpy.init()
    node = rclpy.create_node('rosy_omx_grasp_probe', parameter_overrides=[
        rclpy.parameter.Parameter('use_sim_time', value=True)])
    latest = {}
    node.create_subscription(JointState, '/joint_states', lambda m: latest.update(joints=dict(zip(m.name, m.position))), 10)

    def objects(message):
        for t in message.transforms:
            if t.child_frame_id == BLOCK:
                v = t.transform.translation
                latest['block'] = (v.x, v.y, v.z)
    node.create_subscription(TFMessage, OBJECTS, objects, 10)
    client = ActionClient(node, FollowJointTrajectory, ACTION)

    def spin_until(done, limit):
        deadline = time.monotonic() + limit
        while not done():
            if time.monotonic() > deadline:
                raise TimeoutError(f'waited {limit:.0f} s')
            rclpy.spin_once(node, timeout_sec=.05)

    spin_until(lambda: 'joints' in latest and 'block' in latest and client.server_is_ready(), args.ready_s)

    def move(target):
        """target: joint -> rad, the joints not named keep their current value."""
        current = latest['joints']
        point = {n: target.get(n, current[n]) for n in JOINTS}
        seconds = max(1.0, max(abs(point[n]-current[n]) for n in JOINTS) / SPEED_RAD_S)
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = list(JOINTS)
        goal.trajectory.points = [JointTrajectoryPoint(positions=[point[n] for n in JOINTS],
            time_from_start=Duration(sec=int(seconds), nanosec=int(seconds % 1 * 1e9)))]
        sent = client.send_goal_async(goal)
        spin_until(sent.done, 10)
        handle = sent.result()
        if not handle.accepted:
            raise RuntimeError(f'goal rejected: {target}')
        result = handle.get_result_async()
        spin_until(result.done, seconds + 30)
        settle = time.monotonic() + .5
        spin_until(lambda: time.monotonic() > settle, 5)
        return result.result().result.error_code

    def tcp(x, y, z, yaw, gripper):
        solved = kin.solve_top_down(TopDownPose(x, y, z, yaw), profile.ik_limits())
        if not solved.ok:
            raise RuntimeError(f'no top-down IK for {(x, y, z, yaw)}: {solved}')
        return {**dict(zip(JOINTS, solved.joints)), 'gripper_joint_1': gripper}

    trials = []
    for index in range(args.trials):
        (x, y, z), yaw = latest['block'], pick_yaw
        grasp_z = z + box.height/2 - box.grasp_depth
        trial = {'trial': index + 1, 'block_start_xy': (x, y), 'block_start_z': z, 'codes': []}
        try:
            for target in (tcp(x, y, grasp_z + LIFT_M, yaw, profile.gripper_open),
                           tcp(x, y, grasp_z, yaw, profile.gripper_open),
                           {'gripper_joint_1': close},
                           tcp(x, y, grasp_z + LIFT_M, yaw, close)):
                trial['codes'].append(move(target))
            trial['gripper_rad_lifted'] = latest['joints']['gripper_joint_1']
            trial['block_lifted_z'] = latest['block'][2]
            for target in (tcp(x, y, grasp_z + .002, yaw, close), {'gripper_joint_1': profile.gripper_open},
                           tcp(x, y, grasp_z + LIFT_M, yaw, profile.gripper_open)):
                trial['codes'].append(move(target))
            trial['block_rest_xy'] = latest['block'][:2]
            trial.update(judge(trial))
        except Exception as exc:
            trial['error'] = f'{type(exc).__name__}: {exc}'
        trials.append(trial)
        print('OMX_GRASP_TRIAL=' + json.dumps(trial), flush=True)
    passed = sum(bool(t.get('held') and t.get('rested')) for t in trials)
    summary = {'trials': len(trials), 'passed': passed, 'lift_m': LIFT_M, 'close_rad': close,
               'grasp_depth_m': box.grasp_depth, 'box_width_m': box.width}
    args.out.write_text(json.dumps({'summary': summary, 'trials': trials}, indent=1))
    print(('OMX_GRASP_PASS=' if passed == len(trials) else 'OMX_GRASP_FAIL=') + json.dumps(summary), flush=True)
    node.destroy_node()
    rclpy.shutdown()
    return 0 if passed == len(trials) else 1


if __name__ == '__main__':
    raise SystemExit(main())
