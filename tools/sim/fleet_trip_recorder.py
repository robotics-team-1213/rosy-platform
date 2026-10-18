"""Read-only ROS evidence recorder for the Fleet/Gazebo diagnostic."""
import hashlib
import json
import math
from pathlib import Path
import time

#: Frames kept per robot: a 7.6 m lap at 0.08 m/s is ~100 s of a ~15 Hz camera, with stops.
MAX_FRAMES = 6000


def record_observations(out, robots):
    """Read-only diagnostic trace; received samples do not prove lossless frame coverage."""
    import rclpy
    import cv2
    from cv_bridge import CvBridge
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from rosidl_runtime_py.convert import message_to_ordereddict
    from std_msgs.msg import String, UInt16MultiArray
    from sensor_msgs.msg import Image, Imu, LaserScan
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from rosgraph_msgs.msg import Clock
    rclpy.init(args=[])
    node = rclpy.create_node('fleet_trip_recorder')
    qos = QoSProfile(depth=100, reliability=ReliabilityPolicy.BEST_EFFORT)
    bridge = CvBridge()
    images = Path(out).parent / 'frames'
    images.mkdir()
    captured = {ns: 0 for ns in robots}
    scans = {}
    try:
        with Path(out).open('x', buffering=1) as log:
            def receive(topic, msg):
                wall, monotonic = time.time(), time.monotonic()
                if isinstance(msg, Image):
                    ns = topic.split('/')[1]
                    value = dict(header=message_to_ordereddict(msg.header), width=msg.width,
                                 height=msg.height, encoding=msg.encoding)
                    if captured[ns] < MAX_FRAMES:
                        captured[ns] += 1
                        folder = images / ns
                        folder.mkdir(exist_ok=True)
                        path = folder / f'{captured[ns]:06d}.png'
                        if not cv2.imwrite(str(path), bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')):
                            raise RuntimeError('camera evidence write failed')
                        value.update(image_file=path.relative_to(Path(out).parent).as_posix(),
                                     sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                    else:
                        value['capture_skipped'] = f'{MAX_FRAMES}_frame_limit'
                    log.write(json.dumps(dict(wall=wall, monotonic=monotonic, topic=topic, message=value)) + '\n')
                    return
                # Sensor payloads are unnecessary for receipt/source timing and
                # would make the diagnostic recorder compete with the runtime.
                value = (dict(header=message_to_ordereddict(msg.header))
                         if isinstance(msg, (Imu, LaserScan)) else message_to_ordereddict(msg))
                if isinstance(msg, LaserScan):   # every 5th scan's ranges (cm): where the walls are
                    scans[topic] = scans.get(topic, 0) + 1
                    if scans[topic] % 5 == 1:
                        value.update(angle_min=msg.angle_min, angle_increment=msg.angle_increment,
                                     ranges=[round(r, 2) if math.isfinite(r) else None for r in msg.ranges])
                if isinstance(msg, String):
                    try:
                        value = json.loads(msg.data)
                    except ValueError:
                        pass  # Preserve malformed payloads as evidence.
                log.write(json.dumps(dict(wall=wall, monotonic=monotonic,
                                          topic=topic, message=value)) + '\n')
            topics = [('/clock', Clock)]
            for ns in robots:
                topics.extend((f'/{ns}/{name}', kind) for name, kind in (
                    ('line/keep_debug', String), ('line/observation', String),
                    ('cmd_vel', Twist), ('odom', Odometry),
                    ('scan', LaserScan), ('imu_raw', Imu),
                    ('ir_sensor/range', UInt16MultiArray),
                    ('safety/profile', String), ('camera/front', Image)))
            for topic, kind in topics:
                node.create_subscription(kind, topic, lambda msg, t=topic: receive(t, msg), qos)
            Path(str(out) + '.ready').touch()
            rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


