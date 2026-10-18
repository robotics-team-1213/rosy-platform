"""Read original ROS samples from existing producers; never opens camera or serial devices."""
from collections import OrderedDict
import threading
import time

from collection_profile import number, require, normalize


def stamp(message):
    return message.header.stamp.sec+message.header.stamp.nanosec/1e9


class RosInputs:
    def __init__(self, node, profile):
        from sensor_msgs.msg import CameraInfo, Image, JointState
        from control_msgs.msg import JointTrajectoryControllerState
        from dynamixel_interfaces.msg import DynamixelState
        from rclpy.qos import qos_profile_sensor_data
        self.node, self.profile = node, profile
        self.lock = threading.RLock()
        self.frames = {r: OrderedDict() for r in ('top', 'front')}
        self.rows, self.fault, self.subscriptions, self.intrinsics = {}, None, [], {}
        ros = profile['ros']
        specs = [(JointState, ros['joint_state_topic'], lambda m: self.positions('joints', m)),
                 (JointTrajectoryControllerState, ros['reference_topic'], lambda m: self.positions('reference', m)),
                 (DynamixelState, ros['hardware_topic'], self.hardware)]
        specs += [(Image, topic, lambda m, r=role: self.image(r, m)) for role, topic in ros['image_topics'].items()]
        specs += [(CameraInfo, topic, lambda m, r=role: self.camera_info(r, m))
                  for role, topic in ros.get('camera_info_topics', {}).items()]
        for kind, topic, callback in specs:
            def guarded(message, handler=callback):
                try:
                    handler(message)
                except Exception as exc:
                    with self.lock:
                        self.fault = str(exc)
            self.subscriptions.append(node.create_subscription(kind, topic, guarded, qos_profile_sensor_data))

    def positions(self, key, message):
        names = list(message.name if key == 'joints' else message.joint_names)
        values = message.position if key == 'joints' else (
            message.reference.positions if hasattr(message, 'reference') else message.desired.positions)
        require(names == self.profile['joint_names'] and len(values) == 6 and all(number(v) for v in values),
                key+' joint order/values differ')
        source = stamp(message)
        require(number(source) and source > 0, key+' invalid clock')
        with self.lock:
            require(source > self.rows.get(key, {}).get('stamp', 0), key+' replayed/reversed source')
            self.rows[key] = dict(stamp=source, received=time.monotonic(), values=list(values))

    def image(self, role, message):
        height, width, _ = self.profile['camera_shapes'][role]
        require(message.width == width and message.height == height and message.encoding in ('rgb8', 'bgr8')
                and message.step >= width*3 and len(message.data) == message.step*height, role+' image layout differs')
        packed = b''.join(bytes(message.data[row*message.step:row*message.step+width*3]) for row in range(height))
        if message.encoding == 'bgr8':
            rgb = bytearray(len(packed)); rgb[0::3] = packed[2::3]; rgb[1::3] = packed[1::3]; rgb[2::3] = packed[0::3]
            packed = bytes(rgb)
        source = stamp(message)
        require(number(source) and source > 0, role+' invalid image clock')
        with self.lock:
            buffer = self.frames[role]
            require(not buffer or source > next(reversed(buffer)), role+' replayed/reversed image')
            buffer[source] = dict(data=packed, width=width, height=height, source_stamp=source)
            while len(buffer) > 16:
                buffer.popitem(last=False)

    def camera_info(self, role, message):
        # Recorded as published by the existing producer; a declared model, not a verified calibration.
        height, width, _ = self.profile['camera_shapes'][role]
        k, d, r, p = (list(message.k), list(message.d), list(message.r), list(message.p))
        require(message.width == width and message.height == height and len(k) == 9 and len(r) == 9
                and len(p) == 12 and all(number(v) for v in k+d+r+p), role+' camera_info layout differs')
        with self.lock:
            self.intrinsics[role] = dict(frame_id=message.header.frame_id, width=width, height=height,
                                         distortion_model=message.distortion_model, d=d, k=k, r=r, p=p,
                                         binning=[message.binning_x, message.binning_y])

    def hardware(self, message):
        require(list(message.id) == self.profile['ros']['motor_ids'] and message.comm_state == 0
                and list(message.dxl_hw_state) == [0]*6
                and list(message.torque_state) == self.profile['ros']['expected_torque'],
                'hardware fault/torque differs')
        source = stamp(message)
        with self.lock:
            require(number(source) and source > self.rows.get('hardware', {}).get('stamp', 0),
                    'hardware clock reversed')
            self.rows['hardware'] = dict(stamp=source, received=time.monotonic())

    def snapshot(self, environment):
        now, wall = time.monotonic(), time.time_ns()
        with self.lock:
            require(self.fault is None, 'sensor fault: '+str(self.fault))
            require(all(key in self.rows for key in ('joints', 'reference', 'hardware')),
                    'waiting for native telemetry')
            joints, reference, hardware = (dict(self.rows[key]) for key in ('joints', 'reference', 'hardware'))
            maximum = self.profile['ros'].get('max_hardware_age_s', .25)
            require(0 <= now-hardware['received'] <= maximum and 0 <= wall/1e9-hardware['stamp'] <= maximum,
                    'hardware status stale/future')
            images = {r: dict(self.frames[r][environment['observations'][r]['source_stamp']]) for r in ('top', 'front')}
            configured = set(self.profile['ros'].get('camera_info_topics', {}))
            require(configured <= set(self.intrinsics), 'waiting for camera_info')
            intrinsics = {r: dict(self.intrinsics[r]) for r in sorted(configured)}
        return dict(time_ns=wall, environment=environment, images=images, camera_info=intrinsics,
                    observation_state=normalize(joints['values'], self.profile),
                    joint_positions=list(joints['values']),
                    action=normalize(reference['values'], self.profile),
                    joint_source_stamp=joints['stamp'], reference_source_stamp=reference['stamp'],
                    state_age_s=now-joints['received'], reference_age_s=now-reference['received'])

    def verify_publishers(self):
        ros = self.profile['ros']
        topics = {**ros['image_topics'], 'joints': ros['joint_state_topic'],
                  'reference': ros['reference_topic'], 'hardware': ros['hardware_topic']}
        for key, topic in topics.items():
            infos = self.node.get_publishers_info_by_topic(topic)
            expected = ros['publishers'][key]
            require(len(infos) == 1 and infos[0].node_name == expected['node_name']
                    and infos[0].node_namespace == expected['node_namespace'], key+' producer identity differs')
            gid = bytes(infos[0].endpoint_gid).hex()
            with self.lock:
                old = self.rows.setdefault('gid-'+key, gid)
                require(gid == old, key+' producer restarted')
