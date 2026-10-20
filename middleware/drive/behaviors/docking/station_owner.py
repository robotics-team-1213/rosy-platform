"""Local station session layered over DockingManager; never publishes a motor command."""
from __future__ import annotations

import math
import threading
from uuid import UUID

from core_common.protocol.schemas import DockState
from core_common.protocol.station_charging import (
    Contract, Identifier, Positive, ChargeSessionStatus, StationPoseRecord, StationPoseAck,
    StationObservation, SeatingEvidence, ChargeCompletionEvidence, StationReturnPermit,
)
from .agent import DockStatus
from .database import DockError
from .charging import ChargingConfirmation
from .completion import SeatingGate, ChargeCompletionTracker
from .parking import compose, robot_in_dock_frame
from .station_feed import StationObservationFeed
from .station_return import StationReturnAuthority
from .station_readback import station_readback
from .station_rebind import StationRebindBoundary
from .station_departure_control import StationDepartureController


class StationControlProfile(Contract):
    """Installed measured limits; test profiles do not establish device acceptance."""
    station_id: Identifier
    battery_id: Identifier
    source_id: Identifier
    source_epoch: Identifier
    calibration_revision: Identifier
    marker_offset_m: Positive
    max_age_s: Positive
    max_uncertainty_m: Positive
    max_uncertainty_rad: Positive
    position_tolerance_m: Positive
    heading_tolerance_rad: Positive
    linear_limit_m_s: Positive
    angular_limit_rad_s: Positive
    still_s: Positive
    debounce_s: Positive
    sample_max_age_s: Positive
    min_full_voltage_v: Positive
    max_voltage_v: Positive
    pack_max_age_s: Positive
    charge_confirm_s: Positive


