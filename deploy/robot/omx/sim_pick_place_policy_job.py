"""One fresh native world per checkpoint trial, with an exited startup owner."""
import argparse
import json
import os
from pathlib import Path
import time

from g2_common import ROOT, controller_readiness
from g2_ports import isolation_guard, write_json
from g2_runner import Children
from sim_pick_place_demonstrations import camera_world


def run(directory,*,calibration=False):
    isolation_guard(ROOT)
    directory.mkdir(mode=0o700)
    children=Children(directory)
    started=time.monotonic();deadline=started+600
    result=dict(experiment='pick-place-policy-calibration' if calibration else 'pick-place-policy',
        attempts=0 if calibration else 1,successes=0,sim_aid=True,
        policy_evaluation='CALIBRATION_ONLY' if calibration else 'STARTED',
        physical_device_authority=False,operating_fleet_approval='NOT_CLAIMED')
    try:
        worlds=ROOT/'integrations/simulation/gazebo/worlds'
        world=directory/'camera-world.sdf'
        binding=camera_world(worlds/'omx_cell_workcell_sim_aid.sdf',worlds/'omx_pilot_workcell.sdf',world)
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
        observer=directory/'observer.sock'
        children.start('observer',['/usr/bin/python3',str(ROOT/'deploy/robot/omx/g2_observer.py'),
            '--socket',str(observer),'--open-position','1.0'],env=env)
        controller_readiness(timeout_s=90);children.assert_alive()
        startup=directory/'startup';startup.mkdir(mode=0o700)
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
        command=['/usr/bin/python3',str(ROOT/'deploy/robot/omx/sim_pick_place_policy.py'),
            '--evidence',str(directory),'--observer',str(observer),'--deadline-owner-s',str(deadline)]
        if calibration:command.append('--calibration')
        # Keep ACT's CPU pool below the quota shared with the native simulator.
        policy_env=dict(env,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
        actor=children.start('policy',command,env=policy_env)
        code=actor.wait(timeout=max(.01,deadline-time.monotonic()))
        policy=json.loads((directory/'policy-result.json').read_text())
        result['policy']=policy
        result['successes']=int(not calibration and code==0 and policy.get('success') is True)
        result['calibration_pass']=bool(calibration and code==0 and policy.get('success') is True
            and policy.get('policy_goals_sent')==0)
        result['policy_evaluation']='CALIBRATION_ONLY' if calibration else 'COMPLETED'
    except Exception as error:
        result['error']=type(error).__name__+': '+str(error)
    finally:
        result['cleanup_verified']=children.close()
        result['wall_s']=time.monotonic()-started
        passed=bool(result['successes'] or result.get('calibration_pass'))
        result['result']='PASS' if passed and result['cleanup_verified'] and not result.get('error') else 'HOLD'
        write_json(directory/'result.json',result)
    return 0 if result['result']=='PASS' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--calibration',action='store_true')
    parser.add_argument('--approve-isolated-simulation',action='store_true',required=True)
    parser.add_argument('--approve-startup-home',action='store_true',required=True)
    args=parser.parse_args()
    raise SystemExit(run(args.evidence,calibration=args.calibration))
