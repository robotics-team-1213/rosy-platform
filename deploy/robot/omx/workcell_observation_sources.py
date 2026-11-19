"""Local Observation Sample Buffers & ROS Message Decoders (`workcell_observation_sources.py`).

Single Responsibility:
  - Validate observation manifest credentials (`select_sources`).
  - Retain newest advancing sample (`Sample`, `sample_age`, `LatestSource`, `NativeSource`, `ArmHealthSource`).
  - Decode ROS source stamps, arm joint values, and BGR/RGB camera images (`source_stamp`, `joint_values`, `encode_image`).
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import math
import threading
import time

from core_common.motor_health import read_motor_health_snapshot as _default_read_motor_health_snapshot
from core_common.observation_snapshot import SnapshotChannel
from core_common.protocol.motor_health import MotorHealthResponse
from core_common.protocol.workcell_observations import ArmObservation


_WOB_GLOBALS_LIST: list[dict] = []


def _REGISTER_WOB_GLOBALS(g: dict) -> None:
    if g not in _WOB_GLOBALS_LIST:
        _WOB_GLOBALS_LIST.append(g)


def _read_health(path, owner, *, now):
    import sys

    for g in _WOB_GLOBALS_LIST:
        fn = g.get("read_motor_health_snapshot")
        if fn is not None and fn is not _default_read_motor_health_snapshot:
            return fn(path, owner, now=now)
    mod = sys.modules.get("workcell_observation_bridge")
    fn = getattr(mod, "read_motor_health_snapshot", _default_read_motor_health_snapshot)
    return fn(path, owner, now=now)



def select_sources(manifest, workcell_id, environ):
    cell = next((cell for cell in manifest.workcells if cell.workcell_id == workcell_id), None)
    if cell is None:
        raise ValueError("unknown observation workcell")
    tokens = {}
    for source in [*cell.arms, *cell.cameras]:
        token = environ.get(source.token_env)
        if (
            not isinstance(token, str)
            or not token
            or not hmac.compare_digest(sha256(token.encode()).hexdigest(), source.credential_sha256)
        ):
            raise ValueError("source credential missing or fingerprint mismatch")
        tokens[source.source_id] = token
    return cell, tokens


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
        raise ValueError("observation capture or receipt is stale or future")
    return max(0, source_age, receipt_age)


def _copy_value(value):
    if isinstance(value, (bytes, str, int, float, type(None))):
        return value
    if isinstance(value, tuple) and all(isinstance(x, (bytes, str, int, float, type(None))) for x in value):
        return value
    if isinstance(value, dict) and all(isinstance(v, (int, float, str, bool, type(None))) for v in value.values()):
        return dict(value)
    return deepcopy(value)


class LatestSource:
    def __init__(self, *, wall=time.time, monotonic=time.monotonic):
        self.wall, self.monotonic = wall, monotonic
        self._lock, self._sample = threading.Lock(), None

    def put(self, stamp, value, *, received=None):
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp <= 0:
            raise ValueError("invalid source stamp")
        with self._lock:
            candidate = Sample(
                stamp,
                self.monotonic() if received is None else received,
                self._sample.sequence + 1 if self._sample else 1,
                value,
            )
            sample_age(candidate, self.wall(), self.monotonic())
            if self._sample and stamp <= self._sample.captured_at:
                return False
            self._sample = Sample(stamp, candidate.received_at, candidate.sequence, _copy_value(value))
            return True

    def latest(self):
        with self._lock:
            if self._sample is None:
                return None
            try:
                sample_age(self._sample, self.wall(), self.monotonic())
            except ValueError:
                return None
            s = self._sample
            return Sample(
                s.captured_at,
                s.received_at,
                s.sequence,
                _copy_value(s.value),
                deepcopy(s.motor_health) if s.motor_health is not None else None,
            )


class NativeSource(LatestSource):
    def __init__(self, channel, *, joint_names=None):
        super().__init__()
        self.channel, self.joint_names = SnapshotChannel(channel), joint_names
        self._joint_name_set = set(joint_names) if joint_names is not None else None

    def latest(self):
        sample = self.channel.read()
        if sample is not None:
            try:
                if self.joint_names is None:
                    if sample["kind"] != "jpeg":
                        raise ValueError("camera channel must carry JPEG")
                    value = (sample["payload"], 640, 480)
                else:
                    if sample["kind"] != "joints":
                        raise ValueError("arm channel must carry joint positions")
                    value = json.loads(sample["payload"])
                    if not isinstance(value, dict) or set(value) != self._joint_name_set:
                        raise ValueError("joint observation must match registered arm")
                    value = ArmObservation(
                        epoch="0" * 32, sequence=1, captured_at=sample["captured_at"], positions=value
                    ).positions
                self.put(sample["captured_at"], value, received=sample["monotonic"])
            except (ValueError, TypeError):
                pass
        return super().latest()


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
            health, captured = _read_health(self.path, self.owner, now=wall)
        except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
            pass
        terminal = health is not None and health.status in ("fault", "ended")
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
        elif (
            position is not None
            and position.sequence != self.position_sequence
            and (self.last is None or position.captured_at > self.last.captured_at)
        ):
            self.last = Sample(position.captured_at, position.received_at, sequence, position.value, health)
            self.position_sequence = position.sequence
        if self.last is None:
            return None
        try:
            sample_age(self.last, wall, mono)
        except ValueError:
            return None
        return self.last


def source_stamp(message):
    sec, nanosec = message.header.stamp.sec, message.header.stamp.nanosec
    if type(sec) is not int or type(nanosec) is not int or sec < 0 or not 0 <= nanosec < 1_000_000_000:
        raise ValueError("invalid ROS source stamp")
    return sec + nanosec / 1e9


def joint_values(message, joint_names):
    if (
        len(message.name) != len(message.position)
        or len(set(message.name)) != len(message.name)
        or set(message.name) != set(joint_names)
    ):
        raise ValueError("joint observation must exactly match its registered arm")
    return ArmObservation(
        epoch="0" * 32,
        sequence=1,
        captured_at=source_stamp(message),
        positions=dict(zip(message.name, message.position)),
    ).positions


def encode_image(message, cv, np):
    if (
        message.encoding not in ("bgr8", "rgb8")
        or message.width != 640
        or message.height != 480
        or not 1920 <= message.step <= 4096
        or len(message.data) != message.step * message.height
    ):
        raise ValueError("unsupported camera image layout")
    pixels = np.frombuffer(message.data, np.uint8).reshape(message.height, message.step)
    pixels = pixels[:, : message.width * 3].reshape(message.height, message.width, 3)
    if message.encoding == "rgb8":
        pixels = cv.cvtColor(pixels, cv.COLOR_RGB2BGR)
    ok, encoded = cv.imencode(".jpg", pixels, [cv.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise ValueError("camera JPEG encoding failed")
    return encoded.tobytes(), message.width, message.height
