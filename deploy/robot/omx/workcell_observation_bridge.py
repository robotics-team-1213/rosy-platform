"""Fleet-host read-only ROS observations to authenticated Fleet and Vision ingress."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import logging
import math
from pathlib import Path
import ssl
import threading
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from uuid import uuid4

import yaml

from core_common.protocol.workcell_observations import ArmObservation, WorkcellObservationManifest
from core_common.motor_health import read_motor_health_snapshot
from core_common.protocol.motor_health import MotorHealthResponse
from rosy_vision import protocol


def select_sources(manifest, workcell_id, environ):
    cell = next((cell for cell in manifest.workcells if cell.workcell_id == workcell_id), None)
    if cell is None:
        raise ValueError('unknown observation workcell')
    tokens = {}
    for source in [*cell.arms, *cell.cameras]:
        token = environ.get(source.token_env)
        if (not isinstance(token, str) or not token
                or not hmac.compare_digest(sha256(token.encode()).hexdigest(), source.credential_sha256)):
            raise ValueError('source credential missing or fingerprint mismatch')
        tokens[source.source_id] = token
    return cell, tokens


def secure_url(value, scheme):
    url = urlsplit(value)
    if (any(char.isspace() or ord(char) < 32 for char in value)
            or url.scheme != scheme or not url.hostname or url.username or url.password or url.query or url.fragment
            or (scheme == 'https' and url.path not in ('', '/'))
            or (scheme == 'wss' and url.path not in ('', '/', protocol.WS_PATH))):
        raise ValueError('explicit HTTPS Fleet origin and WSS Vision ingress are required')
    url.port
    return value.rstrip('/')


def _verified(context):
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise ValueError('verified TLS is required')
    return context


@dataclass(frozen=True)
class Sample:
    captured_at: float
    received_at: float
    sequence: int
    value: object
    motor_health: MotorHealthResponse | None = None


def sample_age(sample, wall, monotonic):
    source_age, receipt_age = wall - sample.captured_at, monotonic - sample.received_at
    if not (-0.25 <= source_age <= 2 and 0 <= receipt_age <= 2):
        raise ValueError('observation capture or receipt is stale or future')
    return max(0, source_age, receipt_age)


class LatestSource:
    def __init__(self, *, wall=time.time, monotonic=time.monotonic):
        self.wall, self.monotonic = wall, monotonic
        self._lock, self._sample = threading.Lock(), None

    def put(self, stamp, value):
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp <= 0:
            raise ValueError('invalid source stamp')
        with self._lock:
            candidate = Sample(stamp, self.monotonic(), self._sample.sequence + 1 if self._sample else 1, value)
            sample_age(candidate, self.wall(), self.monotonic())
            if self._sample and stamp <= self._sample.captured_at:
                return False
            self._sample = Sample(stamp, candidate.received_at, candidate.sequence, deepcopy(value))
            return True

    def latest(self):
        with self._lock:
            if self._sample is None:
                return None
            try:
                sample_age(self._sample, self.wall(), self.monotonic())
            except ValueError:
                return None
            return deepcopy(self._sample)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ArmHealthSource:
    """One latest-value stream; terminal files can advance without inventing ROS positions."""
    def __init__(self, source, path, owner):
        self.source, self.path, self.owner = source, path, owner
        self.last, self.position_sequence, self.terminal_key = None, None, None

    def latest(self):
        position = self.source.latest()
        wall, mono = self.source.wall(), self.source.monotonic()
        health, captured = None, None
        try:
            health, captured = read_motor_health_snapshot(self.path, self.owner, now=wall)
        except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
            pass  # Position delivery remains independent; absence is never healthy telemetry.
        terminal = health is not None and health.status in ('fault', 'ended')
        key = (health.session_id, health.status, captured) if terminal else None
        sequence = self.last.sequence + 1 if self.last else 1
        if terminal and key != self.terminal_key and (self.last is None or captured > self.last.captured_at):
            candidate = Sample(captured, mono, sequence, None, health)
            try:
                sample_age(candidate, wall, mono)
            except ValueError:
                candidate = None
            if candidate is not None:
                self.last, self.terminal_key = candidate, key
        elif (position is not None and position.sequence != self.position_sequence
              and (self.last is None or position.captured_at > self.last.captured_at)):
            self.last = Sample(position.captured_at, position.received_at, sequence, position.value, health)
            self.position_sequence = position.sequence
        if self.last is None:
            return None
        try:
            sample_age(self.last, wall, mono)
        except ValueError:
            return None
        return self.last


def post_arm(fleet_url, source_id, token, observation, *, context):
    url = secure_url(fleet_url, 'https') + '/api/fleet/workcell-observations/arms/' + quote(source_id, safe='')
    request = Request(url, data=observation.model_dump_json().encode(), method='POST',
                      headers={'Content-Type': 'application/json', 'X-Workcell-Observation-Token': token})
    opener = build_opener(HTTPSHandler(context=_verified(context)), _NoRedirect())
    with opener.open(request, timeout=2) as response:
        if response.status != 202:
            raise OSError('observation was not accepted')


class ArmSender:
    def __init__(self, fleet_url, source_id, token, *, context):
        self.url, self.source_id, self.token = secure_url(fleet_url, 'https'), source_id, token
        self.context = _verified(context)
        self.epoch, self.sequence, self.conflict_stamp = uuid4().hex, 0, None

    def send(self, sample):
        if self.conflict_stamp is not None:
            if sample.captured_at <= self.conflict_stamp:
                raise ValueError('conflict recovery requires a newer capture')
            # A lost 202 may leave the server ahead; a fresh epoch still requires capture advance.
            self.epoch, self.sequence, self.conflict_stamp = uuid4().hex, 0, None
        observation = ArmObservation(epoch=self.epoch, sequence=self.sequence + 1,
                                     captured_at=sample.captured_at, positions=sample.value,
                                     motor_health=sample.motor_health)
        try:
            post_arm(self.url, self.source_id, self.token, observation, context=self.context)
        except HTTPError as error:
            if error.code == 409:
                self.conflict_stamp = sample.captured_at
            raise
        self.sequence += 1


def camera_hello(source_id, width, height):
    message = {'type': 'hello', 'proto': protocol.PROTO, 'source': source_id,
               'sensor': {'width': width, 'height': height, 'rotation_deg': 0}}
    protocol.validate_hello(message)
    return message


def camera_packet(sample, *, wall=None, monotonic=None):
    age = sample_age(sample, time.time() if wall is None else wall,
                     time.monotonic() if monotonic is None else monotonic)
    jpeg, width, height = sample.value
    if not isinstance(jpeg, bytes) or not jpeg or len(jpeg) > protocol.DEFAULT_CONFIG['max_bytes']:
        raise ValueError('invalid or oversized camera JPEG')
    return protocol.pack_header(protocol.FrameHeader(sample.sequence, math.ceil(age * 1000), width, height, 0)) + jpeg


class CameraSender:
    def __init__(self, vision_url, source_id, token, *, context):
        self.url = secure_url(vision_url, 'wss')
        if urlsplit(self.url).path in ('', '/'):
            self.url += protocol.WS_PATH
        self.source_id, self.token, self.context = source_id, token, _verified(context)
        self.connection = None

    def close(self):
        if self.connection is not None:
            connection, self.connection = self.connection, None
            try:
                connection.close()
            except Exception:
                pass

    def send(self, sample):
        from websockets.sync.client import connect
        try:
            if self.connection is None:
                self.connection = connect(self.url, ssl=self.context,
                    additional_headers={'Authorization': f'Bearer {self.token}'},
                    open_timeout=2, close_timeout=1, max_queue=1, max_size=65536)
                self.connection.socket.settimeout(2)
                self.connection.send(json.dumps(camera_hello(self.source_id, sample.value[1], sample.value[2])))
            # Drain config/status/demand messages so their receive queue cannot stall the socket.
            for _ in range(8):
                try:
                    self.connection.recv(timeout=0)
                except TimeoutError:
                    break
            self.connection.send(camera_packet(sample))
        except Exception:
            self.close()
            raise


class SourceWorker:
    def __init__(self, source, send):
        self.source, self.send = source, send

    def run(self, stop):
        last, backoff = 0, 0.1
        while not stop.is_set():
            sample = self.source.latest()
            if sample is None or sample.sequence == last:
                stop.wait(0.05)
                continue
            try:
                self.send(sample)
                last, backoff = sample.sequence, 0.1
            except Exception as error:
                logging.getLogger(__name__).warning('observation delivery failed source=%s error=%s',
                    threading.current_thread().name, type(error).__name__)
                if stop.wait(backoff):
                    return
                backoff = min(5, backoff * 2)


def source_stamp(message):
    sec, nanosec = message.header.stamp.sec, message.header.stamp.nanosec
    if type(sec) is not int or type(nanosec) is not int or sec < 0 or not 0 <= nanosec < 1_000_000_000:
        raise ValueError('invalid ROS source stamp')
    return sec + nanosec / 1e9


def joint_values(message, joint_names):
    if (len(message.name) != len(message.position) or len(set(message.name)) != len(message.name)
            or set(message.name) != set(joint_names)):
        raise ValueError('joint observation must exactly match its registered arm')
    return ArmObservation(epoch='0' * 32, sequence=1, captured_at=source_stamp(message),
                          positions=dict(zip(message.name, message.position))).positions


def encode_image(message, cv, np):
    if (message.encoding not in ('bgr8', 'rgb8') or message.width != 640 or message.height != 480
            or not 1920 <= message.step <= 4096 or len(message.data) != message.step * message.height):
        raise ValueError('unsupported camera image layout')
    pixels = np.frombuffer(message.data, np.uint8).reshape(message.height, message.step)
    pixels = pixels[:, :message.width * 3].reshape(message.height, message.width, 3)
    if message.encoding == 'rgb8':
        pixels = cv.cvtColor(pixels, cv.COLOR_RGB2BGR)
    ok, encoded = cv.imencode('.jpg', pixels, [cv.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise ValueError('camera JPEG encoding failed')
    return encoded.tobytes(), message.width, message.height


def main(argv=None):
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--workcell', required=True)
    parser.add_argument('--fleet-url', required=True)
    parser.add_argument('--vision-url', required=True)
    parser.add_argument('--domain-id', type=int, required=True)
    parser.add_argument('--ca-file', type=Path)
    parser.add_argument('--arm-health-file', action='append', metavar='SOURCE_ID=/absolute/file',
                        default=os.environ.get('ROSY_OBSERVATION_ARM_HEALTH', '').split(),
                        help='private trusted health file for a registered arm; owner derives from its arm_id '
                             '(default: the space-separated ROSY_OBSERVATION_ARM_HEALTH, one per arm of this cell)')
    args = parser.parse_args(argv)
    if not 0 <= args.domain_id <= 232:
        parser.error('domain-id must be 0..232')
    for key in ('CYCLONEDDS_URI', 'FASTDDS_DEFAULT_PROFILES_FILE',
                'FASTRTPS_DEFAULT_PROFILES_FILE', 'ROS_DISCOVERY_SERVER'):
        if os.environ.get(key):
            parser.error(f'external discovery override is not allowed: {key}')
    if os.environ.get('RMW_IMPLEMENTATION', 'rmw_fastrtps_cpp') != 'rmw_fastrtps_cpp':
        parser.error('observation bridge requires rmw_fastrtps_cpp')
    try:
        manifest = WorkcellObservationManifest.model_validate(yaml.safe_load(args.manifest.read_text(encoding='utf-8')))
        cell, tokens = select_sources(manifest, args.workcell, os.environ)
        health_files = {}
        for binding in args.arm_health_file:
            source, separator, file = binding.partition('=')
            path = Path(file)
            if (not separator or source not in {arm.source_id for arm in cell.arms} or source in health_files
                    or not path.is_absolute() or path.resolve() != path or path.is_symlink()):
                raise ValueError('health file must be bound once to a registered source and canonical path')
            health_files[source] = path
        secure_url(args.fleet_url, 'https'); secure_url(args.vision_url, 'wss')
        context = ssl.create_default_context(cafile=args.ca_file)
    except (OSError, ValueError, yaml.YAMLError) as error:
        parser.error(f'observation configuration invalid: {type(error).__name__}')
    os.environ['RMW_IMPLEMENTATION'] = 'rmw_fastrtps_cpp'
    os.environ['ROS_STATIC_PEERS'] = ''
    os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE'] = 'LOCALHOST'
    import cv2
    import numpy as np
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image, JointState
    rclpy.init(args=[], domain_id=args.domain_id)
    node = rclpy.create_node('rosy_workcell_observation_' + uuid4().hex[:12])
    stop, workers, senders = threading.Event(), [], []

    def subscribe(source, message_type, topic, convert, sender, *, health_file=None):
        buffer = LatestSource()
        def receive(message):
            try:
                buffer.put(source_stamp(message), convert(message))
            except (ValueError, TypeError, OverflowError, cv2.error):
                node.get_logger().warning(f'ignored invalid observation from {source.source_id}')
        node.create_subscription(message_type, topic, receive, qos_profile_sensor_data)
        delivery = ArmHealthSource(buffer, health_file, source.arm_id) if health_file is not None else buffer
        worker = threading.Thread(target=SourceWorker(delivery, sender.send).run, args=(stop,),
                                  name=source.source_id, daemon=True)
        worker.start(); workers.append(worker); senders.append(sender)

    try:
        for arm in cell.arms:
            subscribe(arm, JointState, arm.joint_topic, lambda msg, names=arm.joint_names: joint_values(msg, names),
                      ArmSender(args.fleet_url, arm.source_id, tokens[arm.source_id], context=context),
                      health_file=health_files.get(arm.source_id))
        for camera in cell.cameras:
            subscribe(camera, Image, camera.image_topic, lambda msg: encode_image(msg, cv2, np),
                      CameraSender(args.vision_url, camera.source_id, tokens[camera.source_id], context=context))
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        stop.set()
        for sender in senders:
            if isinstance(sender, CameraSender):
                sender.close()
        for worker in workers:
            worker.join(timeout=3)
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
