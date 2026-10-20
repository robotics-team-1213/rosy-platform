"""Private native SIM teacher: real short goals, RGB frames and object observations."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
import uuid

from g2_common import ROOT, configure_imports
from g2_ports import ObserverClient, isolation_guard, write_json
from sim_pick_place_demonstrations import short_targets, dispatch_readback_target
from sim_pick_place_task import judge_episode


def run(directory, world, observer_path, *, home_only=False):
    isolation_guard(ROOT)
    configure_imports()
    sys.path.insert(0, str(ROOT/'operations/processes/cell'))
    import rclpy
    import yaml
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from omx_adapter.ros_owner_executor import OwnerMultiThreadedExecutor
    from omx_adapter.ros_runtime import RosArmCommandRuntime
    from omx_adapter.pilot_sim.runtime import PilotSimRuntime
    from omx_adapter.pilot_sim.capture import PilotSimCapture
    from omx_adapter.pilot_sim.camera import PilotSimCamera
    from omx_adapter.kinematics import ARM_JOINTS, OmxKinematics, TopDownPose
    from omx_adapter.manipulation_plan import ExecutionStateSnapshot
    from omx_adapter.pose_plan import CellPlanningProfile, AnalyticCellTransferPlanner, CellTransferRequest
    from omx_adapter.gripper_contract import GripperObservation, verify_held_object, verify_released_object
    from rosy_cell.cell import load_cell
    from rosy_cell.recipe import load_recipe
    from rosy_cell.compiler import compile_job
    from cell_sim_tools import SimAid, refuse_second_owner
    from instance_names import names_from_environment

    names = names_from_environment()
    refuse_second_owner(namespace=names.namespace)
    profile = CellPlanningProfile.load(ROOT/'deploy/robot/omx/sim/cell_profile.yaml')
    kin = OmxKinematics.load()
    cell_path = ROOT/'operations/processes/cell/examples/omx_sim/cell.yaml'
    recipe_path = cell_path.with_name('recipe.yaml')
    cell, recipe = load_cell(cell_path.read_text()), load_recipe(recipe_path.read_text())
    job = compile_job(recipe, cell, tol_m=.001)
    if not (cell.kinematics_revision == profile.kinematics_revision == kin.revision):
        raise ValueError('kinematics mismatch')
    pick, place = [step for step in job.steps if step.kind != 'pallet_done'][:2]
    goal = (place.target.x, place.target.y, place.target.z+recipe.box.grasp_depth-recipe.box.height/2)
    native = json.loads((Path(os.environ['OMX_NATIVE_STATE'])/'manifest.json').read_text())
    if Path(native['source']).resolve() != ROOT.resolve():
        raise ValueError('native source mismatch')
    source = {'source_revision': native['revision'],
        'source_tree_sha256': hashlib.sha256(json.dumps(native['source_hashes'], sort_keys=True,
                                                       separators=(',', ':')).encode()).hexdigest(),
        'vendor_revision': yaml.safe_load((ROOT/'deploy/robot/omx/stack.lock.yaml').read_text())['vendor']['revision'],
        'world_sha256': hashlib.sha256(world.read_bytes()).hexdigest()}
    rclpy.init()
    node = Node('rosy_sim_pick_place_teacher', parameter_overrides=[Parameter('use_sim_time', value=True)])
    facade = None
    events, samples, commands = [], [], []

    def on_event(event):
        if facade is not None:
            facade.on_goal_event(event)

    config = profile.arm_command_config(workcell_id='omx_cell_sim', instance_id='omx_cell_sim_01',
        calibration_revision='omx-f-gazebo-only-v1', allowed_owners=('pilot_sim',))
    arm = RosArmCommandRuntime(node, config, joint_state_topic=names.joint_state_topic,
        trajectory_action=names.trajectory_action, on_goal_event=on_event)
    facade = PilotSimRuntime(arm, gripper=profile.gripper_joint,
        range_inset_rad=profile.start_state_tolerance_rad, gripper_open=profile.gripper_open,
        gripper_closed=profile.gripper_closed, gripper_velocity=profile.velocity_limits[profile.gripper_joint],
        gripper_preload=profile.gripper_preload_rad)
    capture = facade.capture = PilotSimCapture(facade, directory/'recordings', source,
        sim_time_ns=lambda: node.get_clock().now().nanoseconds)
    camera = PilotSimCamera(node, capture, source['world_sha256'], world_name='omx_cell_workcell')
    executor = OwnerMultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()
    observer, aid = ObserverClient(observer_path), SimAid()
    episode_id, success, error = None, False, None
    receipt = {'sim_aid': True, 'sim_gripper_sensor': True, 'source': source,
               'goal_m': goal, 'cell_sha256': job.cell_hash, 'recipe_sha256': job.recipe_hash,
               'profile_revision': profile.revision, 'training': 'NOT_RUN'}

    def sim_time():
        return node.get_clock().now().nanoseconds / 1_000_000_000

    def observe():
        value = observer('infeed_block', require_open=False)
        if not samples or value['clock'] != samples[-1]['clock']:
            samples.append(value)
        return value

    def wait_ready(timeout=90):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            state = facade.snapshot()
            if state['owner_state'] == 'hold':
                raise RuntimeError('owner HOLD: '+state['owner_reason'])
            if state['ready'] and state['active_goal'] is None:
                return state
            time.sleep(.02)
        raise TimeoutError('owner not ready')

    def dispatch_once(target):
        state = wait_ready()
        command_id = str(uuid.uuid4())
        def bounded(current, limits):
            for name, value in target.items():
                low, high = limits[name]
                if not math.isfinite(value) or not low <= value <= high or abs(value-current[name]) > .04:
                    return 'teacher_target_outside_bounded_step'
            current.update(target)
            return ''
        response = facade._dispatch(command_id, facade.instance_id, state['state_sequence'], .8,
                                    bounded, '', '')
        commands.append({'command_id': command_id, 'target': target, 'duration_s': .8,
                         'response': response, 'sim_time': sim_time()})
        if response['state'] == 'REJECTED':
            raise RuntimeError('teacher command rejected: '+response['reason'])
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            if episode_id:
                observe()
                quality = capture.status()
                if quality['status'] == 'incomplete' or quality['issues']:
                    raise RuntimeError('capture incomplete: '+str(quality))
            result = facade.goal(command_id)
            if result['state'] == 'SUCCEEDED':
                return wait_ready()
            if result['state'] in {'UNKNOWN_HOLD', 'CANCELED'}:
                raise RuntimeError('teacher goal failed: '+str(result))
            time.sleep(.02)
        raise TimeoutError('teacher goal result unknown')

    def dispatch(target):
        dispatch_readback_target(target, lambda: wait_ready()['positions'], dispatch_once)

    def grip(expect):
        js = arm.latest_joint_state
        q = js.positions[profile.gripper_joint]
        close = profile.gripper_close_for_width(recipe.box.width)
        threshold = (profile.gripper_contact_for_width(recipe.box.width)-close)/2
        held = q >= close+threshold
        opened = abs(q-profile.gripper_open) <= .05
        observation = GripperObservation(config.workcell_id, config.instance_id,
            'omx-sim-width-matched-position-v2', js.sequence, js.received_at,
            'CLOSED' if expect == 'held' else 'OPEN' if opened else 'UNKNOWN',
            held if expect == 'held' else False if opened else None,
            'box' if expect == 'held' and held else None, 1)
        verifier = verify_held_object if expect == 'held' else verify_released_object
        checked = arm.monotonic()
        verified = verifier(observation, object_id='box', now=checked,
                            max_age_s=profile.max_joint_state_age_s)
        return {'observation': vars(observation), 'receipt': vars(verified),
                'checked_owner_s': checked, 'max_age_s': profile.max_joint_state_age_s}

    try:
        state = wait_ready()
        home = TopDownPose(cell.home.x, cell.home.y, cell.home.z, cell.home.yaw)
        home_q = dict(zip(ARM_JOINTS, kin.solve_top_down(home, profile.ik_limits()).joints))
        home_q[profile.gripper_joint] = profile.gripper_open
        order = config.joint_names
        for point in short_targets([tuple(state['positions'][n] for n in order), tuple(home_q[n] for n in order)]):
            dispatch(dict(zip(order, point)))
        if home_only:
            final = wait_ready()
            if final['active_goal'] is not None or final['owner_state'] != 'ready':
                raise RuntimeError('startup owner did not become idle')
            receipt['purpose'] = 'startup_home_only'
            success = True
            return 0
        deadline = time.monotonic()+60
        while not capture.camera_status()['fresh']:
            if time.monotonic() > deadline:
                raise TimeoutError('real RGB camera unavailable: '+str(camera.error))
            time.sleep(.05)
        js = arm.latest_joint_state
        snapshot = ExecutionStateSnapshot(sequence=js.sequence, joint_positions=dict(js.positions),
            calibration_revision=config.calibration_revision, transform_revision='gz-world-is-link0-v1',
            planning_scene_revision=kin.planning_scene_revision, observed_at_monotonic_s=js.received_at)
        geometry = {'grasp_width_m': recipe.box.width, 'grasp_depth_m': recipe.box.grasp_depth,
                    'height_m': recipe.box.height}
        planner = AnalyticCellTransferPlanner(kin, accepted_cell_sha256=lambda: job.cell_hash,
            monotonic=arm.monotonic,
            accepted_item_geometry=lambda sha, item: geometry if sha == job.recipe_hash and item == 'box' else None)
        request = CellTransferRequest(job_id='sim-object-demonstration', recipe_sha256=job.recipe_hash,
            cell_sha256=job.cell_hash, step_index=0, item='box', home=home,
            pick=TopDownPose(pick.target.x,pick.target.y,pick.target.z,pick.target.yaw),
            place=TopDownPose(place.target.x,place.target.y,place.target.z,place.target.yaw),
            pick_approach_z=pick.approach_z, place_approach_z=place.approach_z, carry_z=job.carry_z,
            grasp_depth_m=recipe.box.grasp_depth, grasp_width_m=recipe.box.width)
        plan = planner.plan_transfer(request, profile, snapshot)
        initial = observe()
        aid.watch('infeed_block')
        aid._robot_entity_id()
        episode_id = capture.start('Lift infeed_block and place in fixed pallet A slot 1')['episode_id']
        receipt['episode_id'] = episode_id
        receipt['recording_start_sim_s'] = sim_time()
        for phase in plan.phases:
            event = {'phase_id': phase.phase_id, 'started_sim_s': sim_time(),
                     'started_owner_s': arm.monotonic()}
            events.append(event)
            if phase.phase_id == 'release':
                event['detach'] = aid.detach('infeed_block')
                if not event['detach']['confirmed']:
                    raise RuntimeError('detach unconfirmed')
            targets = short_targets([phase.start_state_positions, *[p.positions for p in phase.points]])
            for point in targets:
                dispatch(dict(zip(phase.joint_names, point)))
            if phase.phase_id == 'grasp':
                event['hold_evidence'] = grip('held')
                event['hold_receipt'] = event['hold_evidence']['receipt']
                tcp = kin.fk([arm.latest_joint_state.positions[n] for n in ARM_JOINTS])
                pose = observe()['model_pose_base']
                if math.hypot(tcp.x-pose['x_m'], tcp.y-pose['y_m']) > .01 or abs(tcp.z-(pose['z_m']+recipe.box.height/2-recipe.box.grasp_depth)) > .01:
                    raise RuntimeError('grasp readback is not at observed object')
                event['attach'] = aid.attach('infeed_block')
                if not event['attach']['confirmed']:
                    raise RuntimeError('attach unconfirmed')
            if phase.phase_id == 'release':
                event['release_evidence'] = grip('open')
                event['release_receipt'] = event['release_evidence']['receipt']
            event['ended_sim_s'] = sim_time()
            event['ended_owner_s'] = arm.monotonic()
        released_at = observe()['clock']
        deadline = time.monotonic()+30
        while observe()['clock']-released_at < 2.2:
            if time.monotonic() > deadline:
                raise TimeoutError('settling clock did not advance')
            time.sleep(.05)
        metrics = judge_episode(samples, model='infeed_block', initial_z=initial['model_pose_base']['z_m'],
            goal=goal, released_at=released_at, released=bool(events[-1].get('release_receipt')
                                                           and events[-1].get('detach',{}).get('confirmed')))
        receipt['metrics'] = metrics
        success = metrics['success']
        receipt['capture'] = capture.stop(episode_id, 'success' if success else 'failure')
        success = bool(success and capture.manifest(episode_id).get('status') == 'complete')
    except Exception as exc:
        error = type(exc).__name__+': '+str(exc)
        if episode_id and capture.recorder.active:
            receipt['capture'] = capture.stop(episode_id, 'failure')
    finally:
        receipt.update(success=success, error=error, recording_end_sim_s=sim_time(),
                       owner_final=facade.snapshot(), camera_final=capture.camera_status(),
                       camera_error=camera.error,
                       source_pairing_error=capture.source_pairing_error,
                       camera_stream_error=capture.camera.last_error if capture.camera else None)
        write_json(directory/'observations.json', samples)
        write_json(directory/'teacher-phases.json', events)
        write_json(directory/'teacher-commands.json', commands)
        write_json(directory/'teacher-result.json', receipt)
        camera.destroy()
        executor.shutdown()
        arm.destroy()
        node.destroy_node()
        rclpy.shutdown()
    return 0 if success else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--world', type=Path, required=True)
    parser.add_argument('--observer', type=Path, required=True)
    parser.add_argument('--home-only', action='store_true')
    args = parser.parse_args()
    raise SystemExit(run(args.evidence, args.world, args.observer, home_only=args.home_only))
