"""D-986: records one G4 approval trial while a person holds the drive.

The drive goes through the caller's normal teleop path only while holds keep arriving, so this
adds no way to move the robot. The raw file has exactly the fields mapping_approval.py verifies;
the verdict stays there. A trial that cannot finish leaves no file.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time

from core_common.robot_body import inside_body
from core_features.line_follow.clearance import body_clearances, scan_points, self_mask_rear_blind_m

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
MIN_SECTOR_RETURNS = 0.5
# Of all the sector's beams, however many end on the body. Recorded C1 scans never fall below 0.44.
MIN_SEEING_BEAMS = 0.25
PAIRS = {("forward", "button_release"), ("reverse", "button_release"), ("cw", "button_release"),
         ("ccw", "button_release"), ("forward", "command_loss")}
COMMANDS = {"forward": (1, 0), "reverse": (-1, 0), "cw": (0, -1), "ccw": (0, 1)}


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


def require_clearance(sample, config, direction: str, blind_zone_confirmed: bool, wall_now: float) -> dict:
    """Raises unless a fresh full scan shows room. No or stale data never reads as free space."""
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
        if range_min > min(config.body_front_x_m - config.body_lidar_x_m, config.body_lidar_x_m - config.body_rear_x_m,
                           config.body_half_width_m):
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
        # Self-mask windows may hide the rear and nothing watches it while driving. Visible returns must
        # still clear, and a person answers for the rest.
        blind = self_mask_rear_blind_m(config.lidar_self_mask, lidar_x_m=config.body_lidar_x_m,
                                       rear_x_m=config.body_rear_x_m, half_width_m=config.body_half_width_m)
        if not blind_zone_confirmed:
            raise TrialRefused("BLIND_ZONE_CONFIRMATION_REQUIRED",
                               f"LiDAR cannot vouch for the rear ({blind * 100:.0f} cm masked): confirm it by eye or camera")
        if seen["rear_m"] is not None and seen["rear_m"] < need:
            raise TrialRefused("CLEARANCE_TOO_SMALL", f"{seen['rear_m']:.2f} m behind the body, {need:.2f} m needed")
        return {**seen, "blind_m": blind}
    if direction == "forward":
        front = seen["front_band_m"]
        free = None if front is None else front - (config.body_front_x_m - config.body_lidar_x_m)
        if free is not None and free < need:
            raise TrialRefused("CLEARANCE_TOO_SMALL", f"{free:.2f} m ahead of the body, {need:.2f} m needed")
        return seen
    if seen["turn_m"] is None or seen["turn_m"] < TURN_MARGIN_M:
        raise TrialRefused("CLEARANCE_TOO_SMALL", f"{TURN_MARGIN_M:.2f} m needed beyond the turning circle")
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

    def start(self, direction: str, stop_cause: str, owner: str, blind_zone_confirmed: bool = False) -> dict:
        if (direction, stop_cause) not in PAIRS:
            raise TrialRefused("TRIAL_UNKNOWN", f"{direction}/{stop_cause} is not a required trial")
        limits = self.safety.limits
        # A lower live limit would clip the command, and the evidence must say what was really sent.
        linear = min(TRIAL_LINEAR_MPS, limits.manual_linear)
        angular = min(TRIAL_ANGULAR_RPS, limits.manual_angular)
        if linear < MIN_LINEAR_MPS or angular < MIN_ANGULAR_RPS:
            raise TrialRefused("TRIAL_LIMIT_TOO_LOW", "the manual speed limit leaves no measurable motion")
        seen = require_clearance(self.state.get_sensor("lidar"), self.line_config(), direction,
                                 blind_zone_confirmed, self.wall())
        odom = self.state.odom_sample()
        if odom is None or odom[3] > ODOM_MAX_AGE_S:
            raise TrialRefused("ODOM_STALE", "odometry is not fresh")
        sign_linear, sign_angular = COMMANDS[direction]
        now = self.clock()
        with self._lock:
            if self._trial is not None:
                raise TrialRefused("TRIAL_ACTIVE", "another trial is running")
            self._trial = {"direction": direction, "stop_cause": stop_cause, "owner": owner, "started_at": now,
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

    def _finish(self, trial) -> None:
        self._trial = None
        self._zero()
        raw = {"direction": trial["direction"], "stop_cause": trial["stop_cause"],
               "requested_linear_mps": trial["linear"], "requested_angular_rps": trial["angular"],
               "stop_requested_at": trial["stop_at"], "samples": trial["samples"]}
        name = f"{trial['direction']}-{trial['stop_cause']}.json"
        try:
            self.directory.mkdir(mode=0o750, parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=self.directory)
            with os.fdopen(handle, "w", encoding="ascii") as out:
                json.dump(raw, out)
            os.chmod(temporary, 0o640)
            os.replace(temporary, self.directory / name)
        except OSError as exc:
            self.last = {"direction": trial["direction"], "stop_cause": trial["stop_cause"],
                         "state": "aborted", "reason": f"evidence could not be written: {exc}"}
            return
        self.last = {"direction": trial["direction"], "stop_cause": trial["stop_cause"], "state": "recorded"}
