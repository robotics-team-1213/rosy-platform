"""Read-only command-relative observations; HOLD here is a recommendation, not a physical stop."""
from __future__ import annotations

from collections import deque
import json

from core_common.protocol.motor_health import MotorHealthResponse

from .hardware_profile import _number
from .load_assessment import assess_candidates, command_positions
from .motion_characteristics import _canonical, _text, document_digest, validate_characteristics


class LoadMonitor:
    def __init__(self, document, request, *, accepted_digest, candidate_id, command_id, started_at, session_id):
        self.profile = validate_characteristics(document)
        self.request = json.loads(_canonical(request))
        self.assessment = assess_candidates(self.profile, self.request, accepted_digest=accepted_digest)
        match = next((c for c in self.assessment['candidates'] if c['id'] == candidate_id), None)
        if match is None or not match['load_domain_match']:
            raise ValueError('monitor requires a measured-domain candidate')
        _text(command_id, 'command_id')
        _text(session_id, 'session_id')
        self.started_at = _number(started_at, 'started_at', positive=True)
        self.command_id, self.session_id, self.candidate_id = command_id, session_id, candidate_id
        self.trajectory_sha256 = match['trajectory_sha256']
        self.envelope = next(e for e in self.profile['envelopes'] if e['id'] == match['matched_envelope_id'])
        self.last_capture = self.last_now = None
        self.last_joint_capture = {}
        self.latched = set()
        self.error_since = {}
        self.history = {name: deque(maxlen=4096) for name in self.profile['joints']}

    def _report(self, reasons, errors, captured, now):
        self.latched.update(reasons)
        holding = bool(self.latched)
        return {'schema': 'rosy.omx-load-monitor.v1', 'status': 'hold_for_owner_review' if holding else 'observing',
                'recommendation': ('replan_from_fresh_state_after_owner_recovery' if holding
                                   else 'continue_observation_only'),
                'reasons': sorted(self.latched), 'errors_rad': errors,
                'command_id': self.command_id, 'candidate_id': self.candidate_id,
                'trajectory_sha256': self.trajectory_sha256,
                'characteristics_sha256': self.assessment['characteristics_sha256'],
                'characteristics_revision': self.profile['revision'],
                'request_sha256': self.assessment['request_sha256'], 'context': self.profile['binding'],
                'source_sequence': self.request['source_sequence'], 'task_id': self.request['task_id'],
                'scene_revision': self.request['scene_revision'], 'session_id': self.session_id,
                'captured_at': captured, 'assessed_at': now,
                'motion_admitted': False, 'automatic_recovery_enabled': False}

    def observe(self, health, *, captured_at, now, context):
        """Use each motor's original measurement time; never use command_raw as the reference."""
        captured = _number(captured_at, 'captured_at', positive=True)
        now = _number(now, 'now', positive=True)
        reasons, errors = set(), {}
        if context != self.profile['binding']:
            reasons.add('configuration_changed')
        if self.last_now is not None and now < self.last_now:
            reasons.add('receipt_clock_regressed')
        if captured > now or captured < self.started_at:
            reasons.add('source_clock_invalid')
        if self.last_capture is not None:
            if captured <= self.last_capture:
                reasons.add('source_clock_regressed')
            elif captured - self.last_capture > self.profile['monitor']['max_gap_s'] + 1e-9:
                reasons.add('feedback_gap')
        self.last_now, self.last_capture = now, captured
        if not isinstance(health, MotorHealthResponse):
            raise ValueError('expected existing MotorHealthResponse')
        # Revalidate mutable Pydantic instances at the read-only trust boundary.
        health = MotorHealthResponse.model_validate(health.model_dump())
        if health.owner_id != self.profile['binding']['owner_id']:
            reasons.add('owner_changed')
        if health.session_id != self.session_id:
            reasons.add('session_changed')
        if health.status != 'active' or health.evidence != 'fresh':
            reasons.add('source_not_active')
        if (health.sample_age_s is None or abs(health.sample_age_s - (now - captured)) > 1e-6
                or now - captured > self.profile['monitor']['max_age_s']):
            reasons.add('stale_feedback')
        names = list(self.profile['joints'])
        if len(health.motors) != len(names) or {m.joint for m in health.motors} != set(names):
            reasons.add('joint_coverage')
        if reasons:
            return self._report(reasons, errors, captured, now)
        for motor in health.motors:
            name = motor.joint
            joint = self.profile['joints'][name]
            if motor.group != health.owner_id or motor.id != joint['motor_id']:
                reasons.add(f'motor_identity:{name}')
                continue
            if motor.hardware_error is None:
                reasons.add(f'hardware_status_unconfirmed:{name}')
            if motor.fault or motor.hardware_error:
                reasons.add(f'hardware_fault:{name}')
            if motor.torque_enabled is not True:
                reasons.add(f'torque_unconfirmed:{name}')
            if motor.temperature_c >= motor.temperature_limit_c:
                reasons.add(f'temperature_limit:{name}')
            if not motor.min_voltage_v <= motor.voltage_v <= motor.max_voltage_v:
                reasons.add(f'voltage_limit:{name}')
            if (not self.envelope['temperature_c'][0] <= motor.temperature_c <= self.envelope['temperature_c'][1]
                    or not self.envelope['voltage_v'][0] <= motor.voltage_v <= self.envelope['voltage_v'][1]):
                reasons.add(f'outside_measured_domain:{name}')
            stamp = now - motor.sample_age_s
            previous = self.last_joint_capture.get(name)
            if motor.sample_age_s > self.profile['monitor']['max_age_s'] or stamp > captured + 1e-6:
                reasons.add(f'stale_feedback:{name}')
                continue
            if previous is not None and (stamp <= previous or stamp - previous > self.profile['monitor']['max_gap_s'] + 1e-9):
                reasons.add(f'feedback_gap:{name}')
                continue
            self.last_joint_capture[name] = stamp
            try:
                desired = command_positions(self.request, self.candidate_id, stamp - self.started_at)
                actual = _number((motor.present_raw - joint['raw_zero']) * joint['rad_per_raw'], 'position_rad')
            except (ValueError, OverflowError):
                reasons.add(f'command_reference_unavailable:{name}')
                continue
            if not self.envelope['position_rad'][name][0] <= actual <= self.envelope['position_rad'][name][1]:
                reasons.add(f'outside_measured_domain:{name}')
            error = actual - desired[names.index(name)]
            errors[name] = error
            self._tracking(name, stamp, error, reasons)
        return self._report(reasons, errors, captured, now)

    def _tracking(self, name, stamp, error, reasons):
        monitor = self.profile['monitor']
        limits = monitor['joints'][name]
        if abs(error) >= limits['error_rad']:
            self.error_since.setdefault(name, stamp)
        elif abs(error) <= limits['clear_error_rad']:
            self.error_since.pop(name, None)
        if name in self.error_since and stamp - self.error_since[name] >= monitor['tracking_duration_s'] - 1e-9:
            reasons.add(f'following_error:{name}')
        history = self.history[name]
        history.append((stamp, error))
        while history and history[0][0] < stamp - monitor['oscillation_window_s']:
            history.popleft()
        previous, reversals = 0, 0
        for _, value in history:
            sign = 1 if value >= limits['oscillation_amplitude_rad'] else -1 if value <= -limits['oscillation_amplitude_rad'] else 0
            if sign:
                if previous and sign != previous:
                    reversals += 1
                previous = sign
        if reversals >= 2 * monitor['oscillation_cycles']:
            reasons.add(f'oscillation:{name}')
