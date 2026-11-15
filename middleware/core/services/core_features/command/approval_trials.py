"""D-986: records one G4 approval trial while a person holds the drive.

The drive goes through the caller's normal teleop path only while holds keep arriving, so this
adds no way to move the robot. The raw file has exactly the fields mapping_approval.py verifies;
the verdict stays there. A trial that cannot finish leaves no file.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import tempfile
import threading
import time

from core_common.robot_body import inside_body
from core_features.line_follow.clearance import body_clearances, rotation_sweep_gap, scan_points

# The measured speed must stay under mapping_approval's 0.03/0.10 too, so the request stays below it.
TRIAL_LINEAR_MPS = 0.02
TRIAL_ANGULAR_RPS = 0.07
# Slowest request that still shows as motion above mapping_approval's measured floors (0.002, 0.03).
MIN_LINEAR_MPS = 0.01
MIN_ANGULAR_RPS = 0.05
TRAVEL_CAP_M = 0.06  # stops well inside the 10 cm limit, which also has to hold the stop's own travel
MAX_HOLD_S = 3.0
HOLD_START_S = 5.0
HOLD_GAP_S = 0.4  # a button hold that goes quiet aborts: only a commanded stop proves a button release
LOSS_GAP_S = 0.25  # a loss trial sees its stream gone, then only watches the teleop watchdog stop the robot
SETTLE_S = 1.2
ODOM_MAX_AGE_S = 0.3
SCAN_MAX_AGE_S = 0.5
SOURCE_MAX_AGE_S = 0.25
RUN_MARGIN_M = 0.05
TURN_MARGIN_M = 0.03
TURN_SWEEP_M = 0.05  # a trial turns well under 0.02 m of arc; the side it turns into must be free this far
MIN_SECTOR_RETURNS = 0.5
# Of all the sector's beams, however many end on the body. Recorded C1 scans never fall below 0.44.
MIN_SEEING_BEAMS = 0.25
PAIRS = {("forward", "button_release"), ("reverse", "button_release"), ("cw", "button_release"),
         ("ccw", "button_release"), ("forward", "command_loss")}
COMMANDS = {"forward": (1, 0), "reverse": (-1, 0), "cw": (0, -1), "ccw": (0, 1)}


# Floor trials: spinning wheels move odometry but not the scan (b8xy, 2026-11-07: odom -3.11 m, clearances unchanged).
# Per-beam noise is 0.6-3.4 mm standing still (D-573). The sector median's spread on real moving C1 scans is about
# 3 mm (1.25 * 0.020 m / sqrt(72)), so the 10 mm tolerance leaves about three times the noise.
MIN_LINEAR_CHECK_M = 0.02
LINEAR_TOLERANCE_M = 0.01
LINEAR_SECTOR_RAD = math.radians(20)
SCAN_RANGE_CAP_M = 4.0
BEAM_JUMP_M = 0.2  # a beam that jumps this far changed target: no use as a distance difference
MIN_PAIRED_BEAMS = 20
# Shifting a real scan onto itself lands exactly; real neighbouring scans differ by up to 2 beams (0.0175 rad).
MIN_TURN_CHECK_RAD = 0.06
TURN_TOLERANCE_RAD = 0.035
TURN_SEARCH_BEAMS = 60
MIN_TURN_BEAMS = 100
RELATIVE_TOLERANCE = 0.5
SURFACE_SUFFIX = ".surface.json"


class TrialRefused(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _sector_seen(sample, config, points, centre_rad: float, half_rad: float) -> bool:
    """Enough of this sector's beams that could see outside did see outside. A beam ending on the
    robot itself says nothing about the room, so it does not count either way."""
    ranges = sample["ranges"]
    low = float(sample["range_min"])
    start = float(sample["angle_min"])
    step = (float(sample["angle_max"]) - start) / (len(ranges) - 1)
    forward = math.radians(float(config.lidar_forward_deg))
    beams = looking = 0
    for index, value in enumerate(ranges):
        angle = start + index * step - forward
        if abs(math.atan2(math.sin(angle - centre_rad), math.cos(angle - centre_rad))) > half_rad:
            continue
        beams += 1
        distance = float(value)
        # 0, inf and NaN are no return at all (robot_body): they stay unknown, never the robot.
        own = math.isfinite(distance) and distance > 0.0 and (distance < low or inside_body(
            distance * math.cos(angle) + config.body_lidar_x_m, distance * math.sin(angle), config.body_front_x_m,
            config.body_rear_x_m, config.body_half_width_m, config.body_rotation_radius_m, strict=True))
        looking += not own
    outside = sum(abs(math.atan2(math.sin(math.atan2(y, x) - centre_rad), math.cos(math.atan2(y, x) - centre_rad))) <= half_rad
                  for x, y in points)
    return outside >= MIN_SEEING_BEAMS * beams and outside >= MIN_SECTOR_RETURNS * looking


def _scan_outside(sample, config) -> list:
    """(robot-frame angle, distance) per beam, None where the beam sees no return or the robot itself."""
    start = float(sample["angle_min"])
    ranges = sample["ranges"]
    step = (float(sample["angle_max"]) - start) / (len(ranges) - 1)
    forward = math.radians(float(config.lidar_forward_deg))
    low = float(sample["range_min"])
    beams = []
    for index, value in enumerate(ranges):
        angle = start + index * step - forward
        angle = math.atan2(math.sin(angle), math.cos(angle))
        distance = float(value)
        beams.append((angle, distance) if math.isfinite(distance) and distance >= low and not inside_body(
            distance * math.cos(angle) + config.body_lidar_x_m, distance * math.sin(angle), config.body_front_x_m,
            config.body_rear_x_m, config.body_half_width_m, config.body_rotation_radius_m, strict=True) else None)
    return beams


def _scan_travel_m(first, last) -> float:
    """Signed travel along the body axis: what lies ahead comes closer, what lies behind goes away."""
    changes = []
    for before, after in zip(first, last):
        if before is None or after is None or max(before[1], after[1]) > SCAN_RANGE_CAP_M \
                or abs(before[1] - after[1]) > BEAM_JUMP_M:
            continue
        if abs(before[0]) <= LINEAR_SECTOR_RAD:
            changes.append(before[1] - after[1])
        elif math.pi - abs(before[0]) <= LINEAR_SECTOR_RAD:
            changes.append(after[1] - before[1])
    if len(changes) < MIN_PAIRED_BEAMS:
        raise TrialRefused("SCAN_UNUSABLE", "too few LiDAR beams ahead or behind to check the travel")
    return statistics.median(changes)


def _scan_turn_rad(first, last, step: float) -> float:
    """Signed turn: the shift that best lays the second scan over the first. Scene turning left moves beams right."""
    count = len(first)
    best = None
    for shift in sorted(range(-TURN_SEARCH_BEAMS, TURN_SEARCH_BEAMS + 1), key=abs):
        differences = [abs(before[1] - after[1]) for before, after in
                       ((first[index], last[(index + shift) % count]) for index in range(count))
                       if before is not None and after is not None]
        if len(differences) < MIN_TURN_BEAMS:
            continue
        score = statistics.median(differences)
        if best is None or score < best[0]:
            best = (score, shift)
    if best is None:
        raise TrialRefused("SCAN_UNUSABLE", "too few LiDAR beams to check the turn")
    return -best[1] * step


def check_floor_motion(start, end, config, direction: str, odom: float) -> dict:
    """Raises unless the room moved as odometry says. odom: signed metres along the axis, or radians for a turn."""
    linear = direction in ("forward", "reverse")
    if abs(odom) < (MIN_LINEAR_CHECK_M if linear else MIN_TURN_CHECK_RAD):
        raise TrialRefused("TRIAL_TOO_SHORT", "hold the button longer: too little motion to check against the LiDAR")
    try:
        if len(start["ranges"]) != len(end["ranges"]) or start["angle_min"] != end["angle_min"]:
            raise TrialRefused("SCAN_UNUSABLE", "the two LiDAR scans do not line up")
        first, last = _scan_outside(start, config), _scan_outside(end, config)
        step = (float(end["angle_max"]) - float(end["angle_min"])) / (len(end["ranges"]) - 1)
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
        raise TrialRefused("SCAN_UNUSABLE", f"the LiDAR scan is unreadable: {exc}") from exc
    seen = _scan_travel_m(first, last) if linear else _scan_turn_rad(first, last, step)
    tolerance = max(LINEAR_TOLERANCE_M if linear else TURN_TOLERANCE_RAD, RELATIVE_TOLERANCE * abs(odom))
    if abs(seen - odom) > tolerance:
        raise TrialRefused("WHEELS_NOT_MOVING_BODY",
                           f"odometry says {odom:+.3f} but the LiDAR saw {seen:+.3f}: the wheels may be slipping")
    return {"odom": round(odom, 4), "scan": round(seen, 4), "tolerance": round(tolerance, 4),
            "unit": "m" if linear else "rad"}


def _scan_is_current(sample, wall_now: float) -> bool:
    try:
        return (0 <= wall_now - sample["received_at"] <= SCAN_MAX_AGE_S
                and abs(sample["source_now_ns"] - sample["source_stamp_ns"]) / 1e9 <= SOURCE_MAX_AGE_S)
    except (KeyError, TypeError):
        return False


def require_clearance(sample, config, direction: str, wall_now: float) -> dict:
    """Raises unless a fresh full scan shows room where the trial moves. No or stale data never reads as free space.

    User 2026-11-09 (D-1008): only the heading is judged. Forward looks ahead, reverse behind, a turn at the side the
    body swings into; what lies elsewhere never refuses, and no person is asked to vouch for the rear."""
    if not sample:
        raise TrialRefused("CLEARANCE_UNKNOWN", "no LiDAR scan has arrived")
    try:
        received, stamp, source_now = sample["received_at"], sample["source_stamp_ns"], sample["source_now_ns"]
        count = len(sample["ranges"])
        span = float(sample["angle_max"]) - float(sample["angle_min"])
        range_min = float(sample["range_min"])
        if wall_now - received > SCAN_MAX_AGE_S or wall_now < received or abs(source_now - stamp) / 1e9 > SOURCE_MAX_AGE_S:
            raise TrialRefused("CLEARANCE_UNKNOWN", "the LiDAR scan is stale")
        if count < 180 or span < 6.0:
            raise TrialRefused("CLEARANCE_UNKNOWN", "the LiDAR scan does not cover the whole circle")
        if not config.body_stop_known:
            raise TrialRefused("CLEARANCE_UNKNOWN", "the robot body outline is not configured")
        points = [(x, y) for x, y in scan_points(sample, forward_deg=config.lidar_forward_deg,
                                                 self_mask=config.lidar_self_mask)
                  if not inside_body(x + config.body_lidar_x_m, y, config.body_front_x_m, config.body_rear_x_m,
                                     config.body_half_width_m, config.body_rotation_radius_m, strict=True)]
        # Under range_min the driver reports the robot itself (real C1 scans: 0.033-0.049 m). That reading
        # holds only while the whole range_min circle lies inside the body: an outside object then meets
        # the body first and reads farther away.
        ahead, behind = config.body_front_x_m - config.body_lidar_x_m, config.body_lidar_x_m - config.body_rear_x_m
        blind_reach = {"forward": ahead, "reverse": behind}.get(direction, min(ahead, behind, config.body_half_width_m))
        if range_min > blind_reach:
            raise TrialRefused("CLEARANCE_UNKNOWN", "the LiDAR's minimum range reaches outside the body")
        centre, half = {"forward": (0.0, math.pi / 4), "reverse": (math.pi, math.pi / 4)}.get(direction, (0.0, math.pi))
        if not _sector_seen(sample, config, points, centre, half):
            raise TrialRefused("CLEARANCE_UNKNOWN", f"too few LiDAR returns for a {direction} trial")
    except TrialRefused:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise TrialRefused("CLEARANCE_UNKNOWN", f"the LiDAR scan is unreadable: {exc}") from exc
    seen = body_clearances(points, lidar_x_m=config.body_lidar_x_m, rear_x_m=config.body_rear_x_m,
                           half_width_m=config.body_half_width_m,
                           rotation_radius_m=config.body_rotation_radius_m)
    need = TRAVEL_CAP_M + RUN_MARGIN_M
    if direction == "reverse":
        if seen["rear_m"] is not None and seen["rear_m"] < need:
            raise TrialRefused("CLEARANCE_TOO_SMALL", f"{seen['rear_m']:.2f} m behind the body, {need:.2f} m needed")
        return seen
    if direction == "forward":
        front = seen["front_band_m"]
        free = None if front is None else front - (config.body_front_x_m - config.body_lidar_x_m)
        if free is not None and free < need:
            raise TrialRefused("CLEARANCE_TOO_SMALL", f"{free:.2f} m ahead of the body, {need:.2f} m needed")
        return seen
    swing = rotation_sweep_gap([(x + config.body_lidar_x_m, y) for x, y in points], sign=COMMANDS[direction][1],
                               front_x_m=config.body_front_x_m, rear_x_m=config.body_rear_x_m,
                               half_width_m=config.body_half_width_m, rotation_radius_m=config.body_rotation_radius_m,
                               horizon_m=TURN_SWEEP_M, pad_m=TURN_MARGIN_M)
    if swing is not None:
        raise TrialRefused("CLEARANCE_TOO_SMALL",
                           f"something lies {swing:.2f} m of turning ahead, {TURN_SWEEP_M:.2f} m needed free")
    return seen


class ApprovalTrials:
    def __init__(self, state, command, safety, line_config, directory: Path, *,
                 clock=time.monotonic, wall=time.time, thread: bool = True) -> None:
        self.state, self.command, self.safety = state, command, safety
        self.line_config, self.directory = line_config, Path(directory)
        self.clock, self.wall, self.thread = clock, wall, thread
        self._lock = threading.Lock()
        self._trial: dict | None = None
        self.last: dict | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._trial is not None

    def status(self) -> dict:
        with self._lock:
            trial = self._trial
            current = None if trial is None else {
                "direction": trial["direction"], "stop_cause": trial["stop_cause"],
                "stopping": trial["stop_at"] is not None}
            return {"active": current, "last": self.last}

    def start(self, direction: str, stop_cause: str, owner: str, *, test_surface: str) -> dict:
        if (direction, stop_cause) not in PAIRS:
            raise TrialRefused("TRIAL_UNKNOWN", f"{direction}/{stop_cause} is not a required trial")
        limits = self.safety.limits
        # A lower live limit would clip the command, and the evidence must say what was really sent.
        linear = min(TRIAL_LINEAR_MPS, limits.manual_linear)
        angular = min(TRIAL_ANGULAR_RPS, limits.manual_angular)
        if linear < MIN_LINEAR_MPS or angular < MIN_ANGULAR_RPS:
            raise TrialRefused("TRIAL_LIMIT_TOO_LOW", "the manual speed limit leaves no measurable motion")
        scan = self.state.get_sensor("lidar")
        seen = require_clearance(scan, self.line_config(), direction, self.wall())
        odom = self.state.odom_sample()
        if odom is None or odom[3] > ODOM_MAX_AGE_S:
            raise TrialRefused("ODOM_STALE", "odometry is not fresh")
        sign_linear, sign_angular = COMMANDS[direction]
        now = self.clock()
        with self._lock:
            if self._trial is not None:
                raise TrialRefused("TRIAL_ACTIVE", "another trial is running")
            self._trial = {"direction": direction, "stop_cause": stop_cause, "owner": owner, "started_at": now,
                           "test_surface": test_surface, "start_scan": scan,
                           "linear": sign_linear * linear, "angular": sign_angular * angular, "first_hold": None,
                           "last_hold": None, "stop_at": None, "samples": [], "travel": 0.0, "last_odom_at": now}
            self.last = None
        if self.thread:
            threading.Thread(target=self._run, name="approval-trial", daemon=True).start()
        return seen

    def hold(self, owner: str, send) -> None:
        """Under the lock, so an abort can never be followed by one more drive command."""
        with self._lock:
            trial = self._trial
            if trial is None or trial["stop_at"] is not None:
                raise TrialRefused("TRIAL_NOT_HOLDING", "no trial is waiting for a hold")
            if trial["owner"] != owner:
                raise TrialRefused("TRIAL_OWNER", "another operator started this trial")
            send(trial["linear"], trial["angular"])
            now = self.clock()
            trial["first_hold"] = trial["first_hold"] or now
            trial["last_hold"] = now

    def stop(self, owner: str) -> None:
        """The button release: its request time is the moment the zero command goes out."""
        with self._lock:
            trial = self._trial
            if trial is None or trial["stop_at"] is not None:
                return
            if trial["owner"] != owner:
                raise TrialRefused("TRIAL_OWNER", "another operator started this trial")
            if trial["stop_cause"] != "button_release" or trial["first_hold"] is None:
                self._abort(trial, "stopped before the trial could be measured")
                return
            trial["stop_at"] = self.clock()
            self._zero()

    def abort(self, reason: str) -> None:
        with self._lock:
            if self._trial is not None:
                self._abort(self._trial, reason)

    def _zero(self) -> None:
        self.command.teleop(0.0, 0.0, source="manual")

    def _abort(self, trial, reason) -> None:
        self._trial = None
        self._zero()
        self.last = {"direction": trial["direction"], "stop_cause": trial["stop_cause"],
                     "state": "aborted", "reason": reason}

    def _run(self) -> None:
        while self.tick():
            time.sleep(0.01)

    def _sample(self, trial, now) -> None:
        odom = self.state.odom_sample()
        if odom is None:
            return
        x, y, yaw, age = odom
        at = now - age
        samples = trial["samples"]
        if samples and at <= samples[-1]["t"]:
            return
        velocity = self.state.snapshot().velocity
        if samples:
            trial["travel"] += math.hypot(x - samples[-1]["x"], y - samples[-1]["y"])
        samples.append({"t": at, "linear": float(velocity.linear), "angular": float(velocity.angular),
                        "x": x, "y": y, "yaw": yaw})
        trial["last_odom_at"] = now

    def tick(self) -> bool:
        with self._lock:
            trial = self._trial
            if trial is None:
                return False
            now = self.clock()
            self._sample(trial, now)
            if trial["stop_at"] is not None:
                if now - trial["stop_at"] >= SETTLE_S:
                    self._finish(trial)
                    return False
                return True
            if now - trial["last_odom_at"] > ODOM_MAX_AGE_S:
                self._abort(trial, "odometry went stale during the trial")
            elif trial["travel"] >= TRAVEL_CAP_M:
                self._abort(trial, "the travel cap was reached")
            elif trial["first_hold"] is None:
                if now - trial["started_at"] > HOLD_START_S:
                    self._abort(trial, "the hold never began")
            elif now - trial["first_hold"] > MAX_HOLD_S:
                self._abort(trial, "the hold ran past its time limit")
            elif trial["stop_cause"] == "command_loss":
                if now - trial["last_hold"] > LOSS_GAP_S:
                    # No zero command here: the stream's loss itself must stop the robot.
                    trial["stop_at"] = trial["last_hold"]
            elif now - trial["last_hold"] > HOLD_GAP_S:
                self._abort(trial, "the hold was lost before a button release")
            return self._trial is not None

    def _motion_check(self, trial) -> dict | None:
        """Floor only: a lifted robot's wheels turn free by design, and its record says so."""
        if trial["test_surface"] != "floor":
            return None
        end = self.state.get_sensor("lidar")
        if not end or not _scan_is_current(end, self.wall()):
            raise TrialRefused("SCAN_UNUSABLE", "no current LiDAR scan after the trial")
        samples = trial["samples"]
        if len(samples) < 2:
            raise TrialRefused("ODOM_STALE", "too few odometry samples")
        first, last = samples[0], samples[-1]
        if trial["angular"]:
            odom = math.atan2(math.sin(last["yaw"] - first["yaw"]), math.cos(last["yaw"] - first["yaw"]))
        else:
            odom = (math.cos(first["yaw"]) * (last["x"] - first["x"]) + math.sin(first["yaw"]) * (last["y"] - first["y"]))
        return check_floor_motion(trial["start_scan"], end, self.line_config(), trial["direction"], odom)

    def _write(self, name: str, content: bytes) -> None:
        handle, temporary = tempfile.mkstemp(dir=self.directory)
        with os.fdopen(handle, "wb") as out:
            out.write(content)
        os.chmod(temporary, 0o640)
        os.replace(temporary, self.directory / name)

    def _finish(self, trial) -> None:
        self._trial = None
        self._zero()
        identity = {"direction": trial["direction"], "stop_cause": trial["stop_cause"]}
        try:
            scan_check = self._motion_check(trial)
        except TrialRefused as exc:
            self.last = {**identity, "state": "refused", "code": exc.code, "reason": exc.detail}
            return
        raw = json.dumps({**identity, "requested_linear_mps": trial["linear"], "requested_angular_rps": trial["angular"],
                          "stop_requested_at": trial["stop_at"], "samples": trial["samples"]}).encode("ascii")
        name = f"{trial['direction']}-{trial['stop_cause']}"
        # Beside the raw file, not in it: schema v2 takes exactly its own fields.
        record = {"test_surface": trial["test_surface"], "raw_sha256": hashlib.sha256(raw).hexdigest(),
                  "scan_check": scan_check}
        try:
            self.directory.mkdir(mode=0o750, parents=True, exist_ok=True)
            self._write(name + SURFACE_SUFFIX, json.dumps(record).encode("ascii"))
            self._write(name + ".json", raw)
        except OSError as exc:
            self.last = {**identity, "state": "aborted", "reason": f"evidence could not be written: {exc}"}
            return
        self.last = {**identity, "state": "recorded", "test_surface": trial["test_surface"], "scan_check": scan_check}
