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
    from sim_pick_place_policy_job import wait_contacts,close_contact_diagnostic

    world=tmp_path/'contacts.sdf'
    binding=contact_world(ROOT/'integrations/simulation/gazebo/worlds/omx_cell_workcell_sim_aid.sdf',world)
    assert ET.parse(world).getroot().find("world/model[@name='omx_f']") is None
    write_json(tmp_path/'world-binding.json',binding)
    env=dict(os.environ,ROS_DOMAIN_ID='197',ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',
        GZ_PARTITION='rosy-contact-probe-'+uuid.uuid4().hex,
        GZ_SIM_PHYSICS_ENGINE_PATH='/opt/ros/jazzy/opt/gz_physics_vendor/lib')
    children=Children(tmp_path);observer=None
    try:
        children.start('gazebo',['gz','sim','-s','-r',str(world)],env=env)
        bridge=children.start('contact-bridge',['ros2','run','ros_gz_bridge','parameter_bridge',
            *[topic(label)+'@ros_gz_interfaces/msg/Contacts[gz.msgs.Contacts' for label in CHANNELS]],env=env)
        observer=children.start('contact-observer',['/usr/bin/python3',
            str(ROOT/'deploy/robot/omx/sim_policy_contacts.py'),'--evidence',str(tmp_path)],env=env)
        wait_contacts(observer,bridge,tmp_path,time.monotonic()+60)
    finally:
        report,clean=close_contact_diagnostic(observer,children,tmp_path)
        write_json(tmp_path/'contact-probe-closure.json',dict(capture=report,cleanup_verified=clean,
            robot_models_spawned=0,robot_commands_sent=0,policy_inferences=0,optimizer_steps=0,
            ros_domain_id=197,gz_partition=env['GZ_PARTITION']))
    assert clean and report['verified'],report
    capture=json.loads((tmp_path/'policy-contacts.json').read_text())
    assert set(capture['summary']['positive_control_channels'])==set(CHANNELS)
    forces=[w['body_1_wrench']['force'] for row in capture['samples']
            for contact in row['contacts'] for w in contact['wrenches']]
    assert forces and all(math.isfinite(v) for force in forces for v in force)
    assert any(sum(v*v for v in force)>0 for force in forces)
