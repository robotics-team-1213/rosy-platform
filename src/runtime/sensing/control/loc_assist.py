"""Subject: the robot side of D-395 between ROS and the pure localization logic (P2-3).

`LocAssist` owns everything `loc_assist_node` decides: when to search, what the
`localization/state`, `localization/candidates` and `localization/result`
payloads say (contract: docs/plans/2026-10-01-d395-phase2-interfaces.md §1),
and which pose to inject with which covariance. Each call returns a list of
`(kind, payload)` outputs for the node to publish: 'state', 'candidates',
'result' (dicts) and 'inject' (an `Injection`).

Rules kept here, not in the node:
- Power-on is UNKNOWN and searches at once; SUSPECT and a set-down after a
  pickup search again. Nothing searches over a running 3 s check or while the
  robot is held.
- A search spans the time the robot stood still; one finishing after the robot
  moved is discarded. CANDIDATES are searched again only after the robot moved
  and `retry_s` passed, so a check manoeuvre gets fresh candidates without a
  global search per scan.
- Candidates are re-reported every `rereport_s` with a new stamp so a lost
  decision is retried (D-395 rev. 3). State goes out every `state_period_s`
  and on every change.
- Every decision gets exactly one result: at once when rejected, otherwise
  when its 3 s check passes or ends.
- The Nav2 goal cancel and replan on LOCALIZED is CORE's: it owns the goal and
  acts on the LOCALIZED state and the accepted result. The state payload stays
  `{status, pose, stamp}` (contract §1).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

import numpy as np
from core_common.protocol.localization import (CandidateReport, LocalizationDecision,
                                               LocalizationStatus)
from pydantic import ValidationError

from .sensing.loc_candidates import global_candidates, merge, sensor_from_base, slot_candidates
from .sensing.loc_objects import unmapped_objects
from .sensing.loc_state import LocalizationStateMachine, LocState

#: Injection standard deviations per decision source, (metres, radians).
COVARIANCE = {'candidate': (.05, .1), 'human': (.15, .3),
              'overhead': (.10, .2), 'homing_ref': (.05, .1)}
#: CandidateReport limits (core_common.protocol.localization).
MAX_CANDIDATES, MAX_OBJECTS, MAX_SIGHTINGS = 8, 16, 4
#: A robot that moved more than this during a search did not stand still.
STILL_M, STILL_RAD = .005, .02
#: CORE and this node read the same robot clock; more than this ahead is not jitter.
RECEIPT_AHEAD_S = .5
#: CORE's longest mission (120 s) plus a margin: a running mission whose end never arrives
#: (lost message, CORE restart) stops pausing the search after this (P2-7).
MISSION_PAUSE_S = 130.
#: S1 re-run R3: a search waits until the odom twist stays under these for SETTLE_S;
#: a scan taken while the robot still turns puts the candidate degrees off.
STILL_MPS, STILL_RADPS, SETTLE_S = .01, .02, .5
#: A robot that never settles (odom lost, a creeping wheel) still gets a search after this.
SETTLE_CAP_S = 5.


@dataclass(frozen=True)
class Injection:
    """A map-frame base_link pose for `initialpose`, with its standard deviations."""
    pose: tuple
    xy_std: float
    yaw_std: float
    source: str
    request_id: str


def _moved(a, b, metres, radians):
    turn = math.atan2(math.sin(a[2] - b[2]), math.cos(a[2] - b[2]))
    return math.dist(a[:2], b[:2]) > metres or abs(turn) > radians


class LocAssist:
    def __init__(self, new_request_id, *, rereport_s=2., state_period_s=.5, retry_s=5.,
                 moved_m=.05, moved_rad=.17, hold_s=3., min_fit=.85, fit_drop_s=1., max_gap_s=.5):
        self.machine = LocalizationStateMachine(new_request_id, hold_s=hold_s, min_fit=min_fit,
                                                fit_drop_s=fit_drop_s, max_gap_s=max_gap_s)
        self.rereport_s, self.state_period_s, self.retry_s = rereport_s, state_period_s, retry_s
        self.moved_m, self.moved_rad = moved_m, moved_rad
        self.pose = self.fit = None
        self.held = False
        self._epoch = 0                     # pickups so far: a search spanning one is void
        self._wanted = True                 # power-on: search at once
        self._searching = None              # (odom, epoch, start s) of the running search
        self._searched_at, self._searched_odom = -math.inf, None
        self._report, self._reported_s = None, -math.inf
        self._state_s, self._state_key = -math.inf, None
        self._pending = None                # request id whose 3 s check is running
        self._mission = None                # since when a CORE mission moves the robot (P2-7)
        self._still_since = None            # first odom twist of the current still run
        self._due_since = None              # since when a search waits for the robot to settle
        self.settle_timed_out = False       # the last due search came from SETTLE_CAP_S

    # --- inputs -------------------------------------------------------------
    def on_amcl_pose(self, pose):
        """Latest AMCL base_link pose (x, y, yaw) in the map frame."""
        self.pose = tuple(float(v) for v in pose)

    def on_fit(self, now_s, fit):
        """Scan/map fit at the AMCL pose for one fresh scan (None: no fit this scan)."""
        if fit is not None:
            self.fit = float(fit)
        return self._after(self.machine.observe_fit(now_s, fit), now_s)

    def on_pickup(self, now_s, active):
        out = []
        if active and not self.held:
            self._epoch += 1
            out = self._after(self.machine.picked_up(now_s), now_s)
            self._wanted = True
        self.held = bool(active)
        return out

    def on_mission(self, now_s, payload):
        """CORE's `localization/mission` (D-395 P2-7): no search and no decision while a
        mission moves the robot; every end asks for a search at once, so Fleet gets fresh
        candidates. Candidates offered before the mission are stale after it: the open
        request id and its report are dropped at the start (S1 re-run, F1 WSL run)."""
        state = payload.get('state') if isinstance(payload, dict) else None
        if state == 'running':
            self._mission = float(now_s)
            self.machine.request_id, self._report = None, None
        elif state in ('done', 'aborted'):
            self._mission, self._wanted = None, True

    def on_twist(self, now_s, linear_mps, angular_radps):
        """Odom twist: speed in m/s and yaw rate in rad/s. Still means both under the limits."""
        still = abs(linear_mps) < STILL_MPS and abs(angular_radps) < STILL_RADPS  # NaN: moving
        if not still:
            self._still_since = None
        elif self._still_since is None:
            self._still_since = float(now_s)

    def on_suspect(self, now_s, payload):
        reason = payload.get('reason') if isinstance(payload, dict) else None
        reason = str(reason or 'fleet_monitor')[:64]
        return self._after(self.machine.mark_suspect(reason), now_s)

    def on_decision(self, now_s, payload):
        """`{"decision": LocalizationDecision, "received_s": float}` from CORE.

        `received_s` (CORE's ROS clock at receipt, same robot) is required: the
        ttl counts from it, so a missing, non-finite or future one (beyond
        RECEIPT_AHEAD_S of clock jitter) is `bad_receipt`. A repeat of the
        decision whose 3 s check is running returns nothing at all."""
        body = payload.get('decision') if isinstance(payload, dict) else None
        raw_id = body.get('request_id') if isinstance(body, dict) else None
        try:
            decision = LocalizationDecision.model_validate(body)
        except ValidationError:
            return [self._result(raw_id if isinstance(raw_id, str) else '', False, 'bad_decision')]
        if self._pending is not None and decision.request_id == self._pending:
            return []
        try:
            received_s = float(payload['received_s'])
        except (KeyError, TypeError, ValueError):
            received_s = math.nan
        if not math.isfinite(received_s) or received_s - now_s > RECEIPT_AHEAD_S:
            return [self._result(decision.request_id, False, 'bad_receipt')]
        if self.held:
            return [self._result(decision.request_id, False, 'held')]
        if self._mission_running(now_s):
            return [self._result(decision.request_id, False, 'mission_running')]
        pose = None if decision.pose is None else (decision.pose.x, decision.pose.y, decision.pose.yaw)
        step = self.machine.decide(decision.request_id, now_s, candidate_index=decision.candidate_index,
                                   pose=pose, source=decision.source.value,
                                   cues=[c.value for c in decision.cues],
                                   received_s=received_s, ttl_s=decision.ttl_s)
        if 'reject_decision' in step.actions:
            return [self._result(decision.request_id, False, step.reason)]
        self._pending = decision.request_id
        xy_std, yaw_std = COVARIANCE[decision.source.value]
        out = [('inject', Injection(step.pose, xy_std, yaw_std, decision.source.value,
                                    decision.request_id))]
        return out + self._state_if_changed(now_s)

    def tick(self, now_s):
        """Timer: scan-gap check, candidate re-report, state cadence."""
        out = []
        if self.machine.check is not None:
            out += self._after(self.machine.observe_fit(now_s, None), now_s)
        if (self.machine.state is LocState.CANDIDATES and self._report is not None and
                self.machine.check is None and now_s - self._reported_s >= self.rereport_s):
            out.append(self._candidates(now_s))
        if not any(kind == 'state' for kind, _ in out) and (
                now_s - self._state_s >= self.state_period_s or self._key() != self._state_key):
            out.append(self._state(now_s))
        return out

    # --- search -------------------------------------------------------------
    def search_due(self, now_s, odom):
        """Whether the node should start a candidate search now (odom: current (x, y, yaw)).

        A due search waits until the robot has been still for SETTLE_S, at most
        SETTLE_CAP_S; `settle_timed_out` says the cap released it."""
        if not self._search_wanted(now_s, odom):
            self._due_since = None
            return False
        if self._due_since is None:
            self._due_since = float(now_s)
        settled = self._still_since is not None and now_s - self._still_since >= SETTLE_S
        self.settle_timed_out = not settled and now_s - self._due_since >= SETTLE_CAP_S
        return settled or self.settle_timed_out

    def _search_wanted(self, now_s, odom):
        if (self._searching is not None or self.held or self.machine.check is not None
                or self._mission_running(now_s)):
            return False
        waited = now_s - self._searched_at >= self.retry_s
        state = self.machine.state
        if state in (LocState.UNKNOWN, LocState.SUSPECT):
            return self._wanted or waited
        if state is LocState.CANDIDATES:
            return self._wanted or (waited and odom is not None and self._searched_odom is not None
                                    and _moved(odom, self._searched_odom, self.moved_m, self.moved_rad))
        return False

    def _mission_running(self, now_s):
        return self._mission is not None and now_s - self._mission <= MISSION_PAUSE_S

    @property
    def camera_wanted(self):
        """Square and paint evidence only matter outside LOCALIZED; the node drops the camera there."""
        return self.machine.state is not LocState.LOCALIZED

    def search_started(self, now_s, odom):
        self._searching = (tuple(odom), self._epoch, float(now_s))
        self._due_since = None

    def search_finished(self, now_s, odom, candidates, unmapped=(), sightings=(), paint_scores=None,
                        evidence_s=None):
        """Offer what the search found. `sightings`: SquareObservation-like objects;
        `paint_scores`: one score (or None) per candidate, None for no camera paint;
        `evidence_s`: when that camera evidence was seen. Evidence from before the
        search started is dropped: it may belong to where the robot was before."""
        searching, self._searching = self._searching, None
        if searching is None or self.machine.check is not None or self.machine.state is LocState.LOCALIZED:
            return []
        started, epoch, start_s = searching
        if self.held or epoch != self._epoch:
            return []                       # picked up meanwhile: the set-down searches again
        if odom is None or _moved(odom, started, STILL_M, STILL_RAD):
            return []                       # still wanted: the next tick retries
        if evidence_s is None or evidence_s < start_s:
            sightings, paint_scores = (), None
        self._searched_at, self._searched_odom, self._wanted = now_s, tuple(odom), False
        candidates = list(candidates)[:MAX_CANDIDATES]
        step = self.machine.offer(candidates, now_s)
        if 'report_candidates' not in step.actions:
            return self._state_if_changed(now_s)
        scores = list(paint_scores or [None] * len(candidates))
        self._report = {
            'request_id': self.machine.request_id,
            'candidates': [{'x': c.x, 'y': c.y, 'yaw': c.yaw, 'scan_fit': min(1., max(0., c.scan_fit)),
                            'paint_score': s} for c, s in zip(candidates, scores)],
            'unmapped_objects': [{'x': float(x), 'y': float(y)} for x, y in list(unmapped)[:MAX_OBJECTS]],
            'square_sightings': [{'bearing_rad': s.bearing_rad, 'range_m': s.range_m,
                                  'confidence': s.confidence} for s in list(sightings)[:MAX_SIGHTINGS]],
        }
        return [self._candidates(now_s)] + self._state_if_changed(now_s)

    # --- outputs ------------------------------------------------------------
    def _after(self, step, now_s):
        out = []
        state = self.machine.state
        if self._pending is not None and state is LocState.LOCALIZED:
            out.append(self._result(self._pending, True, None))
            self._pending = None
        elif self._pending is not None and self.machine.check is None:
            out.append(self._result(self._pending, False, step.reason or self.machine.reason))
            self._pending = None
        if state is LocState.SUSPECT and 'report_status' in step.actions:
            self._wanted = True             # a fresh SUSPECT searches at once
        return out + self._state_if_changed(now_s)

    def _key(self):
        m = self.machine
        return (m.state.value, m.reason, m.request_id if m.state is LocState.CANDIDATES else None,
                self.pose is None)

    def _state_if_changed(self, now_s):
        return [self._state(now_s)] if self._key() != self._state_key else []

    def _state(self, now_s):
        m = self.machine
        status = LocalizationStatus(
            state=m.state.value, pose_frame='odom' if self.pose is None else 'map',
            confidence=0. if self.fit is None else min(1., max(0., self.fit)),
            reason=None if m.reason is None else str(m.reason)[:64],
            request_id=m.request_id if m.state is LocState.CANDIDATES else None)
        payload = {'status': status.model_dump(mode='json'),
                   'pose': None if self.pose is None else dict(zip(('x', 'y', 'yaw'), self.pose)),
                   'stamp': float(now_s)}
        self._state_key, self._state_s = self._key(), now_s
        return 'state', payload

    def _candidates(self, now_s):
        self._reported_s = now_s
        payload = {**self._report, 'pickup': self.machine.pickup, 'stamp': float(now_s)}
        CandidateReport.model_validate({**payload, 'robot_id': 'self'})
        return 'candidates', payload

    def _result(self, request_id, accepted, reason):
        return 'result', {'request_id': request_id, 'accepted': accepted, 'reason': reason,
                          'state': self.machine.state.value}


def search(field, clear, squares, ranges, angles, radius, mount, minimum_fit=.9, object_scan=None):
    """Slot then global candidates (at most 8) and the unmapped objects at the first one.

    `clear` is the cached `field.clear_poses(radius)` mask, or None to compute it;
    it is returned so the caller computes it once per map. `object_scan`: the
    (ranges, angles) the objects come from, default the search's own. Pass the
    full scan when the search is strided: a peer 2 m away spans about 4 beams
    of 640, so a stride of 4 leaves it one beam, under MIN_POINTS (S1 finding 2)."""
    clear = field.clear_poses(radius) if clear is None else clear
    found = merge(slot_candidates(field, squares, ranges, angles, radius, mount, minimum_fit, clear=clear),
                  global_candidates(field, ranges, angles, radius, mount, minimum_fit, clear=clear,
                                    fine_scan=object_scan))
    found = found[:MAX_CANDIDATES]
    objects = []
    if found:
        first = found[0]
        object_ranges, object_angles = (ranges, angles) if object_scan is None else object_scan
        objects = unmapped_objects(field, sensor_from_base((first.x, first.y, first.yaw), mount),
                                   object_ranges, object_angles, mount)
        # Every beam also keeps chassis returns: no peer is inside this robot's own radius.
        objects = [o for o in objects if math.hypot(*o) > radius]
    return found, objects, clear


def pooled_grid(grid, resolution, target):
    """Max-pool an occupancy grid to about `target` metres: any wall wins, then any unknown.

    The 5 mm site map makes one global search take tens of seconds; 2 cm keeps
    the walls (loc_world, D-395 Phase 1). A map already that coarse is returned as is."""
    k = int(round(target / resolution))
    if k <= 1:
        return grid, resolution
    grid = np.asarray(grid)
    h, w = grid.shape[0] // k * k, grid.shape[1] // k * k
    blocks = grid[:h, :w].reshape(h // k, k, w // k, k)
    pooled = np.where((blocks >= 65).any(axis=(1, 3)), 100,
                      np.where((blocks < 0).any(axis=(1, 3)), -1, 0)).astype(np.int8)
    return pooled, resolution * k


def lane_rules_near(map_yaml):
    """`lane_rules.yaml` beside the map YAML or one folder up (map bundles keep maps/ below it)."""
    if not map_yaml:
        return None
    folder = os.path.dirname(os.path.abspath(map_yaml))
    for candidate in (folder, os.path.dirname(folder)):
        path = os.path.join(candidate, 'lane_rules.yaml')
        if os.path.isfile(path):
            return path
    return None
