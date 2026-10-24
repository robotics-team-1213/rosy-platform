"""Explicit passive contacts preserve world geometry and distinguish silence from evidence."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import xml.etree.ElementTree as ET

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy/robot/omx'))


def module():
    return importlib.import_module('sim_policy_contacts')


def vector(value):
    return NS(x=value,y=0.,z=0.)


def message(*,empty=False):
    def entity(name,number):return NS(name=name,id=number,type=5)
    wrench=NS(header=NS(stamp=NS(sec=3,nanosec=4),frame_id=''),
        body_1_name=NS(data='table::top'),body_1_id=NS(data=10),
        body_2_name=NS(data='infeed_block::block'),body_2_id=NS(data=20),
        body_1_wrench=NS(force=vector(.2),torque=vector(.01)),
        body_2_wrench=NS(force=vector(-.2),torque=vector(-.01)))
    contact=NS(collision1=entity('table::top::collision',11),
        collision2=entity('infeed_block::block::collision',21),positions=[vector(.1)],
        normals=[vector(1.)],depths=[.0002],wrenches=[wrench])
    return NS(header=NS(stamp=NS(sec=3,nanosec=4),frame_id=''),contacts=[] if empty else [contact])


def test_contact_world_only_adds_sensors_and_contact_system(tmp_path):
    m=module();source=ROOT/'integrations/simulation/gazebo/worlds/omx_cell_workcell_sim_aid.sdf'
    before=source.read_bytes();target=tmp_path/'world.sdf';binding=m.contact_world(source,target)
    original=ET.fromstring(before);changed=ET.fromstring(target.read_bytes())
    world=changed.find('world');plugin=world.find("plugin[@name='gz::sim::systems::Contact']")
    assert plugin.get('filename')=='gz-sim-contact-system';world.remove(plugin)
    for label,(model,link) in m.CHANNELS.items():
        parent=world.find(f"model[@name='{model}']/link[@name='{link}']")
        sensor=parent.find("sensor[@type='contact']")
        assert sensor.findtext('contact/collision')=='collision'
        assert sensor.findtext('contact/topic')==m.topic(label)
        parent.remove(sensor)
    assert ET.tostring(original)==ET.tostring(changed)
    assert source.read_bytes()==before
    assert binding['source_sha256']==hashlib.sha256(before).hexdigest()
    assert binding['derived_sha256']==hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):m.contact_world(source,target)


def test_copies_original_positive_fields_and_never_fills_missing_wrenches():
    clock=[10.];m=module();trace=m.ContactCapture(clock=lambda:clock[0]);msg=message()
    trace.observe('table',msg);msg.contacts[0].depths[0]=99.
    clock[0]=10.2;msg=message();msg.contacts[0].wrenches=[];trace.observe('infeed',msg)
    doc=trace.finish();first=doc['samples'][0]
    assert first['ros_stamp_ns']==3_000_000_004 and first['received_owner_ns']==10_000_000_000
    assert first['contacts'][0]['depths']==[.0002]
    assert first['contacts'][0]['wrenches'][0]['body_1_wrench']['force']==[.2,0.,0.]
    assert doc['samples'][1]['contacts'][0]['wrenches']==[]
    assert doc['coverage']=='positive_contacts_only_silence_unknown'
    assert doc['summary']['status']=='captured' and trace.ready
    trace.observe('table',message());assert len(doc['samples'])==2
    json.dumps(doc,allow_nan=False)


def test_empty_and_unreceived_are_distinct_and_do_not_pass_positive_warmup():
    m=module();trace=m.ContactCapture(clock=lambda:10.)
    trace.observe('table',message(empty=True));doc=trace.finish()
    assert doc['channels']['table']['empty_messages']==1
    assert doc['channels']['infeed']['messages']==0
    assert not trace.ready and doc['summary']['status']=='incomplete'


@pytest.mark.parametrize('fault',['nan','stamp','entity','point_count','unknown_topic'])
def test_invalid_or_truncated_input_cannot_claim_complete_capture(fault):
    m=module();trace=m.ContactCapture(clock=lambda:10.);msg=message();label='table'
    if fault=='nan':msg.contacts[0].depths=[float('nan')]
    elif fault=='stamp':msg.header.stamp.nanosec=1_000_000_000
    elif fault=='entity':msg.contacts[0].collision1.name='x'*1025
    elif fault=='point_count':msg.contacts[0].positions=[vector(0.)]*9
    else:label='unregistered'
    trace.observe(label,msg);doc=trace.finish()
    assert doc['summary']['status']=='incomplete'
    assert doc['summary']['invalid_messages'] or doc['summary']['truncated']


def test_per_channel_sampling_retains_positive_gap_without_no_contact_inference():
    clock=[10.];m=module();trace=m.ContactCapture(clock=lambda:clock[0])
    trace.observe('table',message());trace.observe('infeed',message())
    clock[0]=10.01;trace.observe('table',message())
    clock[0]=13.;trace.observe('table',message())
    doc=trace.finish();assert len(doc['samples'])==3
    assert doc['channels']['table']['maximum_receipt_gap_ns']==3_000_000_000
    assert doc['coverage']=='positive_contacts_only_silence_unknown'


def test_sample_cap_is_explicit_per_channel():
    clock=[0.];m=module();trace=m.ContactCapture(clock=lambda:clock[0])
    for i in range(6001):
        clock[0]=i*.2;trace.observe('table',message())
    doc=trace.finish();assert len(doc['samples'])==6000
    assert doc['summary']['truncated'] and doc['summary']['status']=='incomplete'