class StationDockingOwner:
    def __init__(self, docking, *, profile, local_scope, local_scope_nowait, clock, source_clock, battery):
        self.docking, self.profile, self.local_scope = docking, profile, local_scope
        self.local_scope_nowait = local_scope_nowait
        self.clock, self.source_clock, self.battery = clock, source_clock, battery
        self.session = self.target = self.feed = None
        self.sensors = None
        self.motion_feed = None
        self.return_authority = None
        self.departure = None  # Explicit installed local profile/feed; absent disables departure.
        self._return_finished = False
        self.return_lease_probe = lambda **kwargs: False
        self.return_idle = lambda: False  # CORE composes the actual locked navigation owner.
        self.state, self.reason = 'UNBOUND', None
        self._operation_id, self._seated_until = None, None
        self._last_observed = None
        self._starting = None
        self.principal_id = self._correlation_id = None
        self._lock = threading.RLock()
        self.rebind_boundary = StationRebindBoundary(self)

    def _scope(self, session, odom_epoch=None, *, nowait=False):
        local = self.local_scope_nowait() if nowait else self.local_scope()
        if local is None:
            raise ValueError('STATION_LOCAL_SCOPE_BUSY')
        expected = {k: getattr(session, k) for k in (
            'robot_id', 'boot_id', 'battery_id', 'map_id', 'map_revision')}
        if (any(local.get(k) != v for k, v in expected.items())
                or not local.get('odom_epoch') or local.get('odom_fresh') is not True
                or odom_epoch is not None and local.get('odom_epoch') != odom_epoch):
            raise ValueError('STATION_LOCAL_SCOPE_CHANGED')
        if local.get('safety_latched') is not False or local.get('mode') in ('MANUAL', 'EMERGENCY'):
            raise ValueError('STATION_LOCAL_STOP_OR_MANUAL')
        return local

    def _valid(self, *, nowait=False):
        if self.session is None or self.state == 'HOLD':
            raise ValueError('STATION_BINDING_REQUIRED')
        self._scope(self.session, self.feed.scope.odom_epoch, nowait=nowait)
        StationPoseRecord.model_validate(self.target.model_dump(), context={'now': self.source_clock()})

    def bind(self, session, target, observation_scope, *, principal_id=None,
             expected_boot_id=None, expected_owner_generation=None):
        with self._lock:
            self.require_principal(principal_id)
            if expected_boot_id is not None and expected_boot_id != session.boot_id:
                raise ValueError('STATION_BOOT_MISMATCH')
            result = self.docking.bind_station(
                lambda: self._bind(session, target, observation_scope),
                expected_boot_id=UUID(expected_boot_id or session.boot_id),
                expected_owner_generation=(self.docking.native_owner()['owner_generation']
                    if expected_owner_generation is None else expected_owner_generation))
            self.principal_id = principal_id
            return result

    def require_principal(self, principal_id):
        if self.principal_id is not None and principal_id != self.principal_id:
            raise ValueError('STATION_PRINCIPAL_MISMATCH')

    def _bind(self, session, target, observation_scope):
        with self._lock:
            session = ChargeSessionStatus.model_validate(session.model_dump())
            if session.session_id in self.rebind_boundary.retired:
                raise ValueError('STATION_SESSION_RETIRED')
            local = self._scope(session)
            target = StationPoseRecord.model_validate(target.model_dump(), context={
                'now': self.source_clock(), 'station_id': session.station_id,
                'map_id': session.map_id, 'map_revision': session.map_revision, 'pose_revision': session.pose_revision})
            profile = self.profile
            if (target.status != 'VALID' or session.station_id != profile.station_id
                    or session.battery_id != profile.battery_id):
                raise ValueError('STATION_PROFILE_SCOPE_MISMATCH')
            scope = StationObservation.model_validate(observation_scope.model_dump(), context={
                k: getattr(session, k) for k in ('robot_id', 'boot_id', 'station_id', 'session_id',
                                               'map_id', 'map_revision', 'pose_revision')} | {
                'now': self.source_clock(), 'odom_epoch': local['odom_epoch'], 'source_epoch': profile.source_epoch,
                'calibration_revision': profile.calibration_revision})
            if scope.source_id != profile.source_id:
                raise ValueError('STATION_SOURCE_SCOPE_MISMATCH')
            replacing = (self.session is not None and self.state == 'WORK_AVAILABLE'
                         and session.session_id != self.session.session_id)
            if replacing:
                self.rebind_boundary.require(session, scope)
            if self.session is not None and not replacing:
                refreshed = {'captured_at', 'valid_until', 'uncertainty_m', 'uncertainty_rad'}
                identity = ('session_id', 'attempt_id', 'robot_id', 'station_id', 'battery_id', 'boot_id',
                            'map_id', 'map_revision', 'pose_revision')
                if (any(getattr(session, k) != getattr(self.session, k) for k in identity)
                        or target.model_dump(exclude=refreshed) != self.target.model_dump(exclude=refreshed)
                        or self.state == 'HOLD'):
                    self.invalidate('STATION_RECONCILIATION_REQUIRED')
                    raise ValueError('STATION_RECONCILIATION_REQUIRED')
                self._valid()  # New evidence cannot revive an expired binding, even before tick.
                if target.captured_at < self.target.captured_at:
                    raise ValueError('STATION_TARGET_REFRESH_REVERSED')
                if target.captured_at == self.target.captured_at and target != self.target:
                    raise ValueError('STATION_TARGET_REFRESH_REPLAY')
                owner_run = self.docking.native_owner()['owner_run_id']
                if owner_run is not None and owner_run != str(self._operation_id):
                    raise ValueError('STATION_NATIVE_OWNER_CHANGED')
                self.target = target
                return self.ack()
            if self.docking.active or self.docking.state not in (DockState.UNDOCKED, DockState.DOCK_FAILED):
                raise ValueError('STATION_LOCAL_OWNER_ACTIVE')
            dock_type = self.docking.database.type_of(session.station_id)
            if (dock_type.detector != 'station_observation' or dock_type.approach != 'pose'
                    or dock_type.settle != 'pose' or dock_type.staging
                    or dock_type.tag_offset_m != profile.marker_offset_m
                    or dock_type.pose_tolerance_m > profile.position_tolerance_m
                    or dock_type.pose_tolerance_rad > profile.heading_tolerance_rad):
                raise ValueError('STATION_CONTROL_PROFILE_MISMATCH')
            feed = StationObservationFeed(scope, clock=self.clock, source_clock=self.source_clock,
                max_age_s=profile.max_age_s, max_uncertainty_m=profile.max_uncertainty_m,
                max_uncertainty_rad=profile.max_uncertainty_rad, marker_offset_m=profile.marker_offset_m)
            if replacing:
                self.rebind_boundary.require(session, scope)  # Recheck after all new contract/profile validation.
            seat_scope = {k: getattr(scope, k) for k in (
                'robot_id', 'station_id', 'session_id', 'boot_id', 'pose_revision', 'odom_epoch')}
            limits = profile.model_dump()
            self.seating = SeatingGate(scope=seat_scope, **{k: limits[k] for k in (
                'position_tolerance_m', 'heading_tolerance_rad', 'linear_limit_m_s', 'angular_limit_rad_s',
                'still_s', 'debounce_s', 'sample_max_age_s')})
            self.completion = ChargeCompletionTracker(session_started_at=self.source_clock(), scope={k: getattr(session, k) for k in (
                'robot_id', 'station_id', 'session_id', 'boot_id', 'battery_id')}, **{k: limits[k] for k in (
                'min_full_voltage_v', 'max_voltage_v', 'pack_max_age_s')})
            self.charging = ChargingConfirmation(clock=self.clock, window_s=profile.charge_confirm_s)
            self._charge_until = None
            dock = self.docking.database.teach(session.station_id, target.pose.x, target.pose.y,
                                                target.pose.yaw, target.map_id)
            feed.start(dock)
            if replacing:
                self.rebind_boundary.retire(self.session.session_id)
                self.departure = StationDepartureController(self, feed=self.departure.feed)
                self._operation_id = self._correlation_id = None
                self._seated_until = self._last_observed = self._starting = None
            self.session, self.target, self.feed, self.state = session, target, feed, 'BOUND'
            self.reason = None
            self.return_authority, self._return_finished = None, False
            try:
                if self.sensors is not None:
                    self.sensors.start(self, dock)
            except Exception:
                self.invalidate('STATION_SENSOR_START_FAILED')
                raise
            return self.ack()

    def ack(self):
        self._valid()
        now = self.source_clock()
        return StationPoseAck(**{k: getattr(self.session, k) for k in (
            'robot_id', 'station_id', 'session_id', 'boot_id', 'map_id', 'map_revision', 'pose_revision')},
            accepted=True, captured_at=now, valid_until=min(self.target.valid_until, now+self.profile.max_age_s))

    def detector(self):
        self._valid()
        return self.feed

    def ingest(self, observation, *, received_at, principal_id=None):
        with self._lock:
            self.require_principal(principal_id)
            if self.feed is None or self.state == 'HOLD':
                return False
            accepted = self.feed.ingest(observation, received_at=received_at)
            if accepted:
                self._last_observed = self.clock()
            return accepted

    def map_pose(self):
        self._valid()
        relative = self.feed.relative_pose()
        if relative is None:
            return None
        robot = robot_in_dock_frame(relative.x, relative.y, relative.yaw, self.profile.marker_offset_m)
        return compose((self.target.pose.x, self.target.pose.y, self.target.pose.yaw), robot)

    def start_docking(self, *, correlation_id, expected_boot_id=None,
                      expected_owner_generation=None, principal_id=None, session_id=None):
        with self._lock:
            self.require_principal(principal_id)
            self._valid()
            if session_id is not None and session_id != self.session.session_id:
                raise ValueError('STATION_SESSION_MISMATCH')
            if expected_boot_id is not None and expected_boot_id != self.session.boot_id:
                raise ValueError('STATION_BOOT_MISMATCH')
            if self.state != 'BOUND' or self.feed.relative_pose() is None:
                raise ValueError('STATION_OBSERVATION_REQUIRED')
            owner = self.docking.native_owner()
            self._starting = ('dock', self.session.station_id, correlation_id,
                              self.session.session_id, self.session.attempt_id)
            try:
                def admitted(operation):
                    self._operation_id = operation.run_id
                    self._correlation_id = correlation_id
                self.completion.reset(self.session.session_id, session_started_at=self.source_clock())
                self.docking.dock(self.session.station_id, correlation_id=correlation_id,
                                  expected_boot_id=UUID(self.session.boot_id),
                                  expected_owner_generation=(owner['owner_generation'] if expected_owner_generation is None
                                                             else expected_owner_generation), receipt_sink=admitted)
                self.state = 'DOCKING'
                return self.docking.capture_native_operation(self._operation_id)
            except Exception:
                self.invalidate('STATION_START_REQUIRES_RECONCILIATION')
                raise
            finally:
                self._starting = None

    def start_departure(self, permit, *, principal_id):
        with self._lock:
            self.require_principal(principal_id)
            self._valid()
            if self.departure is None:
                raise ValueError('STATION_DEPARTURE_PROFILE_REQUIRED')
            return self.departure.start(permit)

    def finish_departure(self, command, *, principal_id):
        with self._lock:
            self.require_principal(principal_id)
            if self.departure is None:
                raise ValueError('STATION_DEPARTURE_PROFILE_REQUIRED')
            return self.departure.finish(command)

    def renew_departure(self, permit, *, principal_id):
        with self._lock:
            self.require_principal(principal_id)
            if self.departure is None:
                raise ValueError('STATION_DEPARTURE_PROFILE_REQUIRED')
            if self.state not in ('UNDOCKING', 'DEPARTURE_CHECK'):
                raise ValueError('STATION_DEPARTURE_ACTIVE_RUN_REQUIRED')
            return self.departure.renew(permit)

    def _return_valid(self):
        authority = self.return_authority
        if authority is None:
            return False
        try:
            self._valid(nowait=True)
            StationReturnPermit.model_validate(authority.permit.model_dump(), context={
                k: getattr(self.target, k) for k in ('station_id', 'map_id', 'map_revision', 'pose_revision')})
            return authority.valid()
        except ValueError as exc:
            if str(exc) == 'STATION_LOCAL_SCOPE_BUSY':
                return False
            authority.lost = True
            return False
        except Exception:
            authority.lost = True
            return False

    def stop_docking(self, command, *, principal_id):
        """Close this intent even after evidence expires; never stop a replacement owner."""
        with self._lock:
            self.require_principal(principal_id)
            if (self.session is None or command.session_id != self.session.session_id
                    or command.expected_boot_id != self.session.boot_id):
                raise ValueError('STATION_SESSION_MISMATCH')
            def stop():
                operation = self.docking.native.lookup()
                pre_departure = (self.state == 'CHARGED_HOLD' and operation is not None
                    and operation.run_id == self._operation_id and operation.kind == 'dock'
                    and operation.phase == 'TERMINAL'
                    and self.docking.native_owner()['owner_run_id'] is None)
                if self._operation_id is None:
                    if (self.state not in ('BOUND', 'HOLD')
                            or self._correlation_id not in (None, command.correlation_id)
                            or self.docking.native_owner()['owner_run_id'] is not None):
                        raise ValueError('STATION_STOP_OWNER_CHANGED')
                elif not pre_departure and (operation is None or operation.run_id != self._operation_id
                        or operation.correlation_id != command.correlation_id
                        or self._correlation_id != command.correlation_id
                        or operation.kind != ('undock' if self.departure is not None
                            and self.departure.operation_id == self._operation_id else 'dock')):
                    raise ValueError('STATION_STOP_OWNER_CHANGED')
                self._correlation_id = command.correlation_id
                self.invalidate('STATION_FLEET_STOP')
            self.docking.bind_station(stop, expected_boot_id=UUID(command.expected_boot_id),
                                       expected_owner_generation=command.expected_owner_generation)

    def grant_return(self, permit, *, principal_id, owner_id):
        with self._lock:
            self.require_principal(principal_id)
            self._valid()
            permit = StationReturnPermit.model_validate(permit.model_dump(), context={
                k: getattr(self.session, k) for k in ('robot_id', 'station_id', 'battery_id', 'session_id',
                    'boot_id', 'map_id', 'map_revision', 'pose_revision')} | {'now': self.source_clock()})
            if self.state == 'RETURNING':
                if not self._return_valid() or self.return_authority.owner_id != owner_id:
                    raise ValueError('STATION_RETURN_AUTHORITY_LOST')
                self.return_authority.renew(permit)
                return
            if self.state != 'BOUND' or self._return_finished or self.local_scope().get('mode') != 'IDLE':
                raise ValueError('STATION_RETURN_BOUNDARY_REQUIRED')
            authority = StationReturnAuthority(permit, owner_id=owner_id, lease_probe=self.return_lease_probe,
                native_probe=lambda: self.docking.native_owner(wait=False), clock=self.clock,
                source_clock=self.source_clock, profile=self.profile)
            def admit():
                if not authority.valid():
                    raise ValueError('STATION_RETURN_LEASE_REQUIRED')
                self.return_authority, self.state = authority, 'RETURNING'
            self.docking.bind_station(admit, expected_boot_id=UUID(permit.boot_id),
                                       expected_owner_generation=permit.expected_owner_generation)

    def finish_return(self, command, *, principal_id):
        with self._lock:
            self.require_principal(principal_id)
            if (self.state != 'RETURNING' or not self._return_valid()
                    or command.session_id != self.session.session_id
                    or command.correlation_id != self.return_authority.permit.correlation_id
                    or command.expected_boot_id != self.session.boot_id):
                raise ValueError('STATION_RETURN_AUTHORITY_REQUIRED')
            local = self.local_scope()
            if local['mode'] == 'NAVIGATION':
                def park():
                    if not self._return_valid() or not self.return_idle():
                        raise ValueError('STATION_RETURN_NAVIGATION_UNVERIFIED')
                    self.return_authority.require_new_stop()
                self.docking.bind_station(park, expected_boot_id=UUID(command.expected_boot_id),
                                           expected_owner_generation=command.expected_owner_generation)
                # A successful IDLE transfer is still not measured standstill or return completion.
                raise ValueError('STATION_RETURN_STANDSTILL_REQUIRED')
            motion = self.motion_feed.snapshot() if self.motion_feed else None
            if not self.return_authority.observe_stop(motion, odom_epoch=local['odom_epoch'], idle=local['mode'] == 'IDLE'):
                raise ValueError('STATION_RETURN_STANDSTILL_REQUIRED')
            def finish():
                self._return_finished = True
                self.return_authority, self.state = None, 'BOUND'
            self.docking.bind_station(finish, expected_boot_id=UUID(command.expected_boot_id),
                                       expected_owner_generation=command.expected_owner_generation)
            return self.ack()

    def readback(self):
        with self._lock:
            return station_readback(self)

    def admit_motion(self, kind, dock, dock_type, correlation_id):
        # Called under manager lock. Never acquire owner lock here: owner start
        # and tick already use owner -> manager order.
        if dock_type is None or dock_type.detector != 'station_observation':
            if self.session is not None and self.state not in ('UNBOUND', 'WORK_AVAILABLE'):
                raise DockError('STATION_SESSION_ACTIVE', 'station session retains motion authority')
            return
        if (self.session is None or self._starting != (kind, dock.id, correlation_id,
                self.session.session_id, self.session.attempt_id) or not correlation_id):
            raise DockError('STATION_BINDING_REQUIRED', 'station motion requires its exact session intent')
        try:
            self._valid()
        except ValueError as exc:
            raise DockError('STATION_BINDING_INVALID', str(exc)) from exc
        self._starting = None

    def motion_ready(self, mode):
        # This callback runs at the final publisher: contention must stop, never
        # delay, a wheel command. No network/agent poll or cleanup in this path.
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if self.state == 'WORK_AVAILABLE':
                return True  # Normal CORE power/safety/mode arbitration still owns the publisher.
            if self.state in ('UNDOCKING', 'DEPARTURE_CHECK'):
                return self.departure is not None and self.departure.ready(mode)
            if self.state == 'RETURNING':
                return mode == 'NAVIGATION' and self._return_valid()
            self._valid(nowait=True)
            operation = self.docking.capture_native_operation(self._operation_id)
            return (mode == 'DOCKING' and self.state == 'DOCKING'
                    and self.feed.relative_pose_nowait() is not None
                    and operation is not None and operation.run_id == self._operation_id
                    and operation.phase != 'TERMINAL')
        except Exception:
            return False
        finally:
            self._lock.release()

    def invalidate(self, reason):
        with self._lock:
            self.state, self.reason, self._seated_until = 'HOLD', reason, None
            self.battery.set_charging(False)
            if self.feed is not None:
                self.feed.stop()
            if self.sensors is not None:
                self.sensors.close()
            if self.motion_feed is not None:
                self.motion_feed.clear()
            self.docking.abort(reason)

    def close(self):
        self.invalidate('STATION_OWNER_SHUTDOWN')

    def clear_charge_evidence(self, reason):
        self._seated_until, self._charge_until, self.reason = None, None, reason
        self.seating.reset()
        self.charging.reset()
        self.battery.set_charging(False)
        if self.state in ('CHARGING', 'CHARGED_HOLD'):
            self.state = 'CHARGE_CONFIRMING'

    def tick(self):
        with self._lock:
            try:
                if self.state == 'WORK_AVAILABLE':
                    self.rebind_boundary.observe()
                    return
                self._valid()
                if self.state in ('UNDOCKING', 'DEPARTURE_CHECK'):
                    if self.departure is None:
                        raise ValueError('STATION_DEPARTURE_PROFILE_REQUIRED')
                    self.departure.tick()
                    return
                if self.state == 'RETURNING':
                    if not self._return_valid():
                        if self.return_authority.lost:
                            self.invalidate('STATION_RETURN_AUTHORITY_LOST')
                        return
                    local = self.local_scope()
                    self.return_authority.observe_stop(self.motion_feed.snapshot() if self.motion_feed else None,
                        odom_epoch=local['odom_epoch'], idle=local['mode'] == 'IDLE')
                    return
                if self.state == 'DOCKING':
                    if self._last_observed is None or self.clock()-self._last_observed > self.profile.max_age_s:
                        self.invalidate('STATION_OBSERVATION_EXPIRED')
                        return
                    if self.feed.relative_pose() is None:
                        return  # Detector restarts clear its sample; output gate stays zero.
                    self.docking.tick()
                    operation = self.docking.capture_native_operation(self._operation_id)
                    if operation is None or operation.run_id != self._operation_id:
                        self.invalidate('STATION_NATIVE_OWNER_CHANGED')
                    elif operation.phase == 'TERMINAL':
                        if operation.result == 'SUCCEEDED' and self.docking.state == DockState.DOCKED:
                            self.state = 'SEATING'
                            self.feed.start(self.docking.database.get(self.session.station_id))
                        else:
                            self.invalidate('STATION_ALIGNMENT_FAILED')
                # Pose-only legacy docking ends before physical seating. Keep its
                # legacy post-dock voltage heuristic out of this charge session.
                if self.sensors is not None:
                    self.sensors.tick(self)
                if self.state in ('CHARGING', 'CHARGED_HOLD') and (
                        self._seated_until is None or self.source_clock() >= self._seated_until
                        or self._charge_until is None or self.source_clock() >= self._charge_until):
                    self.charging.reset()
                    self.battery.set_charging(False)
                    self.state = 'CHARGE_CONFIRMING'
            except Exception:
                self.invalidate('STATION_LOCAL_EVIDENCE_INVALID')

    def update_seating(self, evidence: SeatingEvidence):
        with self._lock:
            self._valid()
            if self.state not in ('SEATING', 'CHARGE_CONFIRMING', 'CHARGING', 'CHARGED_HOLD'):
                return False
            snapshot = self.feed.relative_snapshot()
            relative = snapshot[0] if snapshot is not None else None
            now = self.source_clock()
            if relative is None or self.clock()-relative.at > self.profile.sample_max_age_s:
                self._seated_until = None
                return False
            x, y, heading = robot_in_dock_frame(relative.x, relative.y, relative.yaw, self.profile.marker_offset_m)
            # The camera owns position; never accept a caller's cached in-tolerance claim.
            measured = SeatingEvidence.model_validate(evidence.model_dump() | {
                'position_error_m': math.hypot(x, y), 'heading_error_rad': abs(heading),
                'position_sample_at': now-(self.clock()-relative.at)})
            if not self.seating.update(measured, now=now):
                self._seated_until = None
                return False
            camera_expiry = now + self.profile.sample_max_age_s - (self.clock()-relative.at)
            self._seated_until = min(evidence.valid_until, camera_expiry, snapshot[1])
            if self.state == 'SEATING':
                self.state = 'CHARGE_CONFIRMING'
            return True

    def update_charge(self, status: DockStatus, evidence: ChargeCompletionEvidence, *, received_at):
        with self._lock:
            try:
                self._valid()
                now = self.source_clock()
                evidence = ChargeCompletionEvidence.model_validate(evidence.model_dump(), context={
                    k: getattr(self.session, k) for k in (
                        'robot_id', 'station_id', 'session_id', 'boot_id', 'battery_id')} | {'now': now})
                if (self.state not in ('CHARGE_CONFIRMING', 'CHARGING', 'CHARGED_HOLD')
                        or self._seated_until is None or now >= self._seated_until
                        or not status.answered or status.faults or evidence.faults or not status.load_present
                        or not evidence.load_present or status.charging != evidence.charging
                        or not isinstance(received_at, (int, float)) or isinstance(received_at, bool)
                        or not math.isfinite(received_at) or not 0 <= self.clock()-received_at <= self.profile.max_age_s
                        or evidence.pack_sample_at is None
                        or now-evidence.pack_sample_at > self.profile.pack_max_age_s):
                    raise ValueError('STATION_CHARGE_EVIDENCE_INVALID')
                if evidence.termination == 'NORMAL' and (
                        status.termination != 'NORMAL' or status.termination_source != evidence.source
                        or status.termination_sample_at != evidence.termination_sample_at
                        or status.battery_id != evidence.battery_id):
                    raise ValueError('STATION_TERMINATION_SOURCE_MISMATCH')
                confirmed = self.charging.update(status, evidence.pack_voltage_v, now=received_at)
                self.battery.set_charging(confirmed)
                self._charge_until = min(evidence.valid_until, now+self.profile.max_age_s-(self.clock()-received_at))
                if self.completion.update(evidence, now=now):
                    self.state = 'CHARGED_HOLD'
                    return True
                self.state = 'CHARGING' if confirmed else 'CHARGE_CONFIRMING'
                return False
            except (ValueError, TypeError):
                self.charging.reset()
                self.battery.set_charging(False)
                self._charge_until = None
                if self.state != 'HOLD':
                    self.state = 'CHARGE_CONFIRMING'
                return False
