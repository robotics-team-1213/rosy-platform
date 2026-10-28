"""One fresh native world per checkpoint trial, with an exited startup owner."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from g2_common import ROOT, controller_readiness
from g2_ports import isolation_guard, write_json
from g2_runner import Children
from sim_pick_place_demonstrations import camera_world
from sim_policy_contacts import CHANNELS, COVERAGE, contact_world, topic
from sim_policy_articulation import SCHEMA as ARTICULATION_SCHEMA, COVERAGE as ARTICULATION_COVERAGE


def require_articulation(directory):
    status=json.loads((directory/'articulation-ready.json').read_text())
    received=status.get('latest_advance_owner_ns')
    stamp=status.get('source_stamp_ns')
    if (status.get('schema')!=ARTICULATION_SCHEMA or status.get('ready') is not True
            or status.get('invalid_messages')!=0 or status.get('truncated') is not False
            or type(received) is not int or type(stamp) is not int or stamp<=0
            or not 0<=int(time.monotonic()*1e9)-received<=500_000_000):
        raise ValueError('articulation capture not clean and fresh')


def wait_articulation(observer,bridge,directory,deadline):
    while True:
        contacts_alive(observer,bridge)
        try:
            require_articulation(directory)
            return
        except FileNotFoundError:
            pass
        if time.monotonic()>=deadline:raise TimeoutError('articulation unavailable')
        time.sleep(.05)


def contacts_alive(observer,bridge):
    for name,process in [('contact observer',observer),('contact bridge',bridge)]:
        if process.poll() is not None:raise RuntimeError(name+' exited before diagnostic completed')


def wait_contacts(observer,bridge,directory,deadline):
    while True:
        contacts_alive(observer,bridge)
        ready=directory/'contact-ready.json'
        if ready.exists():
            if json.loads(ready.read_text()).get('positive_control_channels')!=sorted(CHANNELS):
                raise ValueError('contact positive control mismatch')
            return
        if time.monotonic()>=deadline:raise TimeoutError('contact positive control unavailable')
        time.sleep(.05)


def wait_contact_policy(actor,observer,bridge,deadline):
    while True:
        contacts_alive(observer,bridge)
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('contact diagnostic policy deadline')
        try:
            code=actor.wait(timeout=min(.2,remaining))
        except subprocess.TimeoutExpired:
            continue
        contacts_alive(observer,bridge)
        return code


def close_contact_diagnostic(observer,children,directory,*,articulation=False):
    result=dict(verified=False)
    try:
        if observer is None or observer.poll() is not None:
            raise RuntimeError('contact observer absent before requested shutdown')
        observer.terminate()
        if observer.wait(timeout=3)!=0:raise RuntimeError('contact observer shutdown failed')
        raw=(directory/'policy-contacts.json').read_bytes();document=json.loads(raw)
        summary=document['summary']
        if (document.get('schema')!='rosy.omx-contact-observation/1' or document.get('coverage')!=COVERAGE
                or summary.get('status')!='captured' or summary.get('invalid_messages')!=0
                or summary.get('truncated') is not False
                or summary.get('positive_control_channels')!=sorted(CHANNELS)):
            raise ValueError('contact capture incomplete; silence is unknown')
        if articulation:
            joint_raw=(directory/'policy-articulation.json').read_bytes();joints=json.loads(joint_raw)
            joint_summary=joints['summary']
            if (joints.get('schema')!=ARTICULATION_SCHEMA or joints.get('coverage')!=ARTICULATION_COVERAGE
                    or joint_summary.get('status')!='captured' or joint_summary.get('invalid_messages')!=0
                    or joint_summary.get('truncated') is not False or len(joints.get('samples',[]))<2):
                raise ValueError('articulation capture incomplete')
            result['articulation']=dict(sha256=hashlib.sha256(joint_raw).hexdigest(),summary=joint_summary,
                coverage=ARTICULATION_COVERAGE)
        result.update(verified=True,sha256=hashlib.sha256(raw).hexdigest(),summary=summary,
            coverage=COVERAGE,channels=document['channels'])
    except Exception as error:
        result['error']=type(error).__name__+': '+str(error)
    finally:
        cleanup=children.close()
    return result,cleanup


def run(directory,*,calibration=False,contacts=False):
    if calibration and contacts:raise ValueError('contact diagnostic is a policy episode')
    isolation_guard(ROOT)
    directory.mkdir(mode=0o700)
    children=Children(directory)
    started=time.monotonic();deadline=started+600
    contact_observer=contact_bridge=None
    result=dict(experiment='pick-place-policy-calibration' if calibration else
        'pick-place-policy-contact' if contacts else 'pick-place-policy',
        attempts=0 if calibration else 1,successes=0,sim_aid=True,
        policy_evaluation='CALIBRATION_ONLY' if calibration else 'STARTED',
        physical_device_authority=False,operating_fleet_approval='NOT_CLAIMED')
    try:
        worlds=ROOT/'integrations/simulation/gazebo/worlds'
        world=directory/'camera-world.sdf'
        camera=directory/'camera-world-base.sdf' if contacts else world
        binding=camera_world(worlds/'omx_cell_workcell_sim_aid.sdf',worlds/'omx_pilot_workcell.sdf',camera)
        if contacts:
            binding['contact_instrumentation']=contact_world(camera,world)
            binding['derived_sha256']=binding['contact_instrumentation']['derived_sha256']
        write_json(directory/'world-binding.json',binding)
        domain=os.environ.setdefault('ROS_DOMAIN_ID','77')
        env=dict(os.environ,ROSY_SIM_REPO=str(ROOT),ROS_DOMAIN_ID=domain,
            OMX_CELL_WORLD=str(world.with_suffix('')),OMX_CELL_LOG_DIR=str(directory),
            OMX_CELL_DOMAIN_ID=domain,LIBGL_ALWAYS_SOFTWARE='1',
            OMP_NUM_THREADS='4',OPENBLAS_NUM_THREADS='4',HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1')
        children.start('gazebo-launch',['bash',str(ROOT/'deploy/robot/omx/run_cell_sim.sh')],env=env)
        children.start('camera-bridge',['ros2','run','ros_gz_bridge','parameter_bridge',
            '/workcell_camera/image@sensor_msgs/msg/Image[gz.msgs.Image',
            '/workcell_camera/camera_info@sensor_msgs/msg/CameraInfo[gz.msgs.CameraInfo'],env=env)
        if contacts:
            contact_bridge=children.start('contact-bridge',['ros2','run','ros_gz_bridge','parameter_bridge',
                *[topic(label)+'@ros_gz_interfaces/msg/Contacts[gz.msgs.Contacts' for label in CHANNELS]],env=env)
            contact_observer=children.start('contact-observer',['/usr/bin/python3',
                str(ROOT/'deploy/robot/omx/sim_policy_contacts.py'),'--evidence',str(directory)],env=env)
            diagnostic_deadline=min(deadline,time.monotonic()+90)
            wait_contacts(contact_observer,contact_bridge,directory,diagnostic_deadline)
            wait_articulation(contact_observer,contact_bridge,directory,diagnostic_deadline)
        observer=directory/'observer.sock'
        children.start('observer',['/usr/bin/python3',str(ROOT/'deploy/robot/omx/g2_observer.py'),
            '--socket',str(observer),'--open-position','1.0'],env=env)
        controller_readiness(timeout_s=90);children.assert_alive()
        startup=directory/'startup';startup.mkdir(mode=0o700)
        if contacts:
            contacts_alive(contact_observer,contact_bridge)
            require_articulation(directory)
        home=children.start('startup-home',['/usr/bin/python3',
            str(ROOT/'deploy/robot/omx/sim_pick_place_teacher.py'),'--evidence',str(startup),
            '--world',str(world),'--observer',str(observer),'--home-only'],env=env)
        home_code=home.wait(timeout=min(180,max(.01,deadline-time.monotonic())))
        receipt=json.loads((startup/'teacher-result.json').read_text())
        if (home_code!=0 or receipt.get('success') is not True
                or receipt.get('purpose')!='startup_home_only'
                or receipt['owner_final']['active_goal'] is not None
                or receipt['owner_final']['owner_state']!='ready'):
            raise PermissionError('startup home process did not exit with idle owner proof')
        result['startup_owner_exited']=True
        if contacts:
            contacts_alive(contact_observer,contact_bridge)
            require_articulation(directory)
        command=['/usr/bin/python3',str(ROOT/'deploy/robot/omx/sim_pick_place_policy.py'),
            '--evidence',str(directory),'--observer',str(observer),'--deadline-owner-s',str(deadline)]
        if calibration:command.append('--calibration')
        # Keep ACT's CPU pool below the quota shared with the native simulator.
        policy_env=dict(env,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
        actor=children.start('policy',command,env=policy_env)
        code=(wait_contact_policy(actor,contact_observer,contact_bridge,deadline) if contacts
              else actor.wait(timeout=max(.01,deadline-time.monotonic())))
        policy=json.loads((directory/'policy-result.json').read_text())
        result['policy']=policy
        result['successes']=int(not calibration and code==0 and policy.get('success') is True)
        result['calibration_pass']=bool(calibration and code==0 and policy.get('success') is True
            and policy.get('policy_goals_sent')==0)
        result['policy_evaluation']='CALIBRATION_ONLY' if calibration else 'COMPLETED'
    except Exception as error:
        result['error']=type(error).__name__+': '+str(error)
    finally:
        if contacts:
            result['contacts'],result['cleanup_verified']=close_contact_diagnostic(
                contact_observer,children,directory,articulation=True)
        else:result['cleanup_verified']=children.close()
        result['wall_s']=time.monotonic()-started
        passed=bool(result['successes'] or result.get('calibration_pass'))
        result['result']='PASS' if (passed and result['cleanup_verified'] and not result.get('error')
            and (not contacts or result['contacts']['verified'])) else 'HOLD'
        write_json(directory/'result.json',result)
    return 0 if result['result']=='PASS' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--calibration',action='store_true')
    parser.add_argument('--contacts',action='store_true')
    parser.add_argument('--approve-isolated-simulation',action='store_true',required=True)
    parser.add_argument('--approve-startup-home',action='store_true',required=True)
    args=parser.parse_args()
    raise SystemExit(run(args.evidence,calibration=args.calibration,contacts=args.contacts))
