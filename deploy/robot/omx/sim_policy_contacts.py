"""Passive, bounded contacts for an explicitly selected isolated SIM study."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import signal
import threading
import time
import xml.etree.ElementTree as ET

CHANNELS={'table':('table','top'),'infeed':('infeed_block','block')}
COVERAGE='positive_contacts_only_silence_unknown'


def topic(channel):
    if channel not in CHANNELS:raise ValueError('unknown contact channel')
    return '/rosy_diag_contacts/'+channel


def contact_world(source,output):
    tree=ET.parse(source);world=tree.getroot().find('world')
    if world is None or world.get('name')!='omx_cell_workcell':
        raise ValueError('unexpected contact diagnostic world')
    if world.find("plugin[@name='gz::sim::systems::Contact']") is not None:
        raise ValueError('contact diagnostic already present')
    ET.SubElement(world,'plugin',filename='gz-sim-contact-system',name='gz::sim::systems::Contact')
    for label,(model,link) in CHANNELS.items():
        parent=world.find(f"model[@name='{model}']/link[@name='{link}']")
        if parent is None or parent.find("collision[@name='collision']") is None:
            raise ValueError('pinned diagnostic collision missing')
        sensor=ET.SubElement(parent,'sensor',name='policy_contact_diagnostic',type='contact')
        ET.SubElement(sensor,'always_on').text='true'
        contact=ET.SubElement(sensor,'contact')
        ET.SubElement(contact,'collision').text='collision'
        ET.SubElement(contact,'topic').text=topic(label)
    with Path(output).open('xb') as stream:
        tree.write(stream,encoding='utf-8',xml_declaration=True)
    return dict(source_sha256=hashlib.sha256(Path(source).read_bytes()).hexdigest(),
        derived_sha256=hashlib.sha256(Path(output).read_bytes()).hexdigest(),
        topics={label:topic(label) for label in CHANNELS})


def _text(value):
    if not isinstance(value,str) or len(value)>512:raise ValueError('bounded original name required')
    return value


def _integer(value,maximum=2**64-1):
    if type(value) is not int or not 0<=value<=maximum:raise ValueError('original unsigned integer required')
    return value


def _number(value):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('finite contact value required')
    return value


def _vector(value):
    return [_number(getattr(value,name)) for name in ('x','y','z')]


def _stamp(header):
    return _integer(header.stamp.sec,2**31-1)*1_000_000_000+_integer(header.stamp.nanosec,999_999_999)


def _entity(entity):
    return dict(name=_text(entity.name),id=_integer(entity.id),type=_integer(entity.type,7))


def _wrench(value):
    result=dict(ros_stamp_ns=_stamp(value.header),frame_id=_text(value.header.frame_id))
    for body in ('body_1','body_2'):
        result[body+'_name']=_text(getattr(value,body+'_name').data)
        result[body+'_id']=_integer(getattr(value,body+'_id').data,2**32-1)
        wrench=getattr(value,body+'_wrench')
        result[body+'_wrench']=dict(force=_vector(wrench.force),torque=_vector(wrench.torque))
    return result


class ContactCapture:
    def __init__(self,*,clock):
        self.clock=clock;self.samples=[];self.closed=False;self.invalid=0;self.truncated=False
        self.first_error=None;self.positive=set()
        self.channels={name:dict(messages=0,empty_messages=0,samples=0,first_received_owner_ns=None,
            last_received_owner_ns=None,last_stored_owner_ns=None,maximum_receipt_gap_ns=0)
            for name in CHANNELS}

    @property
    def ready(self):
        return self.positive==set(CHANNELS)

    def observe(self,channel,message):
        if self.closed:return
        try:
            if channel not in CHANNELS:raise ValueError('unknown contact channel')
            now=_number(self.clock())
            if now<0:raise ValueError('negative receipt clock')
            received=int(now*1e9);stamp=_stamp(message.header);stats=self.channels[channel]
            previous=stats['last_received_owner_ns']
            if previous is not None:
                if received<previous:raise ValueError('receipt clock moved backward')
                stats['maximum_receipt_gap_ns']=max(stats['maximum_receipt_gap_ns'],received-previous)
            if stats['first_received_owner_ns'] is None:stats['first_received_owner_ns']=received
            stats['last_received_owner_ns']=received;stats['messages']+=1
            if not message.contacts:stats['empty_messages']+=1
            if len(message.contacts)>16:self.truncated=True
            contacts=[]
            for value in message.contacts[:16]:
                row=dict(collision1=_entity(value.collision1),collision2=_entity(value.collision2))
                for name,convert in [('positions',_vector),('normals',_vector),('depths',_number),('wrenches',_wrench)]:
                    values=getattr(value,name)
                    if len(values)>8:self.truncated=True
                    row[name]=[convert(v) for v in values[:8]]
                contacts.append(row)
            frame=dict(channel=channel,topic=topic(channel),ros_stamp_ns=stamp,
                frame_id=_text(message.header.frame_id),received_owner_ns=received,
                original_contact_count=len(message.contacts),contacts=contacts)
            # Sampling bounds storage, never the validity of received evidence.
            stored=stats['last_stored_owner_ns']
            if stored is not None and received-stored<100_000_000:return
            if stats['samples']>=6000:self.truncated=True;return
            self.samples.append(frame);stats['samples']+=1;stats['last_stored_owner_ns']=received
            for row in contacts:
                names=[row[k]['name'] for k in ('collision1','collision2')]
                if (any(n.endswith('table::top::collision') for n in names)
                        and any(n.endswith('infeed_block::block::collision') for n in names)):
                    self.positive.add(channel)
        except Exception as error:
            self.invalid+=1
            if self.first_error is None:self.first_error=type(error).__name__

    def finish(self):
        self.closed=True
        try:
            ended=int(_number(self.clock())*1e9)
            if any(stats['last_received_owner_ns'] is not None and ended<stats['last_received_owner_ns']
                   for stats in self.channels.values()):raise ValueError('receipt clock moved backward')
        except Exception as error:
            ended=None;self.invalid+=1
            if self.first_error is None:self.first_error=type(error).__name__
        for stats in self.channels.values():
            last=stats['last_received_owner_ns']
            stats['end_gap_ns']=ended-last if ended is not None and last is not None else None
        return dict(schema='rosy.omx-contact-observation/1',coverage=COVERAGE,
            ended_owner_ns=ended,
            frame_convention='original_published_fields_no_frame_conversion',sample_period_ns=100_000_000,
            maximum_samples_per_channel=6000,channels=self.channels,samples=self.samples,
            summary=dict(status='captured' if self.ready and not self.invalid and not self.truncated else 'incomplete',
                invalid_messages=self.invalid,first_error=self.first_error,truncated=self.truncated,
                positive_control_channels=sorted(self.positive)))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    import rclpy
    from rclpy.signals import SignalHandlerOptions
    from rclpy.qos import qos_profile_sensor_data
    from ros_gz_interfaces.msg import Contacts
    from sensor_msgs.msg import JointState
    from instance_names import names_from_environment
    from sim_policy_articulation import ArticulationCapture
    from g2_ports import write_json
    stop=threading.Event();capture=ContactCapture(clock=time.monotonic)
    articulation=ArticulationCapture(clock=time.monotonic)
    rclpy.init(args=[],signal_handler_options=SignalHandlerOptions.NO)
    node=rclpy.create_node('omx_contact_diagnostic')
    node.create_subscription(JointState,names_from_environment().joint_state_topic,
        articulation.observe,qos_profile_sensor_data)
    for label in CHANNELS:
        node.create_subscription(Contacts,topic(label),lambda message,label=label:capture.observe(label,message),
            qos_profile_sensor_data)
    for number in (signal.SIGTERM,signal.SIGINT):signal.signal(number,lambda *_:stop.set())
    ready=False;articulation_status_written=False;last_status=0.
    try:
        while rclpy.ok() and not stop.is_set():
            rclpy.spin_once(node,timeout_sec=.1)
            if capture.ready and not ready:
                pending=args.evidence/'contact-ready.pending.json'
                write_json(pending,dict(positive_control_channels=sorted(capture.positive)))
                pending.rename(args.evidence/'contact-ready.json')
                ready=True
            now=time.monotonic()
            if (articulation.ready or articulation_status_written) and now-last_status>=.1:
                pending=args.evidence/'articulation-ready.pending.json'
                write_json(pending,articulation.status())
                pending.replace(args.evidence/'articulation-ready.json')
                articulation_status_written=True;last_status=now
    finally:
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
        try:write_json(args.evidence/'policy-contacts.json',capture.finish())
        finally:write_json(args.evidence/'policy-articulation.json',articulation.finish())


if __name__=='__main__':main()
