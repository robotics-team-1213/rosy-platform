"""core_features.docking.bay_turn_watch — every in-place turn in the bay flow is closed on the LiDAR yaw change.

Rounds 11-17 on y8xs showed wheels turning while the body did not (direction-dependent, up to 20 deg of odometry-only error:
the staging turn ended +21 deg off, the in-bay body yawed against straight odometry). Odometry yaw (and so the map yaw) cannot tell.
While a turn runs, the bridge matches consecutive body scans (bay_scan_pose.locate: the robot's pose in the previous scan's frame, its
heading the yaw increment); the increments add up to the LiDAR yaw. If it differs from the odometry yaw by more than bay_turn_follow_rad
the turn stops and fails ("turn not followed by the body"); no matches for bay_turn_watch_wait_s fail it too ("not verified"), and the
staging turn ends only when a fresh match taken after it stood still agrees with the odometry. The watch is off when no scan feed
exists (no `note_sample`), so docks and tests without the bridge's scans behave as before. A mixin of `BayPhases`. ROS-free.
"""

from __future__ import annotations

import math
from typing import Optional

from core_features.docking.model import DockPhase
from core_features.docking.parking import ParkingGains, turn_twist

_TURN_GAINS = ParkingGains()


def _wrap(angle: float) -> float:
    return math.remainder(angle, math.tau)


