"""ROS-free MCAP decoder for recorded Pinky topics; no middleware imports."""
import json
import math
from pathlib import Path
import re

TOPICS = ('camera/front/compressed', 'camera/front', 'cmd_vel', 'odom', 'scan',
          'line/observation', 'perception/learned/shadow', 'teleop/intent', 'ir_sensor/range')
SCHEMAS = {'camera/front': 'sensor_msgs/msg/Image',
           'camera/front/compressed': 'sensor_msgs/msg/CompressedImage',
           'cmd_vel': 'geometry_msgs/msg/Twist', 'odom': 'nav_msgs/msg/Odometry',
           'scan': 'sensor_msgs/msg/LaserScan', 'line/observation': 'std_msgs/msg/String',
           'perception/learned/shadow': 'std_msgs/msg/String', 'teleop/intent': 'std_msgs/msg/String',
           'ir_sensor/range': 'std_msgs/msg/UInt16MultiArray'}
# Same acceptance as control.recording.ir_range_sample. This module does not import it.
_IR_CHANNELS = ('left', 'centre', 'right')
_IR_ADC_MAX = 4095


def ir_sample(data):
    """{left, centre, right} raw ADC counts, or None. Ultrasonic is not this message."""
    try:
        values = list(data)
    except TypeError:
        return None
    if len(values) != 3:
        return None
    sample = {}
    for name, value in zip(_IR_CHANNELS, values):
        if isinstance(value, (bool, float, str)):
            return None
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        if number < 0 or number > _IR_ADC_MAX:
            return None
        sample[name] = number
    return sample


def topic_name(topic):
    return next((name for name in TOPICS if topic == name or topic.endswith('/' + name)), None)


def stamp_ns(msg):
    if not 0 <= msg.header.stamp.nanosec < 1_000_000_000:
        raise ValueError('raw ROS header nanosecond field invalid')
    return msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec


def camera_size(schema, msg):
    if schema == 'sensor_msgs/msg/CompressedImage':
        import cv2
        import numpy as np
        image = cv2.imdecode(np.frombuffer(bytes(msg.data), np.uint8), cv2.IMREAD_COLOR)
        return None if image is None else (image.shape[1], image.shape[0])
    channels = {'rgb8': 3, 'bgr8': 3, 'mono8': 1, 'bgra8': 4, 'rgba8': 4}.get(msg.encoding.lower())
    if channels is None:
        raise ValueError('raw camera encoding unsupported')
    if (not msg.width or not msg.height or msg.step != msg.width * channels
            or len(msg.data) != msg.height * msg.step):
        return None
    return msg.width, msg.height


def clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


def load_tables(raw):
    from mcap.reader import make_reader
    from mcap_ros2.decoder import DecoderFactory
    import numpy as np
    tables, namespaces, schemas, skipped, last_camera = {}, set(), {}, 0, None
    files = sorted((Path(raw) / 'bag').glob('*.mcap'), key=lambda path: (
        int(re.search(r'(\d+)(?=\.mcap$)', path.name).group(1))
        if re.search(r'(\d+)(?=\.mcap$)', path.name) else -1, path.name))
    for path in files:
        with path.open('rb') as stream:
            reader = make_reader(stream, validate_crcs=True, decoder_factories=[DecoderFactory()])
            summary = reader.get_summary()
            if summary is None:
                raise ValueError('raw MCAP summary required')
            topics = [channel.topic for channel in summary.channels.values() if topic_name(channel.topic)]
            for schema, channel, message, msg in reader.iter_decoded_messages(topics=topics):
                name = topic_name(channel.topic)
                if schema.name != SCHEMAS[name] or schema.encoding != 'ros2msg' or channel.message_encoding != 'cdr':
                    raise ValueError('raw topic message schema/encoding differs')
                namespaces.add(channel.topic[:-len(name)].rstrip('/'))
                if len(namespaces) != 1:
                    raise ValueError('raw recording mixes robot namespaces')
                schemas[name] = schema.name
                log = message.log_time
                if name.startswith('camera/front'):
                    size = camera_size(schema.name, msg)
                    if size is None or (last_camera is not None and log < last_camera):
                        skipped += 1
                        continue
                    last_camera = log
                    name = 'camera'
                    value = {'stamp_ns': stamp_ns(msg), 'width': size[0], 'height': size[1]}
                elif name == 'cmd_vel':
                    value = {'linear': msg.linear.x, 'angular': msg.angular.z}
                elif name == 'odom':
                    p, q = msg.pose.pose.position, msg.pose.pose.orientation
                    value = {'x': p.x, 'y': p.y, 'yaw': math.atan2(
                        2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))}
                elif name == 'scan':
                    value = {'stamp_ns': stamp_ns(msg), 'ranges': np.asarray(msg.ranges, np.float16),
                             **{key: float(getattr(msg, key)) for key in (
                                 'angle_min', 'angle_max', 'angle_increment', 'range_min', 'range_max')}}
                elif name == 'ir_sensor/range':
                    value = ir_sample(msg.data)
                    if value is None:
                        skipped += 1
                        continue
                else:
                    value = json.loads(msg.data)
                tables.setdefault(name, []).append((log, value))
    for name, series in tables.items():
        if any(series[i][0] < series[i - 1][0] for i in range(1, len(series))):
            raise ValueError('raw topic log clocks not ordered across bag splits')
    return tables, {'namespaces': sorted(namespaces), 'schemas': schemas, 'skipped_frames': skipped,
                    'bag_files': len(files)}
