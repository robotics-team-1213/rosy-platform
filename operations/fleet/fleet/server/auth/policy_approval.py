"""D-793 2 / D-1024 3: approval window and execution-lease issuer for an OMX learned policy. Pure, no I/O, no ROS.

A window is a human decision (proposer != approver) for one policy digest on one workcell and rig/calibration
revision. Leases are 1 s (max 2 s), renewed at half period only inside the window, never past its end. When the window
ends, is aborted, or a renewal cannot be delivered the device lease runs out and HOLD is requested; nothing re-approves.
State is memory only: a Fleet restart drops every window, which is the safe direction.
"""
import math
import re
import threading
import time
import uuid

WINDOW_DEFAULT_S, WINDOW_MAX_S = 15 * 60, 30 * 60  # D-793 2: L3 default 15 min, upper bound 30 min
LEASE_DEFAULT_S, LEASE_MAX_S = 1.0, 2.0
MIN_LEASE_S = 0.05  # a lease shorter than this is not worth a delivery; the window end takes over
PROPOSAL_TTL_S = 15 * 60  # an unapproved proposal ages out; approval starts the window clock, not the proposal
_SHA = re.compile(r'[0-9a-f]{64}')


def _text(value, field):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or not value.isprintable():
        raise ValueError(f'{field} required')
    return value


