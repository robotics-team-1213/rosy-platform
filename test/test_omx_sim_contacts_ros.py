"""Opt-in installed SDK probe: passive cube/table contacts, no robot or command owner."""
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid
import xml.etree.ElementTree as ET

import pytest

pytestmark=pytest.mark.skipif(os.environ.get('ROSY_RUN_CONTACT_SENSOR_TEST')!='1',
    reason='requires approved isolated Gazebo/ROS SDK test actor')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy/robot/omx'))


def test_real_contacts_bridge_preserves_positive_force_and_owned_cleanup(tmp_path):
    from g2_ports import write_json
    from g2_runner import Children
    from sim_policy_contacts import contact_world,CHANNELS,topic
    from sim_pick_place_policy_job import wait_contacts,wait_articulation,close_contact_diagnostic

    world=tmp_path/'contacts.sdf'
    binding=contact_world(ROOT/'integrations/simulation/gazebo/worlds/omx_cell_workcell_sim_aid.sdf',world)
    assert ET.parse(world).getroot().find("world/model[@name='omx_f']") is None
    write_json(tmp_path/'world-binding.json',binding)
    env=dict(os.environ,ROS_DOMAIN_ID='197',ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',
        ROSY_OMX_ROS_NAMESPACE='/articulation_probe',
        GZ_PARTITION='rosy-contact-probe-'+uuid.uuid4().hex,
        GZ_SIM_PHYSICS_ENGINE_PATH='/opt/ros/jazzy/opt/gz_physics_vendor/lib')
    children=Children(tmp_path);observer=None
    try:
        children.start('gazebo',['gz','sim','-s','-r',str(world)],env=env)
        bridge=children.start('contact-bridge',['ros2','run','ros_gz_bridge','parameter_bridge',
            *[topic(label)+'@ros_gz_interfaces/msg/Contacts[gz.msgs.Contacts' for label in CHANNELS]],env=env)
        observer=children.start('contact-observer',['/usr/bin/python3',
            str(ROOT/'deploy/robot/omx/sim_policy_contacts.py'),'--evidence',str(tmp_path)],env=env)
        # Synthetic transport only: this world contains no robot or command owner.
        publisher='''import rclpy
from sensor_msgs.msg import JointState
rclpy.init()
node=rclpy.create_node('synthetic_articulation_probe')
publisher=node.create_publisher(JointState,'/articulation_probe/joint_states',10)
def publish():
    msg=JointState()
    msg.header.stamp=node.get_clock().now().to_msg()
    msg.header.frame_id='synthetic_transport_only'
    msg.name=['joint1','joint2','joint3','joint4','joint5','gripper_joint_1','gripper_joint_2']
    msg.position=[.1,.2,.3,.4,.5,.6,-.6]
    publisher.publish(msg)
node.create_timer(.02,publish)
rclpy.spin(node)
'''
        children.start('synthetic-articulation',['/usr/bin/python3','-c',publisher],env=env)
        deadline=time.monotonic()+60
        wait_contacts(observer,bridge,tmp_path,deadline)
        wait_articulation(observer,bridge,tmp_path,deadline)
    finally:
        report,clean=close_contact_diagnostic(observer,children,tmp_path,articulation=True)
        write_json(tmp_path/'contact-probe-closure.json',dict(capture=report,cleanup_verified=clean,
            robot_models_spawned=0,robot_commands_sent=0,policy_inferences=0,optimizer_steps=0,
            ros_domain_id=197,gz_partition=env['GZ_PARTITION'],
            articulation_source='synthetic_transport_only',actual_robot_articulation_verified=False))
    assert clean and report['verified'],report
    capture=json.loads((tmp_path/'policy-contacts.json').read_text())
    assert set(capture['summary']['positive_control_channels'])==set(CHANNELS)
    forces=[w['body_1_wrench']['force'] for row in capture['samples']
            for contact in row['contacts'] for w in contact['wrenches']]
    assert forces and all(math.isfinite(v) for force in forces for v in force)
    assert any(sum(v*v for v in force)>0 for force in forces)
    joints=json.loads((tmp_path/'policy-articulation.json').read_text())
    assert len(joints['samples'])>=2
    assert all(row['positions']==[.1,.2,.3,.4,.5,.6,-.6] and row['velocities']==[]
        and row['frame_id']=='synthetic_transport_only' for row in joints['samples'])
    assert joints['samples'][-1]['ros_stamp_ns']>joints['samples'][0]['ros_stamp_ns']>0
