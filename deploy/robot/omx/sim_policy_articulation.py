"""Bounded original controller-exported ECS states; no command authority."""
from sim_policy_contacts import _number, _stamp, _text

JOINTS=frozenset(['joint1','joint2','joint3','joint4','joint5','gripper_joint_1','gripper_joint_2'])
SCHEMA='rosy.omx-articulation-observation/1'
COVERAGE='sampled_controller_exported_ecs_state'
MAX_SAMPLES=60000
SAMPLE_PERIOD_NS=10_000_000


class ArticulationCapture:
    def __init__(self,*,clock):
        self.clock=clock;self.samples=[];self.closed=False;self.invalid=0;self.truncated=False
        self.messages=0;self.first_error=None;self.first_received=None;self.last_received=None
        self.last_source=None;self.latest_advance=None;self.maximum_gap=0
        self.first_positive_stored=None;self.stored_advance=False

    @property
    def ready(self):
        return not self.invalid and not self.truncated and self.stored_advance

    def status(self):
        return dict(schema=SCHEMA,ready=self.ready,invalid_messages=self.invalid,truncated=self.truncated,
            latest_advance_owner_ns=self.latest_advance,source_stamp_ns=self.last_source)

    def observe(self,message):
        if self.closed:return
        self.messages+=1
        try:
            now=_number(self.clock())
            if now<0:raise ValueError('negative receipt clock')
            received=int(now*1e9);stamp=_stamp(message.header)
            names=[_text(name) for name in message.name]
            if len(names)!=7 or set(names)!=JOINTS:raise ValueError('exact seven joints required')
            positions=[_number(value) for value in message.position]
            velocities=[_number(value) for value in message.velocity]
            if len(positions)!=7 or len(velocities) not in (0,7):raise ValueError('joint shape mismatch')
            frame=_text(message.header.frame_id)
            if self.last_received is not None:
                if received<self.last_received:raise ValueError('receipt clock moved backward')
                self.maximum_gap=max(self.maximum_gap,received-self.last_received)
            if self.last_source is not None and stamp<self.last_source:
                raise ValueError('source clock moved backward')
            if self.last_source is None or stamp>self.last_source:self.latest_advance=received
            if self.first_received is None:self.first_received=received
            self.last_received=received;self.last_source=stamp
            # Validate every message before limiting stored samples.
            if self.samples and received-self.samples[-1]['received_owner_ns']<SAMPLE_PERIOD_NS:return
            if len(self.samples)>=MAX_SAMPLES:self.truncated=True;return
            if stamp>0:
                if self.first_positive_stored is None:self.first_positive_stored=stamp
                elif stamp>self.first_positive_stored:self.stored_advance=True
            self.samples.append(dict(joint_names=names,positions=positions,velocities=velocities,
                ros_stamp_ns=stamp,frame_id=frame,received_owner_ns=received))
        except Exception as error:
            self.invalid+=1
            if self.first_error is None:self.first_error=type(error).__name__

    def finish(self):
        self.closed=True
        try:
            ended=int(_number(self.clock())*1e9)
            if ended<0 or self.last_received is not None and ended<self.last_received:
                raise ValueError('receipt clock moved backward')
        except Exception as error:
            ended=None;self.invalid+=1
            if self.first_error is None:self.first_error=type(error).__name__
        return dict(schema=SCHEMA,coverage=COVERAGE,sample_period_ns=SAMPLE_PERIOD_NS,
            maximum_samples=MAX_SAMPLES,messages=self.messages,samples=self.samples,
            first_ros_stamp_ns=self.samples[0]['ros_stamp_ns'] if self.samples else None,
            last_ros_stamp_ns=self.last_source,
            first_received_owner_ns=self.first_received,last_received_owner_ns=self.last_received,
            maximum_receipt_gap_ns=self.maximum_gap,ended_owner_ns=ended,
            end_gap_ns=ended-self.last_received if ended is not None and self.last_received is not None else None,
            summary=dict(status='captured' if self.ready else 'incomplete',
                invalid_messages=self.invalid,truncated=self.truncated,first_error=self.first_error))
