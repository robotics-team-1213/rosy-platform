"""Measured idle boundary between completed and newly admitted station sessions.

The owner lock and native bind fence serialize replacement. This observer only
reads installed motion evidence; it never renews a departure receipt or moves.
"""
import math

from core_common.protocol.schemas import DockState


class StationRebindBoundary:
    def __init__(self, owner):
        self.owner = owner
        self.retired = set()
        self.key = self.at = self.since = self.deadline = None
        self.utc = self.mono = None
        self.since_mono = None
        self.proven = False

    def observe(self):
        owner = self.owner
        try:
            receipt = owner.departure.receipt if owner.departure else None
            if owner.state != 'WORK_AVAILABLE' or receipt is None:
                raise ValueError('completed departure required')
            local = owner.local_scope_nowait()
            native = owner.docking.native_owner(wait=False)
            motion = owner.motion_feed.snapshot() if owner.motion_feed else None
            if (local is None or native is None or motion is None or local.get('mode') != 'IDLE'
                    or local.get('safety_latched') is not False or local.get('odom_fresh') is not True
                    or any(local.get(key) != getattr(owner.session, key) for key in ('robot_id', 'boot_id', 'battery_id'))
                    or not local.get('odom_epoch') or motion['odom_epoch'] != local['odom_epoch']
                    or native['boot_id'] != owner.session.boot_id or native['owner_run_id'] is not None
                    or type(native['owner_generation']) is not int
                    or native['owner_generation'] < receipt.owner_generation
                    or owner.docking.active or owner.docking.state != DockState.UNDOCKED):
                raise ValueError('current idle owner required')
            mono, utc = owner.clock(), owner.source_clock()
            at, expiry = motion['captured_at'], motion['valid_until']
            linear, angular = motion['measured_linear_m_s'], motion['measured_angular_rad_s']
            if (any(type(value) not in (int, float) or not math.isfinite(value)
                    for value in (mono, utc, at, expiry, linear, angular))
                    or not receipt.captured_at < at <= utc < expiry or utc-at > owner.profile.sample_max_age_s
                    or abs(linear) > owner.profile.linear_limit_m_s or abs(angular) > owner.profile.angular_limit_rad_s
                    or self.utc is not None and (utc < self.utc or mono < self.mono)):
                raise ValueError('fresh post-departure standstill required')
            key = tuple(local.get(name) for name in ('robot_id', 'boot_id', 'battery_id',
                'map_id', 'map_revision', 'odom_epoch'))+(native['owner_generation'], receipt.operation_id)
            if key != self.key:
                self.since = self.since_mono = None
                self.proven = False
            if self.at is not None and at < self.at:
                raise ValueError('motion sample reversed')
            if at == self.at:
                if self.since is None or self.deadline is None or mono >= self.deadline:
                    raise ValueError('motion replay cannot restore standstill')
            else:
                if self.at is None or at-self.at > owner.profile.sample_max_age_s or self.since is None:
                    self.since, self.since_mono = at, mono
                self.deadline = mono+(expiry-utc)
                self.at = at
            self.key, self.utc, self.mono = key, utc, mono
            self.proven = min(at-self.since, mono-self.since_mono) >= owner.profile.still_s
            return self.proven
        except (ValueError, TypeError, KeyError, AttributeError):
            self.since = self.since_mono = None
            self.proven = False
            return False  # Preserve the source watermark and original duplicate deadline.

    def require(self, session, scope):
        owner = self.owner
        if (session.session_id in self.retired or session.session_id == owner.session.session_id
                or session.attempt_id == owner.session.attempt_id or session.state != 'RETURN_RESERVED'
                or session.operation_id is not None or owner.departure is None or owner.departure.receipt is None
                or not owner.departure.receipt.captured_at < session.updated_at <= owner.source_clock()
                or not self.observe()):
            raise ValueError('STATION_NEW_SESSION_STANDSTILL_REQUIRED')
        expected = tuple(getattr(session, name) for name in ('robot_id', 'boot_id', 'battery_id', 'map_id', 'map_revision'))
        if self.key[:5] != expected or self.key[5] != scope.odom_epoch:
            raise ValueError('STATION_NEW_SESSION_SCOPE_CHANGED')

    def retire(self, session_id):
        self.retired.add(session_id)
        self.since = self.since_mono = None
        self.proven = False
