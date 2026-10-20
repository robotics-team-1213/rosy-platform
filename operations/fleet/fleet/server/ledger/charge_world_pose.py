"""Native boot receipts qualify the shared REST read and existing World pose only."""
import asyncio
from dataclasses import dataclass
import math
import re

from core_common.protocol.station_charging import Pose2D, TimedEvidence
from rosy.world.state.projections.map_pose import odom_from_snapshot


@dataclass(frozen=True, eq=False)
class ChargePoseProof:
    robot_id: str
    boot_id: str
    odom_epoch: str
    map_id: str
    map_revision: str
    pose: Pose2D
    odom_stamp: float
    anchor_stamp: float
    valid_until: float
    scope: object
    deadline_mono: float
    facts_key: tuple


class ChargeWorldPoseSource:
    def __init__(self, *, robot_id, poses, clients, active_scope, clock, monotonic, max_age_s):
        if (not robot_id or type(max_age_s) not in (int, float)
                or not math.isfinite(max_age_s) or max_age_s <= 0):
            raise ValueError('CHARGE_WORLD_POSE_PROFILE_REQUIRED')
        self.robot_id, self.poses, self.clients, self.active_scope = robot_id, poses, clients, active_scope
        self.clock, self.monotonic, self.max_age_s = clock, monotonic, max_age_s
        self._lock, self._scope, self._issued = asyncio.Lock(), None, None
        self._first, self._clock_fault, self._times = True, False, None
        self._leases = {}
        self._has_odom = False
        self._map_scope = None

    def _time(self):
        before, utc, after = self.monotonic(), self.clock(), self.monotonic()
        if (self._clock_fault or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
                for v in (before, utc, after)) or after < before
                or self._times is not None and (utc < self._times[0] or before < self._times[1])):
            self._clock_fault = True
            raise ValueError('invalid pose source clock')
        self._times = (utc, after)
        return utc, after, before

    def _facts(self, facts, now):
        keys = ('robot_id', 'boot_id', 'odom_epoch', 'map_id', 'map_revision', 'captured_at', 'valid_until')
        identity = tuple(facts[k] for k in keys)
        if (facts['robot_id'] != self.robot_id or any(not isinstance(facts[k], str) or not facts[k]
                for k in keys[:5]) or re.fullmatch(r'0|[1-9][0-9]*', facts['odom_epoch']) is None
                or tuple(self.active_scope()) != (facts['map_id'], facts['map_revision'])):
            raise ValueError('pose facts scope changed')
        TimedEvidence.model_validate(
            {'captured_at': facts['captured_at'], 'valid_until': facts['valid_until']}, context={'now': now})
        if now-facts['captured_at'] > self.max_age_s:
            raise ValueError('pose facts expired')
        return identity

    def _client(self, client):
        if (client is None or self.clients().get(self.robot_id) is not client
                or client.robot_id != self.robot_id):
            raise ValueError('pose client changed')

    @staticmethod
    def _boot(body, expected):
        if body.get('owner', {}).get('boot_id') != expected:
            raise ValueError('native pose boot changed')

    def _lease(self, kind, generation, stamp, now, started):
        key = (generation, stamp)
        previous = self._leases.get(kind)
        if previous is None or previous[0] != key:
            previous = (key, started+max(0., stamp+self.max_age_s-now))
            self._leases[kind] = previous
        return previous[1]

    async def read(self, facts):
        async with self._lock:
            facts = dict(facts)
            self._issued = None
            try:
                now, _, started = self._time()
                identity = self._facts(facts, now)
                limit = min(facts['valid_until'], facts['captured_at']+self.max_age_s)
                deadline = started+(limit-now)
                previous = self._leases.get('facts')
                facts_identity = identity[:-1]  # A different exported TTL cannot renew this capture.
                if previous is not None:
                    if (facts_identity[-1] < previous[0][-1]
                            or facts_identity[-1] == previous[0][-1] and facts_identity != previous[0]):
                        raise ValueError('original pose facts regressed or changed scope')
                    if previous[0] == facts_identity:
                        deadline = min(deadline, previous[1])
                self._leases['facts'] = (facts_identity, deadline)
                client = self.clients().get(self.robot_id)
                self._client(client)
                self._boot(await client.docking_status(), facts['boot_id'])
                self._client(client)
                previous_scope = self._scope
                map_scope = (facts['map_id'], facts['map_revision'])
                if self._scope is not None and self._map_scope != map_scope:
                    self.poses.retire_source_scope(self._scope)
                self._map_scope = map_scope
                self._scope = self.poses.begin_source_scope(self.robot_id,
                    boot_id=facts['boot_id'], odom_epoch=facts['odom_epoch'], client=client)
                if self._first:
                    self.poses.retire_source_scope(self._scope)
                    self._scope = self.poses.begin_source_scope(self.robot_id,
                        boot_id=facts['boot_id'], odom_epoch=facts['odom_epoch'], client=client)
                    self._first = False
                if self._scope is not previous_scope:
                    self._has_odom = False
                receipt = await self.poses.state_with_source(self.robot_id,
                    after=self.poses.read_number(self.robot_id))
                if receipt.client is not client or receipt.generation != self._scope.generation:
                    raise ValueError('shared pose transport changed')
                self._boot(await client.docking_status(), facts['boot_id'])
                now, mono, _ = self._time()
                self._client(client)
                if identity != self._facts(facts, now) or mono >= deadline:
                    raise ValueError('pose facts changed during read')
                state = receipt.state
                sample = odom_from_snapshot(state)
                if (not self._has_odom and sample is not None and state.get('robot_id') == self.robot_id
                        and state.get('map_id') == facts['map_id'] and sample.epoch is not None
                        and str(sample.epoch) == facts['odom_epoch']
                        and sample.stamp <= self._scope.not_before and 0 <= now-sample.stamp <= self.max_age_s):
                    return None  # The first post-boundary odometry sample has not arrived yet.
                if not self.poses.observe_qualified_state(self._scope, state):
                    raise ValueError('original CORE odometry unverified')
                self._has_odom = True
                pose = self.poses.qualified_pose(self._scope)
                if pose is None:
                    return None  # A new accepted camera anchor is still required.
                anchor = self.poses.odom_to_map(self.robot_id)
                now, mono, _ = self._time()
                limit = min(limit, pose.odom_stamp+self.max_age_s, anchor[2]+self.max_age_s)
                deadline = min(deadline,
                    self._lease('odom', self._scope.generation, pose.odom_stamp, now, started),
                    self._lease('anchor', self._scope.generation, anchor[2], now, started))
                if mono >= deadline or now >= limit:
                    raise ValueError('original pose evidence expired')
                proof = ChargePoseProof(self.robot_id, facts['boot_id'], facts['odom_epoch'],
                    facts['map_id'], facts['map_revision'], Pose2D(x=pose.x, y=pose.y, yaw=pose.yaw),
                    pose.odom_stamp, anchor[2], min(limit, now+deadline-mono), self._scope, deadline, identity)
                self._issued = proof
                if not self.current(proof, facts):
                    raise ValueError('pose changed before use')
                return proof
            except Exception:
                self._issued = None
                if self._scope is not None:
                    self.poses.retire_source_scope(self._scope)
                raise ValueError('CHARGE_WORLD_POSE_UNAVAILABLE') from None

    def current(self, proof, facts):
        try:
            if proof is not self._issued or proof is None:
                return False
            now, mono, _ = self._time()
            if self._facts(facts, now) != proof.facts_key:
                return self._reject()
            self._client(proof.scope.client)
            pose = self.poses.qualified_pose(proof.scope)
            anchor = self.poses.odom_to_map(self.robot_id)
            if (pose is None or anchor is None or anchor[2] != proof.anchor_stamp
                    or pose.odom_stamp != proof.odom_stamp
                    or (pose.x, pose.y, pose.yaw) != (proof.pose.x, proof.pose.y, proof.pose.yaw)):
                return self._reject()
            now, mono, _ = self._time()
            self._client(proof.scope.client)
            if (self._facts(facts, now) != proof.facts_key
                    or now >= proof.valid_until or mono >= proof.deadline_mono):
                return self._reject()
            return True
        except Exception:
            return self._reject()

    def _reject(self):
        self._issued = None
        if self._scope is not None:
            self.poses.retire_source_scope(self._scope)
        return False
