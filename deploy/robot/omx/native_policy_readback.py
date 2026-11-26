"""Fresh, read-only commissioning evidence from the handed-off B follower serial port."""
import os
from pathlib import Path
import threading
import time

from joint_tune_lock import FOLLOWER_5DOF, HELD_ENV, lock_root
from register_probe import read_motors

MAX_AGE_NS = 2_000_000_000


def check_handoff(device):
    """Only the B observer's inherited cell and exclusive arm locks admit an observation session."""
    path = Path(device)
    if path.parent != Path("/dev/serial/by-id") or not path.is_symlink():
        raise ValueError("installed B device must be a by-id link")
    if (os.environ.get("ROSY_HANDOFF_ARM") != "arm_b"
            or str(path.resolve(strict=True)) != os.environ.get("ROSY_HANDOFF_DEVICE")):
        raise PermissionError("active B observer/device handoff required")
    check_inherited_locks()


def check_inherited_locks():
    held = os.environ.get(HELD_ENV, "").split(":")
    if len(held) != 3 or held[0] != "arm_b":
        raise PermissionError("inherited B observer locks required")
    for number, name, mode in zip(held[1:], ("session.lock", "session-arm_b.lock"), ("READ", "WRITE")):
        fd = int(number)
        proc = Path(f"/proc/self/fd/{fd}")
        info = Path(f"/proc/self/fdinfo/{fd}").read_text()
        if (not os.path.samestat(proc.stat(), (lock_root() / name).stat())
                or not any(line.startswith("lock:") and "FLOCK" in line.split() and mode in line.split()
                           for line in info.splitlines())):
            raise PermissionError("B observer handoff lock identity or ownership differs")


def motor_rows(samples):
    if not isinstance(samples, list) or len(samples) != 6:
        raise ValueError("six follower register rows required")
    rows = []
    for motor, sample in zip(FOLLOWER_5DOF, samples):
        keys = ("id", "model_number", "position_raw", "torque_enabled", "hardware_error")
        if not isinstance(sample, dict) or any(type(sample.get(k)) is not int for k in keys):
            raise ValueError("incomplete motor register sample")
        if (sample["id"] != motor or sample["model_number"] != FOLLOWER_5DOF[motor][0]
                or sample["torque_enabled"] not in (0, 1) or not 0 <= sample["hardware_error"] <= 255
                or not -(2**31) <= sample["position_raw"] < 2**31):
            raise ValueError("unexpected B follower model, motor id or register value")
        rows.append({key: sample[key] for key in keys})
    return rows


class RegisterReadback:
    def __init__(self, port, *, clock=time.monotonic_ns, wall=time.time_ns):
        self._port, self._clock, self._wall = port, clock, wall
        self._sample = None
        self._state = "unavailable"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="native-b-register-readback", daemon=True)

    def collect(self):
        begin = self._clock()
        try:
            motors = motor_rows(read_motors(self._port, allow_fault=True))
            end = self._clock()
            wall = self._wall()
            fresh = 0 <= end - begin <= MAX_AGE_NS
            with self._lock:
                self._state = "fresh" if fresh else "stale"
                self._sample = {"observed_at_unix_ns": wall, "observed_at_monotonic_ns": begin,
                                "motors": motors} if fresh else None
        except Exception:
            with self._lock:
                self._sample, self._state = None, "unavailable"

    def _run(self):
        while not self._stop.is_set():
            self.collect()
            self._stop.wait(.4)

    def snapshot(self):
        with self._lock:
            sample, state = self._sample, self._state
            if sample is not None and not 0 <= self._clock() - sample["observed_at_monotonic_ns"] <= MAX_AGE_NS:
                sample, state = None, "stale"
            return {"arm_id": "arm_b", "basis": "readonly_motor_registers", "state": state, **(sample or {})}

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join()  # no concurrent port close; handoff waits for this process before restarting observer
