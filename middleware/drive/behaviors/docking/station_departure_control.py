"""Scoped straight departure over the existing native docking writer.

The station owner holds its lock for mutations. The final publisher calls only
ready(), which reads immutable local cache snapshots without waiting.
"""
import math
from uuid import UUID

from core_common.protocol.station_charging import StationDeparturePermit, StationDepartureReceipt


class StationDepartureController:
    def __init__(self, owner, *, feed):
        self.owner, self.feed = owner, feed
        self.permit = self.receipt = self.operation_id = None
        self.started = self.deadline = self.origin = self.stop_after = None
        self.since = self.last_motion = self.terminal_generation = None
        self.admitted_generation = None
        self.receipt_started = self.receipt_deadline = None
        self.receipt_lost = False
        self.lost = False

    def _sample(self):
        owner, profile = self.owner, self.feed.profile
        view = self.feed.snapshot_with_deadline_nowait()
        if view is None:
            raise ValueError('STATION_DEPARTURE_MEASUREMENT_REQUIRED')
        sample, lifetime = view
        scope = owner._scope(owner.session, sample.odom_epoch, nowait=True)
        if (sample.odom_epoch != owner.feed.scope.odom_epoch
                or any(getattr(sample, key) != getattr(owner.session, key) for key in (
                    'robot_id', 'station_id', 'session_id', 'attempt_id', 'boot_id', 'battery_id',
                    'map_id', 'map_revision', 'pose_revision'))):
            raise ValueError('STATION_DEPARTURE_SCOPE_CHANGED')
        if (sample.output_enabled is not False or sample.charging is not False or sample.faults
                or abs(sample.current_a) > profile.max_current_a or sample.sweep_verified is not True):
            raise ValueError('STATION_DEPARTURE_ISOLATION_OR_SPACE_REQUIRED')
        progress = 0.
        if self.origin is not None:
            x, y, yaw = self.origin
            dx, dy = sample.pose.x-x, sample.pose.y-y
            progress = -(dx*math.cos(yaw)+dy*math.sin(yaw))
            lateral = -dx*math.sin(yaw)+dy*math.cos(yaw)
            heading = math.atan2(math.sin(sample.pose.yaw-yaw), math.cos(sample.pose.yaw-yaw))
            if (progress < -profile.max_overshoot_m or progress > profile.reverse_distance_m+profile.max_overshoot_m
                    or abs(lateral) > profile.max_lateral_m or abs(heading) > profile.max_heading_rad
                    or abs(sample.measured_linear_m_s) > profile.reverse_speed_m_s
                    or abs(sample.measured_angular_rad_s) > owner.profile.angular_limit_rad_s):
                raise ValueError('STATION_DEPARTURE_PATH_LIMIT')
        if sample.rear_clearance_m < max(0., profile.reverse_distance_m-progress)+profile.rear_margin_m:
            raise ValueError('STATION_DEPARTURE_REAR_SPACE_REQUIRED')
        self._source_live(sample, lifetime, owner.source_clock(), owner.clock())
        return sample, scope, lifetime

    def _source_live(self, sample, lifetime, utc, mono):
        try:
            type(sample).model_validate(sample.model_dump(), context={'now': utc})
            if (type(mono) not in (int, float) or not math.isfinite(mono)
                    or not lifetime[0] <= mono < lifetime[1]):
                raise ValueError('STATION_DEPARTURE_SOURCE_LIFETIME_LOST')
        except (TypeError, ValueError):
            self.lost = self.receipt_lost = True  # Observed clock recovery cannot revive this authority.
            raise

    def _permission_time(self):
        if self.permit is None or self.lost:
            raise ValueError('STATION_DEPARTURE_PERMISSION_REQUIRED')
        utc, mono = self.owner.source_clock(), self.owner.clock()
        if (any(type(value) not in (int, float) or not math.isfinite(value) for value in (utc, mono))
                or not self.started <= mono < self.deadline
                or not self.permit.captured_at <= utc < self.permit.valid_until):
            self.lost = True
            raise ValueError('STATION_DEPARTURE_PERMISSION_EXPIRED')
        return utc, mono

    def _live(self):
        self._permission_time()
        self.owner._valid(nowait=True)
        operation = self.owner.docking.capture_native_operation(self.operation_id)
        native = self.owner.docking.native_owner(wait=False)
        if (operation is None or native is None or str(operation.boot_id) != self.permit.boot_id
                or operation.run_id != self.operation_id or operation.kind != 'undock'
                or operation.correlation_id != self.permit.correlation_id
                or native['owner_run_id'] not in (None, str(self.operation_id))
                or native['owner_generation'] != self.admitted_generation+(operation.phase == 'TERMINAL')
                or self.terminal_generation is not None
                and native['owner_generation'] != self.terminal_generation):
            self.lost = True
            raise ValueError('STATION_DEPARTURE_NATIVE_OWNER_CHANGED')
        sample, scope, lifetime = self._sample()
        utc, mono = self._permission_time()
        self._source_live(sample, lifetime, utc, mono)
        return operation, (sample, scope, lifetime)

    def start(self, permit):
        owner, profile = self.owner, self.feed.profile
        if self.permit is not None or owner.state != 'CHARGED_HOLD' or not owner.readback().completion_verified:
            raise ValueError('STATION_DEPARTURE_COMPLETION_REQUIRED')
        permit = StationDeparturePermit.model_validate(permit.model_dump(), context={
            key: getattr(owner.session, key) for key in (
                'robot_id', 'station_id', 'session_id', 'attempt_id', 'boot_id', 'battery_id',
                'map_id', 'map_revision', 'pose_revision')} | {'now': owner.source_clock()})
        sample, local, _ = self._sample()
        limits = owner.docking.departure_limits()
        if (limits != (profile.reverse_distance_m, profile.reverse_speed_m_s, 0.)
                or local['mode'] != 'IDLE' or sample.load_present is not True
                or abs(sample.measured_linear_m_s) > owner.profile.linear_limit_m_s
                or abs(sample.measured_angular_rad_s) > owner.profile.angular_limit_rad_s):
            raise ValueError('STATION_DEPARTURE_PROFILE_OR_STANDSTILL_REQUIRED')
        owner._starting = ('undock', owner.session.station_id, permit.correlation_id,
                           owner.session.session_id, owner.session.attempt_id)
        try:
            def admitted(operation):
                self.permit, self.operation_id = permit, operation.run_id
                self.admitted_generation = owner.docking.native_owner()['owner_generation']
                owner._operation_id, owner._correlation_id = operation.run_id, permit.correlation_id
                self.started = owner.clock()
                self.deadline = self.started+permit.valid_until-owner.source_clock()
                self.origin = (sample.pose.x, sample.pose.y, sample.pose.yaw)
            owner.docking.undock(correlation_id=permit.correlation_id, expected_boot_id=UUID(permit.boot_id),
                expected_owner_generation=permit.expected_owner_generation, receipt_sink=admitted)
            owner._seated_until = owner._charge_until = None
            owner.state, owner.reason = 'UNDOCKING', None
            return owner.docking.capture_native_operation(self.operation_id)
        except Exception:
            if self.operation_id is not None:
                owner.invalidate('STATION_DEPARTURE_START_REQUIRES_RECONCILIATION')
            raise
        finally:
            owner._starting = None

    def ready(self, mode):
        try:
            operation, _ = self._live()
            return mode == 'DOCKING' and self.owner.state == 'UNDOCKING' and operation.phase != 'TERMINAL'
        except Exception:
            return False

    def renew(self, permit):
        owner = self.owner
        def renew():
            self._live()  # An expired or replaced run cannot be revived by a new permission.
            permit_checked = StationDeparturePermit.model_validate(permit.model_dump(),
                context={'now': owner.source_clock()})
            exclude = {'captured_at', 'valid_until', 'expected_owner_generation'}
            if permit_checked.model_dump(exclude=exclude) != self.permit.model_dump(exclude=exclude):
                raise ValueError('STATION_DEPARTURE_PERMISSION_SCOPE_CHANGED')
            if permit_checked == self.permit:
                return
            if permit_checked.captured_at <= self.permit.captured_at:
                raise ValueError('STATION_DEPARTURE_PERMISSION_REPLAY')
            started = owner.clock()
            deadline = started+permit_checked.valid_until-owner.source_clock()
            self.permit, self.started, self.deadline = permit_checked, started, deadline
        return owner.docking.bind_station(renew, expected_boot_id=UUID(permit.boot_id),
            expected_owner_generation=permit.expected_owner_generation)

    def tick(self):
        operation, (sample, local, _) = self._live()
        if self.owner.state == 'UNDOCKING':
            self.owner.docking.tick()
            operation = self.owner.docking.capture_native_operation(self.operation_id)
            if operation is None:
                raise ValueError('STATION_DEPARTURE_NATIVE_OWNER_CHANGED')
            if operation.phase == 'TERMINAL':
                if operation.result != 'SUCCEEDED':
                    raise ValueError('STATION_DEPARTURE_FAILED')
                self.stop_after = self.owner.source_clock()
                self.terminal_generation = self.owner.docking.native_owner()['owner_generation']
                self.owner.state = 'DEPARTURE_CHECK'
                return
        if self.owner.state == 'DEPARTURE_CHECK':
            still = (local['mode'] == 'IDLE' and sample.motion_sample_at > self.stop_after
                and abs(sample.measured_linear_m_s) <= self.owner.profile.linear_limit_m_s
                and abs(sample.measured_angular_rad_s) <= self.owner.profile.angular_limit_rad_s
                and sample.load_present is False
                and sample.contact_sample_at > self.stop_after)
            if not still or self.last_motion is not None and (
                    sample.motion_sample_at < self.last_motion
                    or sample.motion_sample_at-self.last_motion > self.feed.profile.max_age_s):
                self.since = self.last_motion = None
            if still:
                self.since = sample.motion_sample_at if self.since is None else self.since
                self.last_motion = sample.motion_sample_at

    def _require_receipt_live(self):
        utc, mono = self.owner.source_clock(), self.owner.clock()
        if (self.receipt_lost or any(type(value) not in (int, float) or not math.isfinite(value)
                                   for value in (utc, mono))
                or not self.receipt_started <= mono < self.receipt_deadline
                or not self.receipt.captured_at <= utc < self.receipt.valid_until):
            self.receipt_lost = True
            raise ValueError('STATION_DEPARTURE_RECEIPT_EXPIRED')
        return utc, mono

    def _receipt_snapshot(self):
        try:
            self._require_receipt_live()
            sample, local, lifetime = self._sample()
            native = self.owner.docking.native_owner(wait=False)
            if (native is None or native['boot_id'] != self.receipt.boot_id
                    or native['owner_generation'] != self.receipt.owner_generation
                    or native['owner_run_id'] is not None or local['mode'] != 'IDLE'
                    or sample.load_present is not False
                    or abs(sample.measured_linear_m_s) > self.owner.profile.linear_limit_m_s
                    or abs(sample.measured_angular_rad_s) > self.owner.profile.angular_limit_rad_s
                    or sample.motion_sample_at < self.receipt.motion_sample_at
                    or sample.contact_sample_at < self.receipt.contact_sample_at):
                raise ValueError('STATION_DEPARTURE_RECEIPT_CONTRADICTED')
            utc, mono = self._require_receipt_live()
            self._source_live(sample, lifetime, utc, mono)
            return sample, local, lifetime
        except Exception:
            self.receipt_lost = True
            raise

    def status_fields(self):
        """Permission/readback only; never tick a native writer or renew a measurement."""
        try:
            if self.receipt is not None and self.owner.state == 'WORK_AVAILABLE':
                sample, _, lifetime = self._receipt_snapshot()
                utc, mono = self._require_receipt_live()
                self._source_live(sample, lifetime, utc, mono)
                expiry = min(self.receipt.valid_until, sample.valid_until,
                    utc+min(self.receipt_deadline, lifetime[1])-mono)
                proof = self.receipt.model_copy(update={'valid_until': expiry})
                return {'departure_receipt': proof}, expiry
            if self.owner.state in ('UNDOCKING', 'DEPARTURE_CHECK'):
                _, (sample, _, lifetime) = self._live()
                utc, mono = self._permission_time()
                self._source_live(sample, lifetime, utc, mono)
                expiry = min(self.permit.valid_until, sample.valid_until, utc+min(self.deadline, lifetime[1])-mono)
                permission = self.permit.model_copy(update={'valid_until': expiry})
                return {'departure_permit': permission}, expiry
        except Exception:
            if self.receipt is not None:
                self.receipt_lost = True
        return {}, None

    def finish(self, command):
        owner = self.owner
        if (self.permit is None or command.session_id != self.permit.session_id
                or command.expected_boot_id != self.permit.boot_id
                or command.correlation_id != self.permit.correlation_id):
            raise ValueError('STATION_DEPARTURE_COMMAND_SCOPE_CHANGED')
        def finish():
            proof_mono = owner.clock()
            if self.receipt is not None:
                self._receipt_snapshot()
                return self.receipt
            self.tick()
            if (owner.state != 'DEPARTURE_CHECK' or self.since is None
                    or self.last_motion-self.since < owner.profile.still_s):
                raise ValueError('STATION_DEPARTURE_STANDSTILL_REQUIRED')
            sample, local, lifetime = self._sample()
            if (sample.motion_sample_at != self.last_motion or sample.load_present is not False
                    or sample.contact_sample_at <= self.stop_after or local['mode'] != 'IDLE'
                    or abs(sample.measured_linear_m_s) > owner.profile.linear_limit_m_s
                    or abs(sample.measured_angular_rad_s) > owner.profile.angular_limit_rad_s):
                raise ValueError('STATION_DEPARTURE_FINAL_SAMPLE_CHANGED')
            x, y, yaw = self.origin
            reverse = -((sample.pose.x-x)*math.cos(yaw)+(sample.pose.y-y)*math.sin(yaw))
            if reverse < self.feed.profile.reverse_distance_m-self.feed.profile.max_overshoot_m:
                raise ValueError('STATION_DEPARTURE_DISTANCE_UNVERIFIED')
            expiry = min(sample.valid_until, self.permit.valid_until,
                owner.source_clock()+min(self.deadline, lifetime[1])-owner.clock(),
                *(getattr(sample, key)+self.feed.profile.max_age_s for key in (
                    'motion_sample_at', 'space_sample_at', 'power_sample_at', 'current_sample_at', 'contact_sample_at')))
            body = self.permit.model_dump(exclude={'captured_at', 'valid_until', 'expected_owner_generation',
                'policy_profile_revision', 'capacity_revision'})
            captured = owner.source_clock()
            receipt = StationDepartureReceipt(**body, captured_at=captured, valid_until=expiry,
                operation_id=str(self.operation_id), owner_generation=self.terminal_generation,
                odom_epoch=local['odom_epoch'], departure_profile_revision=self.feed.profile.revision,
                source_id=sample.source_id, source_epoch=sample.source_epoch, stopped_since=self.since,
                motion_sample_at=sample.motion_sample_at, contact_sample_at=sample.contact_sample_at,
                space_sample_at=sample.space_sample_at,
                isolation_sample_at=min(sample.power_sample_at, sample.current_sample_at),
                contact_released=True, power_isolated=True, route_clear=True, stopped=True)
            self.receipt_started = proof_mono
            self.receipt_deadline = min(self.deadline, lifetime[1], self.receipt_started+expiry-captured)
            self.receipt = receipt
            self._require_receipt_live()
            owner.state, owner.reason = 'WORK_AVAILABLE', None
            return self.receipt
        return owner.docking.bind_station(finish, expected_boot_id=UUID(command.expected_boot_id),
            expected_owner_generation=command.expected_owner_generation)
