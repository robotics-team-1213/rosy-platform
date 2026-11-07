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
PAIRS = {("forward", "button_release"), ("reverse", "button_release"), ("cw", "button_release"),
         ("ccw", "button_release"), ("forward", "command_loss")}
COMMANDS = {"forward": (1, 0), "reverse": (-1, 0), "cw": (0, -1), "ccw": (0, 1)}


class TrialRefused(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _returns_in_sector(points, centre_rad) -> int:
    half = math.pi / 4
    return sum(abs(math.atan2(math.sin(math.atan2(y, x) - centre_rad), math.cos(math.atan2(y, x) - centre_rad))) <= half
               for x, y in points)


def _closer_than_range_min(sample, forward_deg, centre_rad, range_min) -> bool:
    """A finite return under range_min is something very close that scan_points drops."""
    step = (float(sample["angle_max"]) - float(sample["angle_min"])) / (len(sample["ranges"]) - 1)
    for index, value in enumerate(sample["ranges"]):
        distance = float(value)
        if math.isfinite(distance) and distance < range_min:
            angle = float(sample["angle_min"]) + index * step - math.radians(float(forward_deg)) - centre_rad
            if abs(math.atan2(math.sin(angle), math.cos(angle))) <= math.pi / 4:
                return True
    return False


def _blind_m(config, direction: str, range_min: float) -> float:
    """How far past the body the LiDAR cannot see in this direction (C1 reports range_min 0.15 m, D-422)."""
    if direction == "forward":
        return max(0.0, range_min - (config.body_front_x_m - config.body_lidar_x_m))
    if direction == "reverse":
        return max(0.0, range_min - (config.body_lidar_x_m - config.body_rear_x_m), self_mask_rear_blind_m(
            config.lidar_self_mask, lidar_x_m=config.body_lidar_x_m, rear_x_m=config.body_rear_x_m,
            half_width_m=config.body_half_width_m))
    return max(0.0, range_min - (config.body_rotation_radius_m - abs(config.body_lidar_x_m)))


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
        if direction in ("forward", "reverse") and _closer_than_range_min(
                sample, config.lidar_forward_deg, 0.0 if direction == "forward" else math.pi, range_min):
            raise TrialRefused("CLEARANCE_UNKNOWN", "something is closer than the LiDAR can measure")
    except TrialRefused:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise TrialRefused("CLEARANCE_UNKNOWN", f"the LiDAR scan is unreadable: {exc}") from exc
    seen = body_clearances(points, lidar_x_m=config.body_lidar_x_m, rear_x_m=config.body_rear_x_m,
                           half_width_m=config.body_half_width_m,
                           rotation_radius_m=config.body_rotation_radius_m)
    need = TRAVEL_CAP_M + RUN_MARGIN_M
    # Returns under range_min and inside self-mask windows are dropped, so the band next to the body can
    # never be proved clear. Visible returns must still clear, and a person answers for the rest. Reverse
    # always asks: nothing watches the rear while driving.
    blind = _blind_m(config, direction, range_min)
    if (blind > 0.0 or direction == "reverse") and not blind_zone_confirmed:
        raise TrialRefused("BLIND_ZONE_CONFIRMATION_REQUIRED",
                           f"LiDAR cannot see {blind * 100:.0f} cm next to the body: confirm it by eye or camera")
    if direction == "reverse":
        if _returns_in_sector(points, math.pi) < MIN_SECTOR_RETURNS * count / 4:
            raise TrialRefused("CLEARANCE_UNKNOWN", "too few LiDAR returns behind the robot")
        if seen["rear_m"] is not None and seen["rear_m"] < need:
            raise TrialRefused("CLEARANCE_TOO_SMALL", f"{seen['rear_m']:.2f} m behind the body, {need:.2f} m needed")
        return {**seen, "blind_m": blind}
    if direction == "forward":
        if _returns_in_sector(points, 0.0) < MIN_SECTOR_RETURNS * count / 4:
            raise TrialRefused("CLEARANCE_UNKNOWN", "too few LiDAR returns ahead of the robot")
        front = seen["front_band_m"]
        free = None if front is None else front - (config.body_front_x_m - config.body_lidar_x_m)
        if free is not None and free < need:
            raise TrialRefused("CLEARANCE_TOO_SMALL", f"{free:.2f} m ahead of the body, {need:.2f} m needed")
        return {**seen, "blind_m": blind}
    if len(points) < MIN_SECTOR_RETURNS * count:
        raise TrialRefused("CLEARANCE_UNKNOWN", "too few LiDAR returns around the robot")
    if seen["turn_m"] is None or seen["turn_m"] < TURN_MARGIN_M:
        raise TrialRefused("CLEARANCE_TOO_SMALL", f"{TURN_MARGIN_M:.2f} m needed beyond the turning circle")
    return {**seen, "blind_m": blind}


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
