"""Installed departure facts; never a network reader or a motion writer."""
import math
import threading
from typing import Annotated

from .station_departure_control import StationDepartureController  # noqa: F401

from pydantic import Field, model_validator

from core_common.protocol.station_charging import (
    Contract, Identifier, Positive, Nonnegative, Number, Revision, Pose2D, TimedEvidence,
)

_SAMPLES = ('motion_sample_at', 'space_sample_at', 'power_sample_at', 'current_sample_at', 'contact_sample_at')


class StationDepartureProfile(Contract):
    profile_id: Identifier
    revision: Identifier
    station_id: Identifier
    battery_id: Identifier
    source_id: Identifier
    source_epoch: Identifier
    reverse_distance_m: Positive
    reverse_speed_m_s: Positive
    rear_margin_m: Positive
    max_overshoot_m: Positive
    max_lateral_m: Positive
    max_heading_rad: Positive
    max_age_s: Positive
    max_current_a: Positive


class StationDepartureSample(TimedEvidence):
    robot_id: Identifier
    station_id: Identifier
    session_id: Identifier
    attempt_id: Identifier
    boot_id: Identifier
    battery_id: Identifier
    map_id: Identifier
    map_revision: Identifier
    pose_revision: Revision
    profile_revision: Identifier
    source_id: Identifier
    source_epoch: Identifier
    sequence: Annotated[int, Field(strict=True, ge=0)]
    odom_epoch: Identifier
    pose: Pose2D
    measured_linear_m_s: Number
    measured_angular_rad_s: Number
    rear_clearance_m: Nonnegative
    sweep_verified: bool
    output_enabled: bool
    charging: bool
    current_a: Number
    load_present: bool
    faults: tuple[str, ...]
    motion_sample_at: Nonnegative
    space_sample_at: Nonnegative
    power_sample_at: Nonnegative
    current_sample_at: Nonnegative
    contact_sample_at: Nonnegative

    @model_validator(mode='after')
    def original_sample_times(self):
        if any(getattr(self, key) > self.captured_at for key in _SAMPLES):
            raise ValueError('departure capture cannot precede a source sample')
        return self


class StationDepartureFeed:
    def __init__(self, *, profile, clock, source_clock):
        self.profile = StationDepartureProfile.model_validate(profile.model_dump())
        if not callable(clock) or not callable(source_clock):
            raise ValueError('departure clocks must be installed')
        self.clock, self.source_clock = clock, source_clock
        self._lock = threading.Lock()
        self._last = self._latest = None

    def _live(self, sample, now):
        profile = self.profile
        StationDepartureSample.model_validate(sample.model_dump(), context={'now': now,
            'station_id': profile.station_id, 'battery_id': profile.battery_id, 'source_epoch': profile.source_epoch})
        if (sample.source_id != profile.source_id or sample.profile_revision != profile.revision
                or now-sample.captured_at > profile.max_age_s
                or any(not 0 <= now-getattr(sample, key) <= profile.max_age_s for key in _SAMPLES)):
            raise ValueError('departure source profile or original sample is not live')
        return min(sample.valid_until, *(getattr(sample, key)+profile.max_age_s for key in _SAMPLES))

    def ingest(self, sample):
        with self._lock:
            try:
                sample = StationDepartureSample.model_validate(sample.model_dump())
                utc, mono = self.source_clock(), self.clock()
                if type(mono) not in (int, float) or not math.isfinite(mono):
                    raise ValueError('departure monotonic clock is not finite')
                expiry = self._live(sample, utc)
                if self._last is not None:
                    if sample == self._last:
                        return self._latest is not None  # Preserve the original monotonic deadline.
                    if sample.sequence <= self._last.sequence or sample.captured_at < self._last.captured_at:
                        raise ValueError('departure sequence or capture replay')
                self._last, self._latest = sample, (sample, mono, mono+expiry-utc)
                return True
            except (TypeError, ValueError, AttributeError):
                self._latest = None
                return False

    def snapshot_nowait(self):
        view = self.snapshot_with_deadline_nowait()
        return view[0] if view is not None else None

    def snapshot_with_deadline_nowait(self):
        if not self._lock.acquire(blocking=False):
            return None
        try:
            if self._latest is None:
                return None
            sample, received, deadline = self._latest
            mono = self.clock()
            utc = self.source_clock()
            expiry = self._live(sample, utc)
            if type(mono) not in (int, float) or not math.isfinite(mono) or not received <= mono < deadline:
                raise ValueError('departure monotonic lifetime lost')
            return sample.model_copy(update={'valid_until': min(expiry, utc+deadline-mono)}), (received, deadline)
        except (TypeError, ValueError):
            self._latest = None  # Preserve replay watermark: clock recovery cannot revive this sample.
            return None
        finally:
            self._lock.release()