class BayTurnMixin:
    def _init_tw(self) -> None:
        self._last_sample = None                  # the newest body-scan sample (the bridge hands it over every scan)
        self._last_sample_at = None
        self._last_sample_lag = 0.0
        self._tw_flipped = False
        self._turn_bad_dir = 0.0                  # the sense this robot failed to turn in (learned for the process): the next dock tries the other first
        self._tw: Optional[dict] = None
        self._turn_want = math.pi
        self._turn_passed_pi = True

    def note_sample(self, sample, lag_s: float = 0.0) -> None:
        self._last_sample_at = self._h.now()
        self._last_sample_lag = max(0.0, min(float(lag_s), 1.5))      # how old the scan already was when it arrived: its capture time = now - lag
        self._last_sample = sample                # one assignment: no lock, like note_body_scan

    def _tw_tol(self, tw) -> float:
        """How far the LiDAR yaw may differ from odometry: the 8 deg floor plus a proportional part (odometry reads ~4 % more over a turn)."""
        cfg = self._h._cfg
        return max(cfg.bay_turn_follow_rad, cfg.bay_turn_follow_ratio * max(abs(tw["lidar_odo"]), abs(tw["lidar"])))

    def _tw_start(self, yaw: float, now: float, want: Optional[float] = None) -> None:
        """A turn begins: watch it when the bridge feeds scans."""
        self._tw = None if self._last_sample is None else {
            "ref": self._last_sample, "last_yaw": yaw, "odo": 0.0, "odo_ask": 0.0, "lidar": 0.0, "lidar_odo": 0.0,
            "good_at": now, "ask_at": now, "bad": 0, "fail": None, "final_since": None, "final_ok": False,
            "final_seq": 0, "odo_prev": 0.0, "hist": [(now, 0.0)], "asks": {}, "want": want, "fixes": 0, "pairs": []}

    def _tw_odo(self, yaw: float, now: Optional[float] = None) -> None:
        tw = self._tw
        if tw is not None:
            tw["odo"] += _wrap(yaw - tw["last_yaw"])
            tw["last_yaw"] = yaw
            now = self._h.now() if now is None else now
            tw["hist"] = [s for s in tw["hist"] if now - s[0] <= 3.0] + [(now, tw["odo"])]

    @staticmethod
    def _odo_at(hist, t: float) -> float:
        """The odometry yaw (turned so far) at time t, interpolated: the scan is compared with the wheels at its own capture time."""
        if t <= hist[0][0]:
            return hist[0][1]
        for (t0, a0), (t1, a1) in zip(hist, hist[1:]):
            if t0 <= t <= t1:
                return a0 if t1 == t0 else a0 + (a1 - a0) * (t - t0) / (t1 - t0)
        return hist[-1][1]

    def _tw_ask(self, now: float):
        """scan_request, for a running watch: the previous scan as the reference (the current one becomes the next)."""
        tw, cfg = self._tw, self._h._cfg
        if tw is not None and self._h.phase is not DockPhase.TURNING and self._fh_turn is None:
            self._tw = tw = None                  # the turn is over: no more scan matching in BACKOFF / STAGING / ACQUIRING
        if tw is None or self._req_open is not None or self._last_sample is None:
            return None
        if now - (self._last_sample_at or -1e9) > cfg.bay_scan_fresh_s * 2:
            return None                                   # a stale scan is not asked about (matching it proves nothing)
        due = tw["final_since"] is not None and now - tw["final_since"] >= cfg.bay_turn_settle_s and not tw["final_ok"]
        if not (due or (tw["final_since"] is None and now - tw["ask_at"] >= cfg.bay_turn_ask_s)):
            return None
        ref, tw["ref"], tw["ask_at"] = tw["ref"], self._last_sample, now
        odo_cap = self._odo_at(tw["hist"], now - self._last_sample_lag)        # equal timestamps: the wheels when the scan was captured
        tw["odo_prev"], tw["odo_ask"] = tw["odo_ask"], odo_cap
        req = self._open_request(ref, "turn")
        return req + ("turn", tw["odo_ask"] - tw["odo_prev"])        # (id, scan, kind, the odometry increment as the match's seed)

    def _tw_note(self, match, now: float, rid: int = 0) -> None:
        tw, cfg = self._tw, self._h._cfg
        if tw is None:
            return
        if match is None or match.inliers < cfg.bay_turn_inlier_min or abs(match.heading) > cfg.bay_scan_heading_max_rad:
            tw["bad"] += 1
            return
        tw["bad"], tw["good_at"] = 0, now          # (a late answer still adds its increment above)
        tw["lidar"] += match.heading
        tw["lidar_odo"] = tw["odo_ask"]
        self._h._last_event = "turn watch: odometry %.0f deg, LiDAR %.0f deg%s" % (
            math.degrees(tw["lidar_odo"]), math.degrees(tw["lidar"]), " (after the flip)" if self._tw_flipped else "")
        tw["pairs"] = [p for p in tw["pairs"] if now - p[0] <= cfg.bay_turn_stall_s + 0.5] + [(now, tw["lidar_odo"], tw["lidar"])]
        first = tw["pairs"][0]
        # sliding-window stall: the wheels turned beyond the floor while the LiDAR barely moved (strict, no proportional allowance)
        stalled = (now - first[0] >= cfg.bay_turn_stall_s and abs(tw["lidar_odo"] - first[1]) > cfg.bay_turn_follow_rad
                   and abs(tw["lidar"] - first[2]) < 0.4 * abs(tw["lidar_odo"] - first[1]))
        if stalled or abs(tw["lidar"] - tw["lidar_odo"]) > self._tw_tol(tw):
            tw["fail"] = "bay turn not followed by the body (odometry %.0f deg, LiDAR %.0f deg)" % (
                math.degrees(tw["lidar_odo"]), math.degrees(tw["lidar"]))
        elif tw["final_since"] is not None and rid > tw["final_seq"]:
            tw["final_ok"] = True
            tw["final_lidar"] = tw["lidar"]          # only an answer to a request opened AFTER the turn stood still verifies it

    def _tw_verdict(self, now: float) -> Optional[str]:
        """Why the running turn must stop (a failure text), or None."""
        tw, cfg = self._tw, self._h._cfg
        if tw is None:
            return None
        if tw["fail"]:
            return tw["fail"]
        if tw["bad"] >= 2 or now - tw["good_at"] > cfg.bay_turn_watch_wait_s:
            return "bay turn not verified by LiDAR (no scan match for %.1f s): stopped" % (now - tw["good_at"])
        return None

    def _tw_flip(self, pose, now: float) -> bool:
        """(4) y8xs cannot turn clockwise (LiDAR -0.5 deg for -24 deg of odometry) but ccw is fine. A staging turn the body does not follow
        is retried ONCE the other way: the swing is checked clear every tick (the staging point is outside the row), the target is what
        the LiDAR says is left plus the full turn, the watch restarts. Else the caller fails "turn not followed by the body"."""
        tw = self._tw
        if self._tw_flipped or self._turn_dir == 0.0 or abs(tw["lidar"]) > self._h._cfg.bay_turn_flip_max_rad:
            return False                                  # a turn that moved the body part way is not a one-sense failure: no flip
        self._tw_flipped = True
        lidar_done = abs(tw["lidar"])
        self._turn_bad_dir = self._turn_dir                   # remembered: the next dock turns the other way first
        self._h._last_event = "turn flipped: %s did not move the body (odometry %.0f deg, LiDAR %.0f deg)" % (
            "cw" if self._turn_dir < 0 else "ccw", math.degrees(tw["lidar_odo"]), math.degrees(tw["lidar"]))
        self._turn_dir = -self._turn_dir
        want = math.pi + lidar_done
        self._turn_target = pose[2] + self._turn_dir * want
        self._turn_want = want
        self._turn_passed_pi = want <= math.pi
        self._stop()
        self._tw_start(pose[2], now, want=want)
        return True

    def _tick_turning(self, now: float) -> None:
        h = self._h
        pose = self._odometry()
        if pose is None:
            h._fail("bay odometry unavailable")
            return
        if self._tw is None and self._last_sample is None and h._cfg.bay_turn_needs_scan:
            self._stop()
            h._fail("bay turn needs the LiDAR scan feed and none has arrived: not turning")
            return
        self._tw_odo(pose[2], now)
        body = self._body_fresh(now)
        if body is not None and body[3] < h._phase_since:
            body = None          # a scan from before the stop at staging says nothing about here
        if body is None or body[0] is not None:
            # the turn runs only while the body scan (with the tray) says the sweep is clear — every tick (2026-11-18, neighbour contact)
            self._stop()
            if body is not None or now - h._phase_since > h._cfg.bay_scan_wait_s:
                h._fail("bay turn not clear: %s" % (body[0] if body else "no fresh body scan"))
            return
        tw = self._tw
        if tw is not None and (self._last_sample_at is None or now - self._last_sample_at > h._cfg.bay_scan_fresh_s * 2):
            self._stop()                                  # the scan feed stopped: no blind turn
            if now - tw["good_at"] > h._cfg.bay_turn_watch_wait_s:
                h._fail("bay turn not verified by LiDAR (no fresh scan): stopped")
            return
        why = self._tw_verdict(now)
        if why and "not followed" in why and self._tw_flip(pose, now):
            return
        if why:
            self._stop()
            h._fail(why)
            return
        if tw is not None and tw["final_since"] is not None:       # odometry says turned: wait for the LiDAR to agree
            self._stop()
            if tw["final_ok"]:
                # Close the turn on the LiDAR: a turn that fell short of its intended angle by 3-15 deg is turned on (same sense, twice at most)
                short = (tw["want"] or 0.0) - abs(tw.get("final_lidar", 0.0))
                if tw["want"] and tw["fixes"] < 2 and h._cfg.bay_turn_close_min_rad <= short <= h._cfg.bay_turn_close_max_rad:
                    tw["fixes"] += 1
                    tw["final_since"], tw["final_ok"] = None, False
                    self._turn_target = pose[2] + self._turn_dir * short
                    h._last_event = "turn closed on the LiDAR: %.0f deg short, turning on" % math.degrees(short)
                    return
                self._tw = None
                h._begin_acquiring()
            elif now - tw["final_since"] > h._cfg.bay_turn_watch_wait_s:
                h._fail("bay turn not verified by LiDAR after it stopped: stopped")
            return
        error = _wrap(self._turn_target - pose[2])
        if error * self._turn_dir > 0.0 and abs(error) < math.pi - 0.3:
            self._turn_passed_pi = True
        if error * self._turn_dir < 0.0:
            want = getattr(self, "_turn_want", math.pi)
            passed = getattr(self, "_turn_passed_pi", True)
            wrap_floor = (math.pi - 0.2) if passed else (math.tau - max(math.pi, want) - 0.2)
            if abs(error) > wrap_floor:
                error += self._turn_dir * 2.0 * math.pi  # start: near +-pi or want > pi unwrap cleanly
            elif abs(error) > h._cfg.bay_turn_overshoot_rad:
                self._stop()                             # a long way back would swing the tray upstream
                h._fail("bay turn overshot the target")
                return
        angular, done = turn_twist(error, _TURN_GAINS)
        if done:
            self._stop()
            if tw is None:
                h._begin_acquiring()                     # no scan feed: odometry only, as before
            else:
                tw["final_since"], tw["final_seq"] = now, self._req_seq
            return
        if now - h._phase_since > h._cfg.turn_timeout_s:
            self._stop()
            h._retry("bay turn timed out")
            return
        self._drive(0.0, angular)