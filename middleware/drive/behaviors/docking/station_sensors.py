"""Station contact/charger HTTP cache. Control code reads immutable samples only."""
from dataclasses import dataclass
import math
import threading

from .agent import DockAgent, DockStatus
from .parking import robot_in_dock_frame
from core_common.protocol.station_charging import SeatingEvidence, ChargeCompletionEvidence


@dataclass(frozen=True)
class DockSample:
    status: DockStatus
    monotonic_at: float
    source_at: float


class StationDockPoller:
    def __init__(self, poll, *, clock, source_clock, interval_s, max_age_s):
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0
               for v in (interval_s, max_age_s)):
            raise ValueError('STATION_POLL_LIMITS_REQUIRED')
        self.poll, self.clock, self.source_clock = poll, clock, source_clock
        self.interval_s, self.max_age_s = interval_s, max_age_s
        self._latest, self._thread = None, None
        self._stop = threading.Event()
        self.poll_finished = threading.Event()

    def start(self):
        if self._thread is not None or self._stop.is_set():
            return
        self._thread = threading.Thread(target=self._run, name='station-dock-poll', daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            self.poll_once()
            if self._stop.wait(self.interval_s):
                return

    def poll_once(self):
        self.poll_finished.clear()
        try:
            # The oldest possible contact sample is request start, never reply
            # receipt. A slow HTTP call must consume, not renew, its lease.
            local_at, source_at = self.clock(), self.source_clock()
            status = self.poll()
            if (not isinstance(status, DockStatus) or not status.answered or self._stop.is_set()
                    or not all(math.isfinite(v) for v in (local_at, source_at))):
                self._latest = None
            else:
                self._latest = DockSample(status, local_at, source_at)
        except Exception:
            self._latest = None
        finally:
            self.poll_finished.set()

    def snapshot(self):
        sample = self._latest
        if self._stop.is_set() or sample is None:
            return None
        age, source_age = self.clock()-sample.monotonic_at, self.source_clock()-sample.source_at
        if not 0 <= age <= self.max_age_s or not 0 <= source_age <= self.max_age_s:
            return None
        return sample

    def close(self):
        self._stop.set()
        self._latest = None
        # No join on a controller/mode-exit thread. The daemon's bounded HTTP
        # timeout and stop event finish its lifecycle without delaying a stop.


class StationSensorReader:
    def __init__(self, *, motion_sample, battery_health, clock, source_clock,
                 poller_factory=StationDockPoller):
        self.motion_sample, self.battery_health = motion_sample, battery_health
        self.clock, self.source_clock, self.poller_factory = clock, source_clock, poller_factory
        self._poller, self._proof_at = None, None

    def start(self, owner, dock):
        self.close()
        self._proof_at = None
        profile = owner.profile
        agent = DockAgent(dock.agent_url, timeout_s=min(1.0, profile.max_age_s))
        self._poller = self.poller_factory(agent.poll, clock=self.clock, source_clock=self.source_clock,
                                          interval_s=profile.max_age_s/2, max_age_s=profile.max_age_s)
        self._poller.start()

    def close(self):
        if self._poller is not None:
            self._poller.close()
        self._poller = None

    def tick(self, owner):
        if owner.state not in ('SEATING', 'CHARGE_CONFIRMING', 'CHARGING', 'CHARGED_HOLD'):
            return
        try:
            now, local_now = self.source_clock(), self.clock()
            contact = None if self._poller is None else self._poller.snapshot()
            motion, camera = self.motion_sample(), owner.feed.relative_pose()
            if contact is None or motion is None or camera is None:
                raise ValueError('STATION_SENSOR_SAMPLE_MISSING')
            profile, session, status = owner.profile, owner.session, contact.status
            if (status.dock_id != session.station_id or status.load_sample_at is None
                    or not 0 <= now-status.load_sample_at <= profile.sample_max_age_s):
                raise ValueError('STATION_CONTACT_SOURCE_NOT_VERIFIED')
            contact_at = min(contact.source_at, status.load_sample_at)
            camera_at = now-(local_now-camera.at)
            expiry = min(now+profile.max_age_s, contact_at+profile.sample_max_age_s,
                         motion['captured_at']+profile.sample_max_age_s, camera_at+profile.sample_max_age_s)
            x, y, heading = robot_in_dock_frame(camera.x, camera.y, camera.yaw, profile.marker_offset_m)
            evidence = SeatingEvidence(**{k: getattr(session, k) for k in (
                'robot_id', 'station_id', 'session_id', 'boot_id', 'pose_revision')},
                odom_epoch=motion['odom_epoch'], captured_at=now, valid_until=expiry,
                position_sample_at=camera_at, motion_sample_at=motion['captured_at'],
                contact_sample_at=contact_at, position_error_m=math.hypot(x, y),
                heading_error_rad=abs(heading), measured_linear_m_s=motion['measured_linear_m_s'],
                measured_angular_rad_s=motion['measured_angular_rad_s'], load_present=status.load_present)
            proof_at = min(camera_at, motion['captured_at'], contact_at)
            invalid = (not status.load_present or status.faults
                       or abs(evidence.measured_linear_m_s) > profile.linear_limit_m_s
                       or abs(evidence.measured_angular_rad_s) > profile.angular_limit_rad_s
                       or evidence.position_error_m > profile.position_tolerance_m
                       or evidence.heading_error_rad > profile.heading_tolerance_rad)
            if invalid or self._proof_at is None or proof_at > self._proof_at:
                owner.update_seating(evidence)
                self._proof_at = proof_at
            if invalid:
                raise ValueError('STATION_CONTACT_OR_STANDSTILL_INVALID')
            if owner.state == 'SEATING':
                return
            pack = self.battery_health()
            age = pack['sample_age_s']
            if (isinstance(age, bool) or not isinstance(age, (int, float)) or not math.isfinite(age)
                    or not 0 <= age <= profile.pack_max_age_s):
                raise ValueError('STATION_PACK_SAMPLE_MISSING')
            label = ('NORMAL' if status.termination == 'NORMAL' else 'CHARGING' if status.charging
                     else 'FAULT' if status.faults else 'UNKNOWN')
            charge = ChargeCompletionEvidence(**{k: getattr(session, k) for k in (
                'robot_id', 'station_id', 'session_id', 'boot_id', 'battery_id')},
                captured_at=now, valid_until=min(expiry, now-age+profile.pack_max_age_s),
                load_present=status.load_present, charging=status.charging, termination=label,
                source=status.termination_source if label == 'NORMAL' else 'charger',
                pack_voltage_v=pack['filtered_voltage'], pack_sample_at=now-age,
                termination_sample_at=status.termination_sample_at, faults=list(status.faults))
            owner.update_charge(status, charge, received_at=contact.monotonic_at)
        except (ValueError, TypeError, KeyError):
            self._proof_at = None
            owner.clear_charge_evidence('STATION_SENSOR_EVIDENCE_UNAVAILABLE')