class PolicyApprovals:
    def __init__(self, *, monotonic=time.monotonic, wall=time.time, hold=None, deliver=None,
                 lease_s=LEASE_DEFAULT_S):
        if type(lease_s) not in (int, float) or not 0 < lease_s <= LEASE_MAX_S:
            raise ValueError(f'lease must be in (0, {LEASE_MAX_S}] s')
        self._now, self._wall, self._hold, self._deliver, self._lease_s = monotonic, wall, hold, deliver, float(lease_s)
        self._items, self._lock = {}, threading.RLock()
        self._last, self._clock_fault = float('-inf'), False

    @property
    def delivery_connected(self):
        return self._deliver is not None

    @property
    def lease_s(self):
        return self._lease_s

    def hold_all(self, reason):
        """Fleet shutdown or a lost ticker: close every open window (HOLD goes out, retried by the next tick)."""
        with self._lock:
            for item in self._items.values():
                if item['state'] == 'active':
                    self._close(item, 'held', reason)
                elif item['_hold_due']:  # an earlier HOLD that never went out is retried here too
                    self._fire_hold(item)

    def _tick_time(self):
        """The monotonic clock, guarded: a non-finite or backwards reading latches a fault that holds every window."""
        now = self._now()
        if self._clock_fault or type(now) not in (int, float) or not math.isfinite(now) or now < self._last:
            self._clock_fault = True
            for item in self._items.values():
                self._close(item, 'held', 'clock_fault')
            raise ValueError('monotonic clock fault; approvals are held until Fleet restarts')
        self._last = now
        return now

    def _sweep(self, item, now):
        """Ends a window whose time is up and retries a HOLD that did not go out; true when it ended here."""
        if item['state'] == 'active' and now >= item['_ends']:
            self._close(item, 'ended', 'window_ended')
        elif item['_hold_due']:
            self._fire_hold(item)

    def tick_all(self):
        """Ticker hook: tick every window (<= lease/4). Returns the grants delivered."""
        with self._lock:
            ids = list(self._items)
        return [g for g in (self.tick(i) for i in ids) if g]  # no lock held across a delivery

    @staticmethod
    def _same_person(a, b):
        return a.casefold() == b.casefold()

    def propose(self, *, workcell_id, proposer, policy_digest, rig_revision, calibration_revision, scope,
                window_s=WINDOW_DEFAULT_S):
        for field, value in (('workcell_id', workcell_id), ('proposer', proposer), ('rig_revision', rig_revision),
                             ('calibration_revision', calibration_revision), ('scope', scope)):
            _text(value, field)
        if not isinstance(policy_digest, str) or not _SHA.fullmatch(policy_digest):
            raise ValueError('policy digest must be lowercase sha256')
        if type(window_s) not in (int, float) or not 0 < window_s <= WINDOW_MAX_S:
            raise ValueError(f'window must be in (0, {WINDOW_MAX_S}] s')
        item = dict(id=uuid.uuid4().hex, state='proposed', workcell_id=workcell_id, proposer=proposer, approver=None,
                    policy_digest=policy_digest, rig_revision=rig_revision, calibration_revision=calibration_revision,
                    scope=scope, window_s=float(window_s), proposed_wall=self._wall(), approved_wall=None,
                    hold_reason=None)
        with self._lock:
            self._items[item['id']] = dict(item, _proposed=self._tick_time(), _ends=None, _next=None, _hold_due=None,
                                           lease_id=None, episode_id=None, _seq=0, _delivering=False)
        return self.view(item['id'])

    def _get(self, approval_id):
        item = self._items.get(approval_id)
        if item is None:
            raise KeyError('unknown approval')
        return item

    def approve(self, approval_id, approver):
        _text(approver, 'approver')
        with self._lock:
            item = self._get(approval_id)
            now = self._tick_time()
            if item['state'] != 'proposed':
                raise ValueError(f"approval is {item['state']}")
            if self._same_person(approver, item['proposer']):
                raise PermissionError('proposer and approver must be different people')
            if self._deliver is None:  # A window nobody can enforce must not open (D-793 2).
                raise ValueError('lease delivery is not connected; a window cannot open')
            if now - item['_proposed'] > PROPOSAL_TTL_S:
                item['state'], item['hold_reason'] = 'expired', 'proposal_not_approved_in_time'
                raise ValueError('proposal expired')
            for other in self._items.values():
                self._sweep(other, now)
            if any(o['workcell_id'] == item['workcell_id'] and o['state'] == 'active' for o in self._items.values()):
                raise ValueError('another window is open for this workcell')
            item.update(state='active', approver=approver, approved_wall=self._wall(), _ends=now + item['window_s'],
                        _next=now, lease_id=uuid.uuid4().hex, episode_id=uuid.uuid4().hex)
        return self.view(approval_id)

    def _close(self, item, state, reason):
        if item['state'] == 'active':
            item['state'], item['hold_reason'], item['_hold_due'] = state, reason, reason
            self._fire_hold(item)

    def _fire_hold(self, item):
        """The state is already closed; a hold that fails stays due and is retried by the next sweep or tick."""
        if self._hold is None:
            item['_hold_due'] = None
            return
        try:
            self._hold(item['workcell_id'], item['_hold_due'])  # Device HOLD also follows from the unrenewed lease.
            item['_hold_due'] = None
        except Exception:
            pass

    def abort(self, approval_id, actor):
        _text(actor, 'actor')
        with self._lock:
            item = self._get(approval_id)
            self._sweep(item, self._tick_time())
            if item['state'] == 'proposed':
                item['state'], item['hold_reason'] = 'aborted', f'aborted_by:{actor}'
            elif item['state'] == 'active':
                self._close(item, 'aborted', f'aborted_by:{actor}')
            else:
                raise ValueError(f"approval is {item['state']}")
        return self.view(approval_id)

    def tick(self, approval_id):
        """Call often (<= lease/4). Issues a lease when due and inside the window; ends the window at its end.

        Returns the grant delivered this tick, or None. A lease expiry never exceeds the window end. The delivery runs
        outside the lock so abort, approve and view never wait on a slow CORE; a window closed meanwhile stays closed.
        """
        with self._lock:
            item = self._get(approval_id)
            self._sweep(item, self._tick_time())
            if item['state'] != 'active' or item['_delivering']:
                return None
            now = self._last
            if now < item['_next']:
                return None
            ttl = min(self._lease_s, item['_ends'] - now)
            if ttl < MIN_LEASE_S:  # the window ends within the next tick: no lease, the sweep ends it and HOLDs
                return None
            item['_seq'] += 1
            # seq lets the device refuse a replayed grant; window_remaining_s lets it cap every lease at the window end.
            grant = dict(lease_id=item['lease_id'], episode_id=item['episode_id'], workcell_id=item['workcell_id'],
                         policy_digest=item['policy_digest'], rig_revision=item['rig_revision'],
                         calibration_revision=item['calibration_revision'], ttl_s=ttl, seq=item['_seq'],
                         window_remaining_s=item['_ends'] - now)
            item['_delivering'] = True
            deliver = self._deliver
        try:
            delivered = deliver is not None and deliver(grant) is True
        except Exception:
            delivered = False
        with self._lock:
            item['_delivering'] = False
            if item['state'] != 'active':
                return None
            if not delivered:  # No transport or a failed delivery: the device lease lapses by itself.
                self._close(item, 'held', 'lease_delivery_failed')
                return None
            item['_next'] = now + self._lease_s / 2
            return grant

    def view(self, approval_id):
        with self._lock:
            item = self._get(approval_id)
            try:
                now = self._tick_time()
            except ValueError:  # A faulted clock already held every window; reading must still work.
                now = self._last
            self._sweep(item, now)  # A due window ends on read, not only when a ticker runs.
            out = {k: v for k, v in item.items() if not k.startswith('_')}
            out['window_remaining_s'] = max(0.0, item['_ends'] - now) if item['state'] == 'active' else 0.0
            return out

    def listing(self):
        with self._lock:
            return [self.view(i) for i in self._items]
