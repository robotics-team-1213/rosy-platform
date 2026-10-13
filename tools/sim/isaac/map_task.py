"""D-638: simulation-only residual RL task; no ROS or operational endpoint."""
import bisect
import math
from pathlib import Path
import random
import sys
import time

import yaml

REPOSITORY = Path(__file__).resolve().parents[3]
MAP = REPOSITORY / 'middleware/perception/map/map_v2_fleet'
SOURCE_SHA256 = 'cabf17a84175da8be1ef7562054ec598971bbb9378810acb8cee3f686fe1f92b'
SEGMENTS = ('ring_n', 'west:reverse', 'ring_s', 'east:reverse', 'ring_n', 'ring_w', 'ring_s', 'ring_e')
SIM_DEVICE_IDS = ('isaac-pinky', 'isaac-pinky-a', 'isaac-pinky-b')


def load_track():
    sys.path.insert(0, str(MAP / 'scripts'))
    from stl_scene import load_scene
    from build_world import training_scene, caution_meshes
    scene = load_scene(MAP / '260919 MAP FILE.STL')
    if scene.source_sha256 != SOURCE_SHA256:
        raise ValueError('measured map source hash differs')
    graph = yaml.safe_load((MAP / 'training-curved/lane_graph.yaml').read_text())
    points = []
    previous = None
    bans = {(b['at'], b['from_edge'], b['to_edge']) for b in graph['turn_bans']}
    for name in SEGMENTS:
        segment, _, direction = name.partition(':')
        entry = graph['segments'][segment]
        if direction and direction not in entry['directions']:
            raise ValueError('lane route direction forbidden')
        part = [tuple(p) for p in entry['points']]
        if direction == 'reverse':
            part.reverse()
        start = entry['to'] if direction == 'reverse' else entry['from']
        if previous is not None and (start, previous, segment) in bans:
            raise ValueError('lane route turn forbidden')
        if points and math.dist(points[-1], part[0]) > .001:
            raise ValueError('lane route disconnected')
        points.extend(part if not points else part[1:])
        previous = segment
    return dict(scene=training_scene(scene), points=points, segments=SEGMENTS, caution_meshes=caution_meshes(),
                source_sha256=scene.source_sha256)


class MapTask:
    def __init__(self, points, *, half_size, time_limit=400.):
        self.points = tuple(tuple(p) for p in points)
        if len(self.points) < 2 or not all(len(p) == 2 and all(math.isfinite(x) for x in p) for p in self.points):
            raise ValueError('finite ordered route required')
        self.distance = [0.]
        for a, b in zip(self.points, self.points[1:]):
            self.distance.append(self.distance[-1] + math.dist(a, b))
        if self.distance[-1] <= 0:
            raise ValueError('nonzero route required')
        self.half_size = half_size
        self.time_limit = time_limit
        self.index = 0
        self.window_end = 0
        self.previous = None
        self.stopped_since = None
        self.result = None
        from control.control.path_follow import PathFollower
        self.follower = PathFollower()

    def observe(self, x, y, yaw, linear, angular, elapsed):
        if self.result is not None:
            return self.result
        previous_progress = self.distance[self.index]
        reason = ''
        finite = all(type(v) in (int, float) and math.isfinite(v) for v in (x, y, yaw, linear, angular, elapsed))
        if not finite or elapsed < 0:
            reason = 'invalid_observation'
        elif abs(x) + .086 >= self.half_size[0] - .005 or abs(y) + .086 >= self.half_size[1] - .005:
            reason = 'wall_overlap'
        elif self.previous is not None:
            dt = elapsed - self.previous[2]
            if dt <= 0 or math.dist((x, y), self.previous[:2]) > .20 * dt + .005:
                reason = 'pose_jump'
        if not reason:
            upper = bisect.bisect_right(self.distance, previous_progress + .12)
            nearest = min(range(self.index, min(len(self.points), upper)),
                          key=lambda i: math.dist((x, y), self.points[i]))
            deviation = math.dist((x, y), self.points[nearest])
            if deviation > .05:
                reason = 'off_route'
            else:
                self.index = nearest
        else:
            deviation = 0.
        goal = not reason and self.index >= len(self.points) - 2 and math.dist((x, y), self.points[-1]) < .015
        if goal and abs(linear) < .005 and abs(angular) < .02:
            if self.stopped_since is None:
                self.stopped_since = elapsed
        else:
            self.stopped_since = None
        complete = self.stopped_since is not None and elapsed - self.stopped_since >= .3
        truncated = not reason and not complete and elapsed >= self.time_limit
        progress = self.distance[self.index]
        state = dict(progress_m=progress, route_length_m=self.distance[-1], index=self.index,
                     deviation_m=deviation, goal_reached=goal, complete=complete,
                     terminated=bool(reason) or complete, truncated=truncated,
                     reason=reason or ('complete' if complete else 'time_limit' if truncated else ''),
                     reward=20 * (progress - previous_progress) - deviation * .2 - (10 if reason else 0))
        if complete:
            state['reward'] += 10
        if state['terminated'] or state['truncated']:
            self.result = state
        self.previous = (x, y, elapsed)
        return state

    def pursuit(self, x, y, yaw):
        from control.control.pursuit import pursuit_index
        if not self.window_end or self.distance[self.window_end - 1] - self.distance[self.index] < .12:
            self.window_end = min(len(self.points), bisect.bisect_right(
                self.distance, self.distance[self.index] + .35))
        # Matching remaining suffix preserves the existing Drive alignment history.
        route = self.points[max(0, self.index - 1):self.window_end]
        target = pursuit_index(route, x, y, .06)
        dx, dy = route[target][0] - x, route[target][1] - y
        error = math.atan2(math.sin(math.atan2(dy, dx) - yaw), math.cos(math.atan2(dy, dx) - yaw))
        speed, angular, _ = self.follower.update(route, (x, y, yaw), route_age=0., tf_age=0.,
                                                speed=.04, turn=.6, lookahead=.06,
                                                tolerance=.005, max_deviation=.05)
        state = (bisect.bisect_right((-.6, -.2, -.05, .05, .2, .6), error),
                 bisect.bisect_right((.01, .025), math.dist((x, y), self.points[self.index])))
        return state, speed, angular


class QPolicy:
    gains = (.75, 1., 1.35, 1.7)

    def __init__(self, seed):
        self.random = random.Random(seed)
        self.table = {}
        self.updates = 0

    def choose(self, state, *, explore):
        if explore and self.random.random() < .2:
            return self.random.randrange(len(self.gains))
        values = self.table.get(state)
        return 1 if values is None else max(range(len(values)), key=lambda i: values[i])

    def update(self, state, action, reward, next_state, *, terminated):
        if not math.isfinite(reward):
            raise ValueError('finite measured reward required')
        values = self.table.setdefault(state, [0.] * len(self.gains))
        future = 0. if terminated else max(self.table.get(next_state, [0.] * len(self.gains)))
        values[action] += .15 * (reward + .95 * future - values[action])
        self.updates += 1

    def export(self):
        return dict(updates=self.updates, gains=self.gains,
                    q={','.join(map(str, state)): values[:] for state, values in sorted(self.table.items())})

    @classmethod
    def restore(cls, data):
        if not isinstance(data, dict) or set(data) != {'updates', 'gains', 'q'}:
            raise ValueError('saved policy fields differ')
        if type(data['updates']) is not int or not 0 < data['updates'] <= 10**9:
            raise ValueError('measured policy updates required')
        if not isinstance(data['gains'], (list, tuple)) or not all(
                type(v) in (int, float) for v in data['gains']) or tuple(data['gains']) != cls.gains:
            raise ValueError('saved yaw gains differ')
        table = data['q']
        if not isinstance(table, dict) or not 0 < len(table) <= 21:
            raise ValueError('bounded saved state table required')
        policy = cls(seed=17)
        for key, values in table.items():
            if not isinstance(key, str) or key not in {f'{a},{b}' for a in range(7) for b in range(3)}:
                raise ValueError('saved state outside observation bins')
            if not isinstance(values, list) or len(values) != len(cls.gains) or not all(
                    type(v) in (int, float) and math.isfinite(v) for v in values):
                raise ValueError('finite action Q values required')
            policy.table[tuple(map(int, key.split(',')))] = values[:]
        if not any(v != 0. for values in policy.table.values() for v in values):
            raise ValueError('untrained zero policy refused')
        policy.updates = data['updates']
        return policy


