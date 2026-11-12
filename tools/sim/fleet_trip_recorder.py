"""Read-only recording and evidence checks for Fleet/Gazebo trips."""
import hashlib
import json
import math
from pathlib import Path
import time

#: Frames kept per robot: a 7.6 m lap at 0.08 m/s is ~100 s of a ~15 Hz camera, with stops.
MAX_FRAMES = 6000


def cyclone_profile(root, nav=False):
    """Use more loopback DDS participant indexes when two Nav2 stacks are running."""
    base = Path(__file__).resolve().parents[2] / 'middleware/devices/pinky/bringup/config/cyclonedds_localhost.xml'
    if not nav:
        return base
    discovery = ('    <Discovery>\n      <ParticipantIndex>auto</ParticipantIndex>\n'
                 '      <MaxAutoParticipantIndex>120</MaxAutoParticipantIndex>\n    </Discovery>\n')
    xml = base.read_text(encoding='utf-8').replace('    </General>\n', '    </General>\n' + discovery, 1)
    assert '<MaxAutoParticipantIndex>' in xml
    (root / 'cyclonedds_nav.xml').write_text(xml, encoding='utf-8')
    return root / 'cyclonedds_nav.xml'


def drivable_evidence(path, revision, robots):
    """Require the requested model in keep_debug while the driven robot moves."""
    commands = {ns: [] for ns in robots}
    keeps = {ns: [] for ns in robots}
    if not path.is_file():
        return {'pass': False, 'reason': 'recorder output missing'}
    for line in path.open(encoding='utf-8'):
        try:
            row = json.loads(line)
            topic, message, wall = row['topic'], row['message'], row['wall']
            for ns in robots:
                if topic == f'/{ns}/cmd_vel':
                    linear = message['linear']
                    angular = message['angular']
                    if abs(linear['x']) > 0.001 or abs(angular['z']) > 0.001:
                        commands[ns].append(wall)
                elif topic == f'/{ns}/line/keep_debug':
                    keeps[ns].append((wall, message))
        except (KeyError, TypeError, ValueError):
            continue
    evidence = {}
    for ns in robots:
        during = [message for wall, message in keeps[ns]
                  if commands[ns] and commands[ns][0] <= wall <= commands[ns][-1]]
        matched = sum(message.get('paint_source_used') == 'learned_drivable'
                      and message.get('paint_model_revision') == revision for message in during
                      if isinstance(message, dict))
        wrong_revision = sum(message.get('paint_source_used') == 'learned_drivable'
                             and message.get('paint_model_revision') not in (None, revision) for message in during
                             if isinstance(message, dict))
        unknown_revision = sum(message.get('paint_source_used') == 'learned_drivable'
                               and message.get('paint_model_revision') is None for message in during
                               if isinstance(message, dict))
        fallback = sum(message.get('paint_source_used') == 'denoise_fallback' for message in during
                       if isinstance(message, dict))
        evidence[ns] = {'pass': len(during) >= 10 and matched / len(during) >= 0.99
                        and wrong_revision == 0,
                        'moving_commands': len(commands[ns]), 'moving_keep_debug': len(during),
                        'matched_revision': matched, 'wrong_revision': wrong_revision,
                        'unknown_revision_frames': unknown_revision, 'fallback_frames': fallback,
                        'pure_model': matched == len(during)}
    return {'pass': all(row['pass'] for row in evidence.values()),
            'expected_revision': revision, 'robots': evidence}


def image_bgr(msg):
    """Decode the simulator's raw camera image without ROS cv_bridge's NumPy ABI."""
    import cv2
    import numpy as np

    channels = {'bgr8': 3, 'rgb8': 3, 'bgra8': 4, 'rgba8': 4, 'mono8': 1}
    count = channels.get(msg.encoding)
    if count is None or msg.step < msg.width * count:
        raise ValueError(f'unsupported camera encoding: {msg.encoding}')
    raw = np.frombuffer(msg.data, dtype=np.uint8)
    if raw.size != msg.height * msg.step:
        raise ValueError('camera image byte count does not match step and height')
    image = raw.reshape(msg.height, msg.step)[:, :msg.width * count].reshape(
        msg.height, msg.width, count)
    convert = {'rgb8': cv2.COLOR_RGB2BGR, 'rgba8': cv2.COLOR_RGBA2BGR,
               'bgra8': cv2.COLOR_BGRA2BGR, 'mono8': cv2.COLOR_GRAY2BGR}
    return cv2.cvtColor(image, convert[msg.encoding]) if msg.encoding in convert else image


def record_observations(out, robots):
    """Read-only diagnostic trace; received samples do not prove lossless frame coverage."""
    import rclpy
    import cv2
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
                        if not cv2.imwrite(str(path), image_bgr(msg)):
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


