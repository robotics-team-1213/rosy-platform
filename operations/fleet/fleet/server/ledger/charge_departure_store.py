"""Departure preparation and measured claim release in ChargeStore's transaction.

This ledger never submits motion. The coordinator must obtain fresh policy and
CORE evidence; task identity, session authority and release remain atomic here.
"""
from contextlib import closing
from datetime import datetime
import json

from core_common.protocol.station_charging import (
    ChargeSessionStatus, StationDeparturePermit, StationDepartureReceipt,
)
from fleet.server.charge_policy_admission import work_request_digest
from fleet.server.dispatch_admission import release

_SCOPE = ('session_id', 'robot_id', 'station_id', 'battery_id', 'boot_id',
          'pose_revision', 'map_id', 'map_revision', 'attempt_id')


class ChargeDepartureStore:
    @staticmethod
    def _departure_task_time(expires_at, now):
        if expires_at is not None:
            expiry = datetime.fromisoformat(expires_at)
            if expiry.tzinfo is None or expiry.timestamp() <= now:
                raise ValueError('CHARGE_DEPARTURE_WORK_EXPIRED')

    @classmethod
    def _departure_final_check(cls, evidence, clock, started, admission, expires_at=None):
        if admission() is not True:
            raise ValueError('CHARGE_DEPARTURE_POLICY_UNVERIFIED')
        now = clock()
        type(evidence).model_validate(evidence.model_dump(), context={'now': now})
        if now < started:
            raise ValueError('CHARGE_DEPARTURE_CLOCK_REVERSED')
        cls._departure_task_time(expires_at, now)

    @staticmethod
    def _departure_row(db, session_id):
        return db.execute('SELECT * FROM fleet_charge_departures WHERE session_id=?', (session_id,)).fetchone()

    def _departure_task(self, db, permit, now):
        row = db.execute('SELECT * FROM fleet_tasks WHERE task_id=?', (permit.work_task_id,)).fetchone()
        if (row is None or row['robot_id'] != permit.robot_id or row['status'] != 'QUEUED'
                or row['dispatch_phase'] != 'READY' or row['attempt_id'] is not None
                or work_request_digest(self.tasks._task_dict(row)) != permit.work_request_digest):
            raise ValueError('CHARGE_DEPARTURE_WORK_CHANGED')
        self._departure_task_time(row['expires_at'], now)
        unresolved = db.execute('''SELECT 1 FROM fleet_tasks WHERE robot_id=?
            AND (status IN ('ACCEPTED', 'RUNNING', 'UNKNOWN')
                 OR (status='QUEUED' AND dispatch_phase NOT IN ('READY', 'WAITING_TRAFFIC'))) LIMIT 1''',
            (permit.robot_id,)).fetchone()
        if unresolved:
            raise ValueError('CHARGE_DEPARTURE_UNFINISHED_WORK')
        return self.tasks._task_dict(row)

    def prepare_departure(self, permit, *, clock, admission):
        if not callable(clock) or not callable(admission):
            raise ValueError('CHARGE_DEPARTURE_CLOCK_AND_ADMISSION_REQUIRED')
        permit = StationDeparturePermit.model_validate(permit.model_dump())
        with self._write() as db:
            now = clock()  # BEGIN IMMEDIATE may wait; caller-sampled time is insufficient.
            StationDeparturePermit.model_validate(permit.model_dump(), context={'now': now})
            if admission() is not True:
                raise ValueError('CHARGE_DEPARTURE_POLICY_UNVERIFIED')
            row = self._row(db, permit.session_id)
            current = self._value(row)
            intent = db.execute("SELECT * FROM fleet_charge_operations WHERE session_id=? AND kind='dock'",
                (permit.session_id,)).fetchone()
            if (current is None or current.state != 'CHARGED_HOLD' or current.operation_id is None
                    or any(getattr(current, key) != getattr(permit, key) for key in _SCOPE)
                    or not self._admitted(db, row, current) or now < current.updated_at
                    or intent is None or intent['status'] != 'ACKNOWLEDGED'
                    or intent['operation_id'] != current.operation_id
                    or self._departure_row(db, current.session_id) is not None):
                raise ValueError('CHARGE_DEPARTURE_PREPARATION_CONFLICT')
            self._departure_task(db, permit, now)
            db.execute('INSERT INTO fleet_charge_departures(session_id, permit_json) VALUES (?, ?)',
                (current.session_id, permit.model_dump_json()))
            db.execute('''INSERT INTO fleet_charge_operations
                (session_id, kind, correlation_id, state, status) VALUES (?, 'undock', ?, 'UNDOCKING', 'PREPARED')''',
                (current.session_id, permit.correlation_id))
            for state in ('DEPARTURE_CHECK', 'UNDOCKING'):
                current = ChargeSessionStatus.model_validate(current.model_dump() | dict(
                    state=state, operation_id=None, updated_at=now, reason='CHARGE_DEPARTURE_PREPARED'))
                self._save(db, current)
            task = self._departure_task(db, permit, now)
            self._departure_final_check(permit, clock, now, admission, task['expires_at'])
            return current

    def departure_context(self, session_id):
        with closing(self.tasks._connect()) as db:
            row = self._departure_row(db, session_id)
            active = db.execute('SELECT permit_json FROM fleet_charge_departure_renewals WHERE session_id=?',
                (session_id,)).fetchone()
            return None if row is None else dict(permit=json.loads(row['permit_json']),
                active_permit=json.loads(active['permit_json'] if active else row['permit_json']),
                receipt=json.loads(row['receipt_json']) if row['receipt_json'] else None)

    def renew_departure_permission(self, permit, *, previous, clock, admission):
        """Record an acknowledged same-run CORE renewal; never submit or repeat motion.

        Keep the initial motion fence separately from the latest live lease. The
        previous lease is a compare-and-swap guard against delayed HTTP replies.
        """
        if not callable(clock) or not callable(admission):
            raise ValueError('CHARGE_DEPARTURE_CLOCK_AND_ADMISSION_REQUIRED')
        permit = StationDeparturePermit.model_validate(permit.model_dump())
        previous = StationDeparturePermit.model_validate(previous.model_dump())
        with self._write() as db:
            now = clock()
            self._departure_final_check(previous, clock, now, admission)
            StationDeparturePermit.model_validate(permit.model_dump(), context={'now': now})
            row = self._row(db, permit.session_id)
            current = self._value(row)
            context = self._departure_row(db, permit.session_id)
            active = db.execute('SELECT permit_json FROM fleet_charge_departure_renewals WHERE session_id=?',
                (permit.session_id,)).fetchone()
            intent = db.execute("SELECT * FROM fleet_charge_operations WHERE session_id=? AND kind='undock'",
                (permit.session_id,)).fetchone()
            if (current is None or context is None or current.state != 'UNDOCKING'
                    or not self._admitted(db, row, current) or now < current.updated_at
                    or intent is None or intent['status'] != 'ACKNOWLEDGED'
                    or intent['operation_id'] != current.operation_id
                    or intent['correlation_id'] != permit.correlation_id):
                raise ValueError('CHARGE_DEPARTURE_OPERATION_UNVERIFIED')
            original = StationDeparturePermit.model_validate_json(context['permit_json'])
            stored = StationDeparturePermit.model_validate_json(active['permit_json']) if active else original
            mutable = {'captured_at', 'valid_until', 'expected_owner_generation'}
            if (stored != previous or permit.model_dump(exclude=mutable) != original.model_dump(exclude=mutable)
                    or permit.captured_at <= stored.captured_at
                    or permit.expected_owner_generation <= original.expected_owner_generation
                    or permit.expected_owner_generation < stored.expected_owner_generation):
                raise ValueError('CHARGE_DEPARTURE_RENEWAL_CONFLICT')
            task = self._departure_task(db, original, now)
            db.execute('INSERT INTO fleet_charge_departure_renewals(session_id, permit_json) VALUES (?, ?) '
                'ON CONFLICT(session_id) DO UPDATE SET permit_json=excluded.permit_json',
                (permit.session_id, permit.model_dump_json()))
            self._departure_final_check(previous, clock, now, admission, task['expires_at'])
            self._departure_final_check(permit, clock, now, admission, task['expires_at'])
            return current

    def validate_departure_permission(self, permit, *, prepared, clock, admission):
        """Final task/session admission before a physical start, renewal or finish."""
        if not callable(clock) or not callable(admission):
            raise ValueError('CHARGE_DEPARTURE_CLOCK_AND_ADMISSION_REQUIRED')
        permit = StationDeparturePermit.model_validate(permit.model_dump())
        with self._write() as db:
            now = clock()
            StationDeparturePermit.model_validate(permit.model_dump(), context={'now': now})
            row = self._row(db, permit.session_id)
            current = self._value(row)
            context = self._departure_row(db, permit.session_id)
            active = db.execute('SELECT permit_json FROM fleet_charge_departure_renewals WHERE session_id=?',
                (permit.session_id,)).fetchone()
            intent = db.execute("SELECT * FROM fleet_charge_operations WHERE session_id=? AND kind='undock'",
                (permit.session_id,)).fetchone()
            if (current is None or context is None or current.state != 'UNDOCKING'
                    or any(getattr(current, key) != getattr(permit, key) for key in _SCOPE)
                    or not self._admitted(db, row, current) or now < current.updated_at
                    or intent is None or intent['status'] != ('PREPARED' if prepared else 'ACKNOWLEDGED')
                    or intent['operation_id'] != current.operation_id
                    or intent['correlation_id'] != permit.correlation_id
                    or StationDeparturePermit.model_validate_json(
                        active['permit_json'] if active else context['permit_json']) != permit):
                raise ValueError('CHARGE_DEPARTURE_OPERATION_UNVERIFIED')
            task = self._departure_task(db, permit, now)
            self._departure_final_check(permit, clock, now, admission, task['expires_at'])
            return current

    def complete_departure(self, receipt, *, clock, admission):
        if not callable(clock) or not callable(admission):
            raise ValueError('CHARGE_DEPARTURE_CLOCK_AND_ADMISSION_REQUIRED')
        receipt = StationDepartureReceipt.model_validate(receipt.model_dump())
        with self._write() as db:
            now = clock()
            StationDepartureReceipt.model_validate(receipt.model_dump(), context={'now': now})
            if admission() is not True:
                raise ValueError('CHARGE_DEPARTURE_POLICY_UNVERIFIED')
            row = self._row(db, receipt.session_id)
            current = self._value(row)
            context = self._departure_row(db, receipt.session_id)
            if current is None or context is None:
                raise ValueError('CHARGE_DEPARTURE_RECEIPT_REQUIRED')
            permit = StationDeparturePermit.model_validate_json(context['permit_json'])
            active = db.execute('SELECT permit_json FROM fleet_charge_departure_renewals WHERE session_id=?',
                (receipt.session_id,)).fetchone()
            live_permit = StationDeparturePermit.model_validate_json(active['permit_json']) if active else permit
            expected = {key: getattr(permit, key) for key in (*_SCOPE, 'correlation_id',
                'work_task_id', 'work_request_digest')}
            StationDepartureReceipt.model_validate(receipt.model_dump(), context=expected | {'now': now})
            if (receipt.operation_id != current.operation_id or now < current.updated_at
                    or receipt.owner_generation <= permit.expected_owner_generation
                    or receipt.owner_generation < live_permit.expected_owner_generation
                    or receipt.valid_until > live_permit.valid_until
                    or receipt.stopped_since <= permit.captured_at):
                raise ValueError('CHARGE_DEPARTURE_RECEIPT_SCOPE_CHANGED')
            if current.state == 'WORK_AVAILABLE':
                if context['receipt_json'] is None or StationDepartureReceipt.model_validate_json(
                        context['receipt_json']) != receipt:
                    raise ValueError('CHARGE_DEPARTURE_RECEIPT_CONFLICT')
                self._departure_final_check(receipt, clock, now, admission)
                return current
            intent = db.execute("SELECT * FROM fleet_charge_operations WHERE session_id=? AND kind='undock'",
                (current.session_id,)).fetchone()
            if (current.state != 'UNDOCKING' or not self._admitted(db, row, current)
                    or intent is None or intent['status'] != 'ACKNOWLEDGED'
                    or intent['correlation_id'] != receipt.correlation_id
                    or intent['operation_id'] != receipt.operation_id):
                raise ValueError('CHARGE_DEPARTURE_OPERATION_UNVERIFIED')
            self._departure_task(db, permit, now)
            db.execute('UPDATE fleet_charge_departures SET receipt_json=? WHERE session_id=?',
                (receipt.model_dump_json(), current.session_id))
            current = ChargeSessionStatus.model_validate(current.model_dump() | dict(
                state='WORK_AVAILABLE', updated_at=now, reason='CHARGE_DEPARTURE_MEASURED'))
            self._save(db, current)
            release(db, owner_kind='charge_session', owner_id=current.session_id, generation=row['generation'])
            task = self._departure_task(db, permit, now)
            self._departure_final_check(receipt, clock, now, admission, task['expires_at'])
            return current
