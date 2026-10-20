"""Private fixed-object ACT study actor in the protected native simulation job."""
import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
from uuid import uuid4

from g2_common import ROOT, configure_imports, verify_module_origins
from g2_ports import ObserverClient, isolation_guard, write_json


def run(directory,observer_path,*,deadline_owner_s,calibration=False):
    if not math.isfinite(deadline_owner_s) or not 0<deadline_owner_s-time.monotonic()<=600:
        raise ValueError('original bounded native trial deadline required')
    isolation_guard(ROOT)
    configure_imports()
    sys.path[:0]=[str(ROOT/p) for p in ('learning/training/omx',
        'middleware/robot_execution/local/src','contracts/learning/src','operations/processes/cell')]
    import rclpy
    from PIL import Image
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from omx_adapter.ros_owner_executor import OwnerMultiThreadedExecutor
    from omx_adapter.ros_runtime import RosArmCommandRuntime
    from omx_adapter.pose_plan import CellPlanningProfile
    from omx_adapter.kinematics import ARM_JOINTS, OmxKinematics
    from omx_adapter.gripper_contract import GripperObservation, verify_held_object, verify_released_object
    from rosy.execution.local.omx_policy import OwnerPolicySession
    from rosy.execution.local.policy_journal import PolicyExecutionJournal
    from rosy_cell.cell import load_cell
    from rosy_cell.recipe import load_recipe
    from rosy_cell.compiler import compile_job
    from act_inference import ACTInference
    from sim_policy_install import prepare_install, WORLD
    from sim_policy_camera import SimPolicyCamera
    from sim_policy_inference import infer_for_owner
    from sim_policy_runtime import bind_sim_runtime
    from sim_policy_trial_evidence import goal_succeeded, object_transition, contact_held
    from sim_study_authority import NativeSimStudyAuthority
    from sim_study_stop import NativeSimStopFence
    from cell_sim_tools import SimAid, refuse_second_owner
    from instance_names import names_from_environment

    origins=verify_module_origins({'act_inference':'learning/training/omx',
        'rosy.execution.local.omx_policy':'middleware/robot_execution/local/src',
        'omx_adapter.command_owner':'middleware/devices/omx/adapter'})
    directory=Path(directory)
    frames=directory/'policy-frames';frames.mkdir(mode=0o700)
    parent_root=Path(os.environ['OMX_SIM_POLICY_INPUT'])
    campaign=json.loads((parent_root/'campaign.json').read_text())
    names=names_from_environment()
    refuse_second_owner(namespace=names.namespace)
    profile=CellPlanningProfile.load(ROOT/'deploy/robot/omx/sim/cell_profile.yaml')
    kin=OmxKinematics.load()
    cell_path=ROOT/'operations/processes/cell/examples/omx_sim/cell.yaml'
    recipe=load_recipe(cell_path.with_name('recipe.yaml').read_text())
    job=compile_job(recipe,load_cell(cell_path.read_text()),tol_m=.001)
    place=[step for step in job.steps if step.kind!='pallet_done'][1]
    goal=(place.target.x,place.target.y,place.target.z+recipe.box.grasp_depth-recipe.box.height/2)
    rclpy.init()
    node=Node('rosy_sim_fixed_object_policy',parameter_overrides=[Parameter('use_sim_time',value=True)])
    config=profile.arm_command_config(workcell_id='omx_cell_sim',instance_id='omx_cell_sim_01',
        calibration_revision='omx-f-gazebo-only-v1',allowed_owners=('learned_policy',))
    events=[]
    arm=RosArmCommandRuntime(node,config,joint_state_topic=names.joint_state_topic,
        trajectory_action=names.trajectory_action,on_goal_event=lambda event:events.append(asdict(event)))
    camera=SimPolicyCamera(node,arm.monotonic)
    executor=OwnerMultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    spinner=threading.Thread(target=executor.spin,daemon=True);spinner.start()
    observer,aid=ObserverClient(observer_path),SimAid()
    samples,steps,transitions,worker_errors=[],[],[],[]
    stop=threading.Event()
    authority=fence=session=None
    threads=[]
    started=time.monotonic()
    last_observed=[None]
    receipt=dict(schema='rosy.omx-fixed-object-policy-trial/1',success=False,
        mode='calibration_without_policy_goals' if calibration else 'learned_policy_object_trial',
        parent_policy_revision=campaign['policy_revision'],goal_m=goal,sim_aid=True,
        operating_fleet_approval='NOT_CLAIMED',physical_device_authority=False,module_origins=origins)

    def require_live():
        if worker_errors:raise RuntimeError(worker_errors[0])
        if time.monotonic()>=deadline_owner_s:raise TimeoutError('fixed policy trial wall budget')
        if last_observed[0] is not None and time.monotonic()-last_observed[0]>.5:
            raise PermissionError('independent object observation stale')
        if session and session.hold_reason:raise PermissionError(session.hold_reason)
        if arm.owner.state=='hold':raise PermissionError('native owner HOLD')

    def observe_worker():
        try:
            while not stop.is_set():
                value=observer('infeed_block',require_open=False)
                if not samples or value['clock']!=samples[-1]['clock']:samples.append(value)
                last_observed[0]=time.monotonic()
                stop.wait(.05)
        except Exception as error:worker_errors.append('object_observer:'+str(error))

    def renew_worker():
        try:
            while not stop.wait(.1):session.renew(authority.issue())
        except Exception as error:worker_errors.append('lease_renewal:'+str(error))

    def gripper_evidence(expect):
        js=arm.latest_joint_state
        q=js.positions[profile.gripper_joint]
        close=profile.gripper_close_for_width(recipe.box.width)
        contact=profile.gripper_contact_for_width(recipe.box.width)
        held=contact_held(q,close=close,contact=contact)
        opened=abs(q-profile.gripper_open)<=.05
        observation=GripperObservation(config.workcell_id,config.instance_id,
            'omx-sim-width-matched-position-v2',js.sequence,js.received_at,
            'CLOSED' if expect=='held' else 'OPEN' if opened else 'UNKNOWN',
            held if expect=='held' else False if opened else None,
            'box' if expect=='held' and held else None,1)
        verifier=verify_held_object if expect=='held' else verify_released_object
        checked=arm.monotonic()
        proof=verifier(observation,object_id='box',now=checked,max_age_s=profile.max_joint_state_age_s)
        return dict(observation=vars(observation),receipt=vars(proof),checked_owner_s=checked)

    try:
        deadline=time.monotonic()+90
        while arm.owner.state!='ready' or arm.latest_joint_state is None or not camera.snapshots():
            require_live()
            if time.monotonic()>deadline:raise TimeoutError('dedicated learned owner/camera unavailable')
            time.sleep(.02)
        policy=prepare_install(parent_root,campaign['policy_revision'],directory/'installed',arm.owner,
            normalization_sha256=campaign['normalization_sha256'])
        engine=ACTInference(policy.root,policy.binding.policy_revision,monotonic=arm.monotonic)
        receipt['installed_policy_revision']=policy.binding.policy_revision
        authority=NativeSimStudyAuthority(os.environ['OMX_NATIVE_STATE'],policy,arm.owner,str(uuid4()),
            monotonic=arm.monotonic)
        fence=NativeSimStopFence(authority)
        journal=PolicyExecutionJournal(directory/'policy-execution.sqlite3')
        session=OwnerPolicySession(policy,arm.owner,fence,authority.issue(),authority_current=authority.current,
            owner_identity=lambda:dict(simulation=True,workcell_id=config.workcell_id,
                instance_id=config.instance_id,profile='sim-world:'+WORLD),monotonic=arm.monotonic,
            enabled=True,camera_current=camera.snapshots,execution_journal=journal)
        session.observe(arm.latest_joint_state)
        renew=threading.Thread(target=renew_worker,daemon=True);renew.start();threads.append(renew)
        bind_started=time.monotonic()
        bind_sim_runtime(session,arm)
        receipt['runtime_bind_ms']=(time.monotonic()-bind_started)*1000
        sampler=threading.Thread(target=observe_worker,daemon=True);sampler.start();threads.append(sampler)
        while not samples:require_live();time.sleep(.01)
        initial_z=samples[0]['model_pose_base']['z_m']
        aid.watch('infeed_block');aid._robot_entity_id()
        attached=ever_attached=False
        last_submit=None
        for index in range(12 if calibration else 600):
            require_live()
            while last_submit is not None and time.monotonic()-last_submit<.8:
                require_live();time.sleep(.01)
            before=time.monotonic()
            candidate,result=infer_for_owner(engine,session,camera)
            step=dict(index=index,candidate=asdict(candidate),inference_ms=(time.monotonic()-before)*1000,
                input={key:value for key,value in asdict(result.source).items() if key!='rgb'},
                frame_sha256=result.source.frame_sha256,consumed_current=result.consumed_current,
                produced_owner_ns=result.produced_at_ns,returned_owner_ns=result.returned_at_ns)
            steps.append(step)
            Image.frombytes('RGB',(320,240),result.source.rgb).save(frames/f'{index:04d}.png')
            if calibration:
                with session._lock:
                    doc,now,cameras=session._guard()
                    session._source(candidate,doc,now);session._camera_source(candidate,doc,now,cameras)
                    if now-candidate.produced_at_ns>doc['timing']['max_action_age_ns']:
                        raise PermissionError('calibration action too old')
                step['checked_input_age_ms']=(now-min(candidate.observed_at_ns,*candidate.camera_received_at_ns))/1e6
                time.sleep(.1)
                continue
            if last_observed[0] is None or time.monotonic()-last_observed[0]>.5:
                raise PermissionError('independent object observation stale')
            decision=session.submit(candidate)
            last_submit=time.monotonic()
            step.update(decision=asdict(decision),command_id=session._active_command)
            deadline=time.monotonic()+30
            while True:
                require_live()
                row=journal.read(step['command_id'])
                if row['events'] and row['events'][-1]['kind'] in (
                        'TERMINAL_RESULT','TERMINAL_UNKNOWN','GOAL_REJECTED','GOAL_ACCEPTANCE_UNKNOWN'):
                    if not goal_succeeded(row):raise PermissionError('native learned goal did not succeed')
                    if arm.owner.state=='ready':break
                if time.monotonic()>deadline:raise TimeoutError('native learned goal terminal result missing')
                time.sleep(.02)
            step['native_goal_id']=row['driver_goal_id']
            js=arm.latest_joint_state
            if not 0<=arm.monotonic()-js.received_at<=profile.max_joint_state_age_s:
                raise PermissionError('post-goal actual gripper readback stale')
            tcp=kin.fk([js.positions[name] for name in ARM_JOINTS]);pose=samples[-1]['model_pose_base']
            q=js.positions[profile.gripper_joint]
            close=profile.gripper_close_for_width(recipe.box.width)
            contact=profile.gripper_contact_for_width(recipe.box.width)
            held=contact_held(q,close=close,contact=contact)
            released=abs(q-profile.gripper_open)<=.05
            transition=object_transition(attached=attached,ever_attached=ever_attached,held=held,
                released=released,gripper_position=q,
                contact_gripper=contact,xy_error_m=math.hypot(tcp.x-pose['x_m'],tcp.y-pose['y_m']),
                z_error_m=abs(tcp.z-(pose['z_m']+recipe.box.height/2-recipe.box.grasp_depth)))
            if transition=='settle':
                proof=gripper_evidence('open');released_at=samples[-1]['clock']
                transitions.append(dict(kind='released',sim_s=released_at,evidence=proof))
                while samples[-1]['clock']-released_at<2.2:require_live();time.sleep(.02)
                from sim_pick_place_task import judge_episode
                receipt['metrics']=judge_episode(samples,model='infeed_block',initial_z=initial_z,goal=goal,
                    released_at=released_at,released=True)
                receipt['success']=receipt['metrics']['success']
                break
            if transition in ('attach','detach'):
                proof=gripper_evidence('held') if transition=='attach' else None
                ack=getattr(aid,transition)('infeed_block')
                transitions.append(dict(kind=transition,sim_s=samples[-1]['clock'],evidence=proof,ack=ack))
                if ack.get('confirmed') is not True:raise PermissionError('SIM aid transition unconfirmed')
                attached=transition=='attach';ever_attached=True
        if calibration:
            receipt['success']=len(steps)==12 and not events
            receipt['policy_goals_sent']=len(events)
        elif not receipt['success']:
            raise RuntimeError('fixed object task did not satisfy independent judge')
    except Exception as error:
        receipt['error']=type(error).__name__+': '+str(error)
    finally:
        stop.set()
        for thread in threads:thread.join(4)
        if fence:
            try:fence.close_study('SIM_STUDY_COMPLETED' if receipt['success'] else 'SIM_STUDY_FAILED')
            except Exception as error:receipt['stop_error']=str(error);receipt['success']=False
        if session:
            try:session._fail('isolated_study_ended')
            except PermissionError:pass
        receipt.update(wall_s=time.monotonic()-started,worker_errors=worker_errors,
            owner_final=arm.owner.state,camera_accepted=camera.accepted,camera_rejected=camera.rejected,
            camera_error=camera.error,policy_steps=len(steps),native_events=len(events))
        if worker_errors:receipt['success']=False
        write_json(directory/'policy-steps.json',steps)
        write_json(directory/'policy-native-events.json',events)
        write_json(directory/'policy-object-transitions.json',transitions)
        write_json(directory/'policy-camera-captures.json',camera.captures)
        write_json(directory/'observations.json',samples)
        write_json(directory/'policy-result.json',receipt)
        camera.destroy();executor.shutdown();arm.destroy();node.destroy_node();rclpy.shutdown()
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--observer',type=Path,required=True)
    parser.add_argument('--calibration',action='store_true')
    parser.add_argument('--deadline-owner-s',type=float,required=True)
    args=parser.parse_args()
    raise SystemExit(run(args.evidence,args.observer,deadline_owner_s=args.deadline_owner_s,
                         calibration=args.calibration))
