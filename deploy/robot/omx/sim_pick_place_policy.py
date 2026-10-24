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
    import torch
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
    from rosy.execution.local.policy_source import capture_source
    from rosy_cell.cell import load_cell
    from rosy_cell.recipe import load_recipe
    from rosy_cell.compiler import compile_job
    from act_inference import ACTInference
    from sim_policy_install import prepare_install, WORLD
    from sim_policy_camera import MAX_CAPTURE_RECORDS, SimPolicyCamera
    from sim_policy_inference import infer_for_owner
    from sim_policy_runtime import bind_sim_runtime, trace_sim_admission
    from sim_policy_trial_evidence import goal_succeeded, object_transition, contact_held
    from sim_policy_tracking import ControllerTracking
    from sim_pick_place_task import judge_episode
    from sim_study_authority import NativeSimStudyAuthority
    from sim_study_stop import NativeSimStopFence
    from cell_sim_tools import SimAid, refuse_second_owner
    from instance_names import names_from_environment

    origins=verify_module_origins({'act_inference':'learning/training/omx',
        'rosy.execution.local.omx_policy':'middleware/robot_execution/local/src',
        'omx_adapter.command_owner':'middleware/devices/omx/adapter'})
    previous_switch_interval_s=sys.getswitchinterval()
    sys.setswitchinterval(.001)
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
    # Leave joint intake turns between full policy checks on the shared owner lock.
    arm=RosArmCommandRuntime(node,config,joint_state_topic=names.joint_state_topic,
        trajectory_action=names.trajectory_action,poll_period_s=.2,
        on_goal_event=lambda event:events.append(asdict(event)))
    camera=SimPolicyCamera(node,arm.monotonic)
    executor=OwnerMultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    spinner=threading.Thread(target=executor.spin,daemon=True);spinner.start()
    observer,aid=ObserverClient(observer_path),SimAid()
    samples,steps,transitions,worker_errors=[],[],[],[]
    admission_timings=[]
    stop=threading.Event()
    authority=fence=session=None
    failed_traceback=None
    threads=[]
    tracking=ControllerTracking(config.joint_names,clock=arm.monotonic,
        command_reference=lambda:getattr(session,'_active_command',None))
    started=time.monotonic()
    last_observed=[None]
    receipt=dict(schema='rosy.omx-fixed-object-policy-trial/1',success=False,
        mode='calibration_without_policy_goals' if calibration else 'learned_policy_object_trial',
        parent_policy_revision=campaign['policy_revision'],goal_m=goal,sim_aid=True,
        runtime_poll_period_s=arm.poll_period_s,
        camera_capture_record_limit=MAX_CAPTURE_RECORDS,
        python_switch_interval_s=sys.getswitchinterval(),
        previous_python_switch_interval_s=previous_switch_interval_s,
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
            while not stop.wait(.2):session.renew(authority.issue())
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
        try:
            from control_msgs.msg import JointTrajectoryControllerState
            from rclpy.qos import qos_profile_sensor_data
            node.create_subscription(JointTrajectoryControllerState,
                names.trajectory_action.rsplit('/',1)[0]+'/controller_state',
                tracking.observe,qos_profile_sensor_data)
        except Exception as error:tracking.failure(error)
        deadline=time.monotonic()+90
        while arm.owner.state!='ready' or arm.latest_joint_state is None or not camera.snapshots():
            require_live()
            if time.monotonic()>deadline:raise TimeoutError('dedicated learned owner/camera unavailable')
            time.sleep(.02)
        policy=prepare_install(parent_root,campaign['policy_revision'],directory/'installed',arm.owner,
            normalization_sha256=campaign['normalization_sha256'])
        engine=ACTInference(policy.root,policy.binding.policy_revision,monotonic=arm.monotonic)
        period_s=engine.metadata['timing']['period_ns']/1e9
        receipt['policy_cycle_minimum_interval_s']=period_s
        receipt['torch_num_threads']=torch.get_num_threads()
        receipt['torch_num_interop_threads']=torch.get_num_interop_threads()
        receipt['installed_policy_revision']=policy.binding.policy_revision
        journal=PolicyExecutionJournal(directory/'policy-execution.sqlite3')
        prepare_started=time.monotonic()
        header,payloads=capture_source(policy,arm.owner)
        prepared_source=journal.store_source(header,payloads)
        del header,payloads
        receipt['source_prepare_ms']=(time.monotonic()-prepare_started)*1000
        require_live()
        authority=NativeSimStudyAuthority(os.environ['OMX_NATIVE_STATE'],policy,arm.owner,str(uuid4()),
            monotonic=arm.monotonic)
        fence=NativeSimStopFence(authority)
        session=OwnerPolicySession(policy,arm.owner,fence,authority.issue(),authority_current=authority.current,
            owner_identity=lambda:dict(simulation=True,workcell_id=config.workcell_id,
                instance_id=config.instance_id,profile='sim-world:'+WORLD),monotonic=arm.monotonic,
            enabled=True,camera_current=camera.snapshots,execution_journal=journal)
        bind_started=time.monotonic()
        bind_sim_runtime(session,arm)
        if session._runtime_binding.source_revision!=prepared_source:
            raise PermissionError('prepared source changed during runtime binding')
        receipt['runtime_bind_ms']=(time.monotonic()-bind_started)*1000
        admission_timings=trace_sim_admission(session,journal,arm)
        renew=threading.Thread(target=renew_worker,daemon=True);renew.start();threads.append(renew)
        sampler=threading.Thread(target=observe_worker,daemon=True);sampler.start();threads.append(sampler)
        while not samples:require_live();time.sleep(.01)
        initial_z=samples[0]['model_pose_base']['z_m']
        aid.watch('infeed_block');aid._robot_entity_id()
        attached=ever_attached=False
        last_cycle=None
        for index in range(12 if calibration else 600):
            require_live()
            while last_cycle is not None and time.monotonic()-last_cycle<period_s:
                require_live();time.sleep(.01)
            before=time.monotonic()
            timing_ms={}
            candidate,result=infer_for_owner(engine,session,camera,timings=timing_ms,require_live=require_live)
            step=dict(index=index,candidate=asdict(candidate),inference_ms=(time.monotonic()-before)*1000,
                cycle_started_owner_s=before,
                timing_ms=timing_ms,
                input={key:value for key,value in asdict(result.source).items() if key!='rgb'},
                frame_sha256=result.source.frame_sha256,consumed_current=result.consumed_current,
                produced_owner_ns=result.produced_at_ns,returned_owner_ns=result.returned_at_ns)
            steps.append(step)
            save_started=time.monotonic()
            Image.frombytes('RGB',(320,240),result.source.rgb).save(frames/f'{index:04d}.png')
            step['frame_save_ms']=(time.monotonic()-save_started)*1000
            require_live()
            if calibration:
                with session._lock:
                    doc,now,cameras=session._guard()
                    session._source(candidate,doc,now);session._camera_source(candidate,doc,now,cameras)
                    if now-candidate.produced_at_ns>doc['timing']['max_action_age_ns']:
                        raise PermissionError('calibration action too old')
                step['checked_input_age_ms']=(now-min(candidate.observed_at_ns,*candidate.camera_received_at_ns))/1e6
                last_cycle=time.monotonic()
                continue
            if last_observed[0] is None or time.monotonic()-last_observed[0]>.5:
                raise PermissionError('independent object observation stale')
            step['pre_submit_original_input_age_ms']=(int(arm.monotonic()*1e9)-min(
                candidate.observed_at_ns,*candidate.camera_received_at_ns))/1e6
            submit_started=time.monotonic()
            try:
                require_live()
                decision=session.submit(candidate)
            finally:
                step['submit_ms']=(time.monotonic()-submit_started)*1000
            last_cycle=time.monotonic()
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
        failed_traceback=error.__traceback__
    finally:
        stop.set()
        for thread in threads:thread.join(4)
        if not calibration and samples and 'metrics' not in receipt:
            receipt['metrics']=judge_episode(samples,model='infeed_block',
                initial_z=samples[0]['model_pose_base']['z_m'],goal=goal,
                released_at=samples[-1]['clock'],released=False)
            assert receipt['metrics']['success'] is False
            receipt['metrics_scope']='incomplete_trial_observation'
        if fence:
            try:fence.close_study('SIM_STUDY_COMPLETED' if receipt['success'] else 'SIM_STUDY_FAILED')
            except Exception as error:receipt['stop_error']=str(error);receipt['success']=False
        if session:
            try:session._fail('isolated_study_ended')
            except PermissionError:pass
        if failed_traceback is not None:
            import traceback
            receipt['error_stack']=[dict(file=Path(frame.filename).name,line=frame.lineno,function=frame.name)
                for frame in traceback.extract_tb(failed_traceback,limit=12)]
        if session and session._runtime_binding is not None:
            receipt['admission_rejection']=session._runtime_binding.admission_rejection
        receipt.update(wall_s=time.monotonic()-started,worker_errors=worker_errors,
            owner_final=arm.owner.state,camera_accepted=camera.accepted,camera_rejected=camera.rejected,
            camera_error=camera.error,camera_capture_records=len(camera.captures),
            policy_steps=len(steps),native_events=len(events))
        if worker_errors:receipt['success']=False
        receipt['controller_tracking']=tracking.finish(directory/'policy-controller-tracking.json',write_json)
        write_json(directory/'policy-steps.json',steps)
        write_json(directory/'policy-native-events.json',events)
        write_json(directory/'policy-object-transitions.json',transitions)
        write_json(directory/'policy-camera-captures.json',camera.captures)
        write_json(directory/'observations.json',samples)
        write_json(directory/'policy-result.json',receipt)
        try:
            camera.destroy();executor.shutdown();arm.destroy();node.destroy_node();rclpy.shutdown()
        finally:
            write_json(directory/'policy-admission-timings.json',admission_timings)
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
