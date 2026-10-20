"""Read-only queue selection for energy estimation; never claims or authorizes work."""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import sqlite3
import threading

from fleet.server.charge_policy_admission import work_request_digest


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate stored work key')
        result[key] = value
    return result


def _parse_time(value):
    if not isinstance(value, str):
        raise ValueError('stored work time is not an ISO timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('stored work time requires an explicit timezone')
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class ChargeWorkSelection:
    robot_id: str
    task_id: str
    goal: tuple[float, float, float]
    request_digest: str
    authority_epoch: int
    generation: int
    priority_class: int
    queued_at: str
    expires_at: str | None


class ChargeWorkSelector:
    def __init__(self, tasks, *, clock):
        self.tasks, self.clock = tasks, clock
        self._lock = threading.Lock()
        self._last_clock = None
        self._clock_broken = False

    def _now(self):
        now = self.clock()
        if (self._clock_broken or type(now) not in (int, float) or not math.isfinite(now)
                or now < 0 or self._last_clock is not None and now < self._last_clock):
            self._clock_broken = True
            raise ValueError('CHARGE_WORK_CLOCK_INVALID')
        self._last_clock = now
        return datetime.fromtimestamp(now, timezone.utc)

    def select(self, robot_id):
        """Call outside the async loop. An estimate does not acquire a scheduler lease."""
        with self._lock:
            try:
                return self._select(robot_id)
            except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, OverflowError):
                return None

    def _select(self, robot_id):
        with closing(self.tasks._connect()) as connection:
            connection.execute('BEGIN')
            now = self._now()
            control = connection.execute(
                'SELECT authority_epoch,generation,dispatch_enabled FROM fleet_dispatch_control '
                'WHERE control_id=1').fetchone()
            if control is None or not control['dispatch_enabled']:
                return None
            rows = connection.execute(
                "SELECT * FROM fleet_tasks WHERE robot_id=? AND status='QUEUED' "
                "AND dispatch_phase='READY' ORDER BY priority_class,queued_at,task_id",
                (robot_id,))
            row = None
            # Match the scheduler's queue order; expired work has no dispatch authority.
            for candidate in rows:
                if candidate['expires_at'] is None or _parse_time(candidate['expires_at']) > now:
                    row = candidate
                    break
            if row is None:
                return None
            if (row['task_type'] != 'navigate' or row['queued_at'] is None
                    or row['lease_until'] is not None and _parse_time(row['lease_until']) > now):
                return None
            if len(row['request_json']) > 65536:
                return None
            request = json.loads(row['request_json'], object_pairs_hook=_unique)
            if not isinstance(request, dict) or set(request) != {'goal'}:
                return None
            goal = request['goal']
            if (not isinstance(goal, dict) or set(goal) != {'x', 'y', 'yaw'}
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in goal.values())):
                return None
            result = ChargeWorkSelection(robot_id=robot_id, task_id=row['task_id'],
                goal=tuple(float(goal[k]) for k in ('x', 'y', 'yaw')),
                request_digest=work_request_digest(dict(row) | {'request': request}),
                authority_epoch=control['authority_epoch'], generation=control['generation'],
                priority_class=row['priority_class'], queued_at=row['queued_at'], expires_at=row['expires_at'])
        # A read transaction sees its original snapshot. Check stop/rearm using a
        # new read after closing it, rather than mistaking that snapshot for a fence.
        with closing(self.tasks._connect()) as connection:
            current = connection.execute(
                'SELECT authority_epoch,generation,dispatch_enabled FROM fleet_dispatch_control '
                'WHERE control_id=1').fetchone()
            if (current is None or not current['dispatch_enabled']
                    or current['authority_epoch'] != result.authority_epoch
                    or current['generation'] != result.generation):
                return None
        finished = self._now()
        if result.expires_at is not None and _parse_time(result.expires_at) <= finished:
            return None
        return result

    def matches(self, selection):
        """Re-read queue, immutable request and stop/rearm fences before using an estimate."""
        return isinstance(selection, ChargeWorkSelection) and self.select(selection.robot_id) == selection
