"""Original fixed-world RGB and CameraInfo for the explicit SIM policy caller."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import threading

from omx_adapter.camera_contract import CameraFrameGate
from rosy.execution.local.omx_policy import CameraSnapshot
from sim_policy_install import CAMERA_INFO, WORLD

# Retain every retry: 600 s / 10 ms plus 600 outer policy cycles, without RGB copies.
MAX_CAPTURE_RECORDS=60_600


@dataclass(frozen=True)
class CameraPacket:
    metadata: CameraSnapshot
    rgb: bytes
    source_stamp_ns: int


def packet_from_message(message, *, sim_now_ns, owner_received_ns):
    stamp=message.header.stamp.sec*1_000_000_000+message.header.stamp.nanosec
    if (message.encoding!='rgb8' or (message.height,message.width,message.step)!=(240,320,960)
            or message.header.frame_id!='workcell_camera_optical' or len(message.data)!=320*240*3
            or type(owner_received_ns) is not int or owner_received_ns<0
            or stamp<0 or not 0<=sim_now_ns-stamp<=500_000_000):
        raise ValueError('fixed original RGB layout, identity and fresh SIM stamp required')
    raw=bytes(message.data)
    metadata=CameraSnapshot('front','gazebo:omx_cell_workcell:front:'+WORLD,CAMERA_INFO,
        (3,240,320),owner_received_ns,hashlib.sha256(raw).hexdigest())
    return CameraPacket(metadata,raw,stamp)


class SimPolicyCamera:
    def __init__(self,node,monotonic):
        from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import Image, CameraInfo
        self.node,self.clock=node,monotonic
        self._lock=threading.RLock()
        self._latest,self._stamp=None,-1
        self._info=False
        self.error=None
        self.accepted,self.rejected=0,0
        self.captures=[]
        self.group=MutuallyExclusiveCallbackGroup()
        self.subscriptions=[
            node.create_subscription(Image,'/workcell_camera/image',self.receive,qos_profile_sensor_data,
                                     callback_group=self.group),
            node.create_subscription(CameraInfo,'/workcell_camera/camera_info',self.info,qos_profile_sensor_data,
                                     callback_group=self.group)]

    def info(self,message):
        with self._lock:
            if CameraFrameGate.camera_info_fingerprint(message)!=CAMERA_INFO:
                self.error='fixed CameraInfo fingerprint differs'
                self._latest=None
            elif not self.error:
                self._info=True

    def receive(self,message):
        received=int(self.clock()*1e9)
        try:
            packet=packet_from_message(message,sim_now_ns=self.node.get_clock().now().nanoseconds,
                                       owner_received_ns=received)
        except ValueError:
            with self._lock:self.rejected+=1
            return
        with self._lock:
            if self.error or not self._info or packet.source_stamp_ns<=self._stamp:
                self.rejected+=1
                return
            self._latest,self._stamp=packet,packet.source_stamp_ns
            self.accepted+=1

    def snapshots(self):
        with self._lock:
            return () if self._latest is None else (self._latest.metadata,)

    @contextmanager
    def capture(self):
        with self._lock:
            if self._latest is None or self.error:
                raise PermissionError('original fixed SIM camera unavailable')
            if len(self.captures)>=MAX_CAPTURE_RECORDS:
                raise RuntimeError('bounded policy capture limit')
            packet=self._latest
            self.captures.append(dict(frame_sha256=packet.metadata.frame_sha256,
                received_owner_ns=packet.metadata.received_at_ns,source_sim_ns=packet.source_stamp_ns))
            yield packet

    def destroy(self):
        for subscription in self.subscriptions:self.node.destroy_subscription(subscription)
