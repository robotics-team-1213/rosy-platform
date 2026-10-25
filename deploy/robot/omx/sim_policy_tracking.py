"""Bounded passive Jazzy controller-state capture; never a control decision."""
import math
import threading


def _vector(values,size,*,optional=False):
    result=list(values)
    if optional and not result:return result
    if len(result)!=size or any(type(v) not in (int,float) or not math.isfinite(v) for v in result):
        raise ValueError('finite controller vector with original joint order required')
    return result


class ControllerTracking:
    def __init__(self,joint_names,*,clock,command_reference):
        self._names=tuple(joint_names)
        self._clock=clock
        self._command=command_reference
        self._lock=threading.Lock()
        self._samples=[]
        self._last_ns=None
        self._closed=False
        self._invalid=0
        self._first_error=None
        self._truncated=False

    def failure(self,error):
        with self._lock:
            if not self._closed:
                self._invalid+=1
                if self._first_error is None:self._first_error=type(error).__name__

    def observe(self,message):
        try:
            # Read-only references, outside the collector lock; no owner/session lock.
            now=self._clock();command=self._command()
            if type(now) not in (int,float) or not math.isfinite(now) or now<0:
                raise ValueError('finite receipt clock required')
            if command is not None and (not isinstance(command,str) or len(command)>128):
                raise ValueError('bounded optional command reference required')
            received=int(now*1e9)
            with self._lock:
                if self._closed:return
                if self._last_ns is not None:
                    if received<self._last_ns:raise ValueError('receipt clock moved backward')
                    if received-self._last_ns<100_000_000:return
                if len(self._samples)>=6000:
                    self._truncated=True
                    return
                if tuple(message.joint_names)!=self._names:raise ValueError('joint order differs')
                stamp=message.header.stamp
                if (type(stamp.sec) is not int or stamp.sec<0 or type(stamp.nanosec) is not int
                        or not 0<=stamp.nanosec<1_000_000_000):
                    raise ValueError('original ROS timestamp required')
                sample=dict(ros_stamp_ns=stamp.sec*1_000_000_000+stamp.nanosec,
                    received_owner_ns=received,joint_names=list(self._names),
                    active_command_reference=command)
                for name in ('reference','feedback','error'):
                    point=getattr(message,name)
                    sample[name]=dict(positions=_vector(point.positions,len(self._names)),
                        velocities=_vector(point.velocities,len(self._names),optional=True))
                self._samples.append(sample)
                self._last_ns=received
        except Exception as error:
            self.failure(error)

    def finish(self,path,writer):
        with self._lock:
            self._closed=True
            summary=dict(status='complete' if self._samples and not self._invalid and not self._truncated
                         else 'incomplete',samples=len(self._samples),invalid_messages=self._invalid,
                         first_error=self._first_error,truncated=self._truncated)
            document=dict(schema='rosy.omx-sim-controller-tracking/1',sample_period_ns=100_000_000,
                command_reference_scope='observation_only_not_controller_goal_binding',
                summary=dict(summary),samples=list(self._samples))
        try:writer(path,document)
        except Exception as error:
            summary.update(status='incomplete',write_error=type(error).__name__)
        return summary