class SimulationOwner:
    """Private in-process diagnostic owner; never an operational POLICY API."""
    def __init__(self, *, device_id='isaac-pinky'):
        if type(device_id) is not str or device_id not in SIM_DEVICE_IDS:
            raise ValueError('fixed simulation device identity required')
        from core_features.command.manager import CommandManager
        from core_features.command.arbitration import SourceRegistry, ModeMachine
        from core_features.safety.manager import SafetyManager, SpeedLimits, BatteryPolicy
        self.modes = ModeMachine()
        self.safety = SafetyManager(SpeedLimits(max_linear=.06, max_angular=.8), BatteryPolicy())
        self.command = CommandManager(SourceRegistry(), self.modes, self.safety)
        self._device_id = device_id
        self.epoch = 0
        self.halted = True
        self.pending = None

    def begin(self, epoch):
        from core_features.command.arbitration import Mode
        if type(epoch) is not int or epoch <= self.epoch:
            raise ValueError('new episode epoch required')
        self.stop()
        self.epoch = epoch
        self.halted = False
        if not self.modes.transition(Mode.NAVIGATION)[0]:
            raise ValueError('CORE navigation admission refused')

    def stop(self):
        from core_features.command.arbitration import Mode
        self.command.clear_navigation()
        self.modes.transition(Mode.IDLE)
        self.halted = True
        self.pending = None

    def submit(self, intent, *, observed_at, now, preserve_curvature=False):
        from rosy.contracts.motion import MotionIntent, MotionKind, PriorityClass
        from core_features.command.manager import Twist, ZERO
        valid = type(intent) is MotionIntent and intent.kind is MotionKind.BASE_TWIST
        if valid:
            h, p = intent.header, intent.payload
            valid = (not self.halted and h.device_id == self._device_id and h.source == 'learned_policy'
                     and h.priority_class is PriorityClass.POLICY and h.envelope_ref == 'isaac-map-v1'
                     and h.state_sequence == self.epoch and h.valid_for_s <= .1
                     and dict(h.limits) == {'linear_mps': .06, 'angular_radps': .8}
                     and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in (observed_at, now))
                     and 0 <= now - observed_at <= .1 and h.is_valid_at(now)
                     and abs(p.linear_mps) <= .06 and abs(p.angular_radps) <= .8)
        if not valid:
            self.stop()
            return ZERO
        self.pending = (intent, observed_at)
        self.command.set_nav_twist(Twist(p.linear_mps, p.angular_radps), now=now,
                                   preserve_curvature=preserve_curvature)
        return self.select_output(now=now)

    def select_output(self, now=None):
        from core_features.command.manager import ZERO
        now = time.monotonic() if now is None else now
        if self.pending is None or self.halted:
            return ZERO
        intent, observed_at = self.pending
        if (type(now) not in (int, float) or not math.isfinite(now) or now < 0 or not intent.header.is_valid_at(now)
                or not 0 <= now - observed_at <= .1 or intent.header.state_sequence != self.epoch):
            self.stop()
            return ZERO
        return self.command.select_output(now=now)

    def announce_pending(self):
        self.command.announce_pending()
