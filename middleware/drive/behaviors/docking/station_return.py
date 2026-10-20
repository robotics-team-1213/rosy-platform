"""Scoped return permission and measured handover; called under the station owner lock."""
import math

class StationReturnAuthority:
    def __init__(self, permit, *, owner_id, lease_probe, native_probe, clock, source_clock, profile):
        self.permit, self.owner_id = permit, owner_id
        self.lease_probe, self.native_probe = lease_probe, native_probe
        self.clock, self.source_clock, self.profile = clock, source_clock, profile
        self.started = clock()
        self.deadline = self.started+(permit.valid_until-source_clock())
        self.lost = False
        self.since = self.proof_at = None
        self.stop_after = permit.captured_at
        self.lease_until = permit.captured_at

    def valid(self):
        if self.lost:
            return False
        utc, mono, permit = self.source_clock(), self.clock(), self.permit
        if (not permit.captured_at <= utc < permit.valid_until
                or not self.started <= mono < self.deadline):
            self.lost = True
            return False
        native = self.native_probe()
        if native is None:
            return False
        if (native['boot_id'] != permit.boot_id or native['owner_generation'] != permit.expected_owner_generation
                or native['owner_run_id'] is not None):
            self.lost = True
            return False
        matched = self.lease_probe(lease_id=permit.lease_id, trip_id=permit.trip_id,
                                   job_id=permit.session_id, owner_id=self.owner_id)
        if matched is False:
            self.lost = True
        if isinstance(matched, dict) and matched.get('remaining_s', 0) > 0:
            self.lease_until = utc+matched['remaining_s']
            return True
        return False

    def observe_stop(self, motion, *, odom_epoch, idle):
        try:
            now = self.source_clock()
            if not idle or motion is None or motion['odom_epoch'] != odom_epoch:
                raise ValueError('return motion scope unavailable')
            at, expiry = motion['captured_at'], motion['valid_until']
            linear, angular = motion['measured_linear_m_s'], motion['measured_angular_rad_s']
            if (any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v)
                    for v in (now, at, expiry, linear, angular))
                    or not self.stop_after < at <= now < expiry or now-at > self.profile.sample_max_age_s
                    or abs(linear) > self.profile.linear_limit_m_s
                    or abs(angular) > self.profile.angular_limit_rad_s):
                raise ValueError('return standstill not measured')
            if self.proof_at is not None:
                if at < self.proof_at:
                    raise ValueError('return motion reversed')
                if at == self.proof_at:
                    return at-self.since >= self.profile.still_s
                if at-self.proof_at > self.profile.sample_max_age_s:
                    self.since = None
            if self.since is None:
                self.since = at
            self.proof_at = at
            return at-self.since >= self.profile.still_s
        except (ValueError, KeyError, TypeError):
            self.since = self.proof_at = None
            return False

    def require_new_stop(self):
        self.since = self.proof_at = None
        self.stop_after = self.source_clock()

    def renew(self, permit):
        if not self.valid():
            raise ValueError('STATION_RETURN_AUTHORITY_LOST')
        old = self.permit.model_dump(exclude={'captured_at', 'valid_until'})
        if permit.model_dump(exclude={'captured_at', 'valid_until'}) != old:
            raise ValueError('STATION_RETURN_SCOPE_CHANGED')
        if permit == self.permit:
            return  # Replayed ACK lookup never renews a source or monotonic deadline.
        if permit.captured_at <= self.permit.captured_at:
            raise ValueError('STATION_RETURN_REFRESH_REVERSED')
        self.permit = permit
        self.started = self.clock()
        self.deadline = self.started+(permit.valid_until-self.source_clock())
