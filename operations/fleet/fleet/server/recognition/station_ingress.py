"""Scoped camera facts reach CORE through Fleet's existing robot credential only."""
import asyncio
import hashlib
import hmac
import math

from pydantic import Field

from core_common.protocol.station_charging import (
    Contract, Identifier, Positive, StationObservation, StationPoseRecord, StationTargetStatus,
)

ACTIVE = ('RETURN_RESERVED', 'RETURNING', 'DOCKING', 'CHARGE_CONFIRMING', 'CHARGING', 'CHARGED_HOLD', 'UNDOCKING')


class StationSource(Contract):
    source_id: Identifier
    token: str = Field(min_length=16, repr=False)
    station_id: Identifier
    robot_ids: tuple[Identifier, ...] = Field(min_length=1)
    map_id: Identifier
    map_revision: Identifier
    source_epoch: Identifier
    calibration_revision: Identifier
    max_age_s: Positive
    max_uncertainty_m: Positive
    max_uncertainty_rad: Positive


class StationIngress:
    def __init__(self, *, stations, sessions, sources, clients, clock):
        self.stations, self.sessions, self.clients, self.clock = stations, sessions, clients, clock
        self.sources = tuple(StationSource.model_validate(source.model_dump()) for source in sources)
        if (len({s.source_id for s in self.sources}) != len(self.sources)
                or len({s.token for s in self.sources}) != len(self.sources)):
            raise ValueError('STATION_SOURCE_CREDENTIAL_CONFLICT')
        self._locks, self._last = {}, {}

    def assert_isolated(self, console, console_token, principals):
        for source in self.sources:
            if any(robot not in console.robot_ids for robot in source.robot_ids):
                raise ValueError('STATION_SOURCE_ROBOT_NOT_REGISTERED')
            digest = hashlib.sha256(source.token.encode()).hexdigest()
            if (source.token == console_token or console.uses_rest_token(source.token)
                    or console.uses_agent_pairing_token(source.token)
                    or any(hmac.compare_digest(digest, value) for value in principals)):
                raise ValueError('STATION_SOURCE_CREDENTIAL_CONFLICT')

    def authenticate(self, authorization):
        if not isinstance(authorization, str) or not authorization.startswith('Bearer '):
            raise PermissionError('STATION_SOURCE_UNAUTHORIZED')
        digest = hashlib.sha256(authorization[7:].encode()).digest()
        source = next((s for s in self.sources if hmac.compare_digest(
            hashlib.sha256(s.token.encode()).digest(), digest)), None)
        if source is None:
            raise PermissionError('STATION_SOURCE_UNAUTHORIZED')
        return source

    def _source_evidence(self, source, evidence):
        for key in ('source_id', 'station_id', 'map_id', 'map_revision', 'source_epoch', 'calibration_revision'):
            if getattr(evidence, key) != getattr(source, key):
                raise ValueError('STATION_SOURCE_SCOPE_MISMATCH')
        now = self.clock()
        type(evidence).model_validate(evidence.model_dump(), context={'now': now})
        if (now-evidence.captured_at > source.max_age_s
                or evidence.uncertainty_m > source.max_uncertainty_m
                or evidence.uncertainty_rad > source.max_uncertainty_rad):
            raise ValueError('STATION_SOURCE_EVIDENCE_UNUSABLE')

    def _current(self, source, body):
        self._source_evidence(source, body)
        current = self.sessions.admitted_session(body.session_id, states=ACTIVE)
        if (current is None or body.robot_id not in source.robot_ids
                or any(getattr(body, key) != getattr(current, key) for key in (
                    'robot_id', 'station_id', 'session_id', 'boot_id', 'map_id', 'map_revision', 'pose_revision'))):
            raise ValueError('STATION_SESSION_NOT_CURRENT')
        target = next((p for p in self.stations.installations() if p.station_id == body.station_id), None)
        if target is None or target.status != 'VALID' or target.pose_revision != body.pose_revision:
            raise ValueError('STATION_POSITION_NOT_VERIFIED')

    async def observation(self, authorization, body: StationObservation):
        source = self.authenticate(authorization)
        if body.robot_id not in source.robot_ids:
            raise ValueError('STATION_SOURCE_SCOPE_MISMATCH')
        async with self._locks.setdefault(body.robot_id, asyncio.Lock()):
            key = (body.session_id, body.boot_id, body.source_id, body.source_epoch)
            previous = self._last.get(body.robot_id)
            if previous is not None and previous[0] == key and (
                    body.sequence <= previous[1] or body.captured_at < previous[2]):
                return {'accepted': False}
            client = self.clients().get(body.robot_id)
            if client is None:
                raise ValueError('STATION_ROBOT_UNAVAILABLE')
            async def forward():
                # This atomic read is fact admission's linearization point. Never put
                # database/registry locks on Fleet's event loop or hold them over HTTP.
                await asyncio.to_thread(self._current, source, body)
                self._source_evidence(source, body)  # Recheck time after a contended read.
                self._last[body.robot_id] = key, body.sequence, body.captured_at
                return await client.station_observation(body)
            result = await asyncio.wait_for(forward(), timeout=1.5)
            if type(result.get('accepted')) is not bool:
                raise ValueError('STATION_CORE_REPLY_UNUSABLE')
            return {'accepted': result['accepted']}

    async def pose(self, authorization, body: StationPoseRecord):
        source = self.authenticate(authorization)
        self._source_evidence(source, body)
        body = body.model_copy(update={'valid_until': min(body.valid_until, body.captured_at+source.max_age_s)})
        result = await asyncio.to_thread(self.stations.observe, body)
        return {'accepted': result is not None, 'station': result.model_dump(mode='json') if result else None}

    def _active_session(self, source, robot_id):
        candidates = [row for row in self.sessions.list() if row.robot_id == robot_id
                      and row.station_id == source.station_id and row.state in ACTIVE]
        admitted = [self.sessions.admitted_session(row.session_id, states=ACTIVE) for row in candidates]
        admitted = [row for row in admitted if row is not None]
        return admitted[0] if len(admitted) == 1 else None

    async def observation_scope(self, authorization, robot_id):
        source = self.authenticate(authorization)
        if robot_id not in source.robot_ids:
            raise PermissionError('STATION_SOURCE_UNAUTHORIZED')
        return {'scope': await asyncio.wait_for(self._read_scope(source, robot_id), timeout=1.5)}

    async def _read_scope(self, source, robot_id):
        current = await asyncio.to_thread(self._active_session, source, robot_id)
        client = self.clients().get(robot_id)
        if current is None or client is None:
            return None
        try:
            live = await client.station_target()
            live = StationTargetStatus.model_validate(live.model_dump(), context={
                'now': self.clock(), 'session_id': current.session_id, 'boot_id': current.boot_id})
            if not live.binding_valid or live.ack.robot_id != robot_id:
                return None
            if any(getattr(live.target, key) != getattr(current, key) for key in (
                    'station_id', 'map_id', 'map_revision', 'pose_revision')):
                return None
            state = await client.state()
            odom = state.get('odom_pose') or {}
            epoch, stamp, now = odom.get('epoch'), odom.get('stamp'), self.clock()
            if (state.get('robot_id') != robot_id or state.get('map_id') != current.map_id
                    or type(epoch) is not int or epoch < 0
                    or isinstance(stamp, bool) or not isinstance(stamp, (float, int))
                    or not math.isfinite(stamp) or not stamp <= now < stamp+source.max_age_s):
                return None
            scope = StationObservation(**{key: getattr(current, key) for key in (
                'robot_id', 'station_id', 'session_id', 'boot_id', 'map_id', 'map_revision', 'pose_revision')},
                odom_epoch=str(epoch), source_id=source.source_id, source_epoch=source.source_epoch,
                calibration_revision=source.calibration_revision, sequence=0, frame='base_link', pose=None,
                visible=False, uncertainty_m=source.max_uncertainty_m, uncertainty_rad=source.max_uncertainty_rad,
                # This is permission to MEASURE a new frame, not a renewal of
                # previous seating/charge evidence. Its lifetime must not feed
                # the old camera deadline back into every subsequent frame.
                captured_at=now, valid_until=min(live.ack.valid_until, live.target.valid_until,
                    stamp+source.max_age_s, now+source.max_age_s))
            await asyncio.to_thread(self._current, source, scope)
            self._source_evidence(source, scope)
            return scope.model_dump(mode='json')
        except (ValueError, TypeError, KeyError, AttributeError):
            return None
