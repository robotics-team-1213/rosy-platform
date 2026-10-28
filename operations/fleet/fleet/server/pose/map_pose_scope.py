"""Opt-in ingestion fences for existing World trackers, not a second pose estimator.

The trusted caller must verify native boot/client identity before declaring a scope.
These local tickets are neither HTTP credentials nor proof of that verification.
"""
from dataclasses import dataclass
import math
import re

from rosy.world.state.projections.map_pose import LOCALIZED, odom_from_snapshot


@dataclass(frozen=True, eq=False)
class PoseSourceScope:
    robot_id: str
    boot_id: str
    odom_epoch: str
    client: object
    map_id: str
    generation: int
    not_before: float


class MapPoseScopes:
    def __init__(self, service):
        self.service = service
        self._bound, self._generations = {}, {}
        self._counter = 0
        self._last_clock = None
        self._clock_broken = False

    def _now(self):
        now = self.service._wall()
        if (self._clock_broken or type(now) not in (int, float) or not math.isfinite(now)
                or now < 0 or self._last_clock is not None and now < self._last_clock):
            self._clock_broken = True
            raise ValueError('MAP_POSE_SCOPE_CLOCK_INVALID')
        self._last_clock = now
        return now

    def generation(self, robot_id):
        return self._generations.get(robot_id, 0)

    def unqualified(self, robot_id, generation=None):
        return robot_id not in self._bound and (generation is None or generation == self.generation(robot_id))

    def prune(self, roster):
        for robot in set(self._bound) - set(roster):
            del self._bound[robot]
            self._counter += 1
            self._generations[robot] = self._counter

    def begin(self, robot_id, *, boot_id, odom_epoch, client):
        now, map_id = self._now(), self.service.active_map_id()
        if (not self.service.knows(robot_id) or client is None or not isinstance(boot_id, str)
                or not boot_id or not isinstance(odom_epoch, str)
                or re.fullmatch(r'0|[1-9][0-9]*', odom_epoch) is None or not map_id):
            raise ValueError('MAP_POSE_SOURCE_SCOPE_REQUIRED')
        current = self._bound.get(robot_id)
        if current is not None:
            ticket = current['ticket']
            if (not current['retired'] and ticket.boot_id == boot_id and ticket.odom_epoch == odom_epoch
                    and ticket.client is client and ticket.map_id == map_id):
                return ticket
        self._counter += 1
        ticket = PoseSourceScope(robot_id, boot_id, odom_epoch, client, map_id, self._counter, now)
        self._bound[robot_id] = dict(ticket=ticket, sample=None, usable=False, retired=False)
        self._generations[robot_id] = ticket.generation
        self.service._trackers.pop(robot_id, None)
        for key in list(self.service._kept):
            if key[0] == robot_id:
                del self.service._kept[key]
        return ticket

    def _current(self, ticket):
        if not isinstance(ticket, PoseSourceScope):
            return None
        self.prune(self.service._robot_ids())
        row = self._bound.get(ticket.robot_id)
        if row is None or row['ticket'] is not ticket or row['retired']:
            return None
        if ticket.map_id != self.service.active_map_id():
            row['retired'], row['usable'] = True, False
            return None
        return row

    def retire(self, ticket):
        if not isinstance(ticket, PoseSourceScope):
            return
        row = self._bound.get(ticket.robot_id)
        if row is not None and row['ticket'] is ticket and not row['retired']:
            row['retired'], row['usable'] = True, False
            self._counter += 1
            self._generations[ticket.robot_id] = self._counter
            self.service._trackers.pop(ticket.robot_id, None)
            for key in list(self.service._kept):
                if key[0] == ticket.robot_id:
                    del self.service._kept[key]

    def sighting(self, sighting):
        row = self._bound.get(sighting.robot_id)
        if row is None:
            return True
        ticket = row['ticket']
        try:
            return (self._current(ticket) is row and ticket.not_before < sighting.captured_at <= self._now()
                    and sighting.map_id == ticket.map_id)
        except ValueError:
            return False

    def observe(self, ticket, state):
        row = self._current(ticket)
        if row is None:
            return False
        try:
            now = self._now()
            sample = odom_from_snapshot(state)
            if (sample is None or state.get('robot_id') != ticket.robot_id
                    or state.get('map_id') != ticket.map_id or sample.epoch is None
                    or str(sample.epoch) != ticket.odom_epoch
                    or not ticket.not_before < sample.stamp <= now
                    or now-sample.stamp > self.service.config.max_odom_age_s):
                raise ValueError('MAP_POSE_ORIGINAL_ODOM_UNVERIFIED')
            previous = row['sample']
            if previous is not None and sample.stamp <= previous.stamp:
                if sample == previous and row['usable']:
                    return True  # Same original sample does not extend any lifetime.
                raise ValueError('MAP_POSE_ORIGINAL_ODOM_REPLAY')
            tracker = self.service._tracker(ticket.robot_id)
            if tracker is None or not tracker.add_odom(sample, now):
                raise ValueError('MAP_POSE_ORIGINAL_ODOM_REFUSED')
            row['sample'], row['usable'] = sample, True
            return True
        except (TypeError, ValueError, AttributeError):
            row['usable'] = False
            return False

    def pose(self, ticket):
        row = self._current(ticket)
        if row is None or not row['usable']:
            return None
        try:
            now = self._now()
            sample = row['sample']
            pose = self.service.arbitrated_pose(ticket.robot_id)
            anchor = self.service.odom_to_map(ticket.robot_id)
            if (pose is None or pose.state != LOCALIZED or pose.anchor_source != 'sighting'
                    or pose.odom_stamp != sample.stamp or pose.map_id != ticket.map_id
                    or anchor is None or not ticket.not_before < anchor[2] <= now
                    or not 0 <= now-sample.stamp <= self.service.config.max_odom_age_s
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in (pose.x, pose.y, pose.yaw))):
                return None
            finished = self._now()
            if (self._current(ticket) is not row or not row['usable'] or row['sample'] is not sample
                    or not 0 <= finished-sample.stamp <= self.service.config.max_odom_age_s
                    or not 0 <= finished-anchor[2] <= self.service.config.max_anchor_age_s):
                return None
            return pose
        except (TypeError, ValueError, AttributeError):
            return None
