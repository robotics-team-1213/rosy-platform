"""Original calibrated energy facts; no ROS, motion authority or BMS guess.

Only a trusted private port can supply a reading. CORE separately publishes
these facts under its writer boundary and latches parent-specific STOP. Neither
a public DTO nor this module's arithmetic authenticates a device or calibration.
"""
from dataclasses import dataclass
import math
from threading import RLock
import time
from uuid import UUID


def _number(value, lower, upper):
    return type(value) in (int, float) and lower <= value <= upper and math.isfinite(value)


def _text(value):
    return type(value) is str and 0 < len(value) <= 128 and value == value.strip()


def _up(value):
    return math.nextafter(value, math.inf)


def _down(value):
    return math.nextafter(value, -math.inf)


@dataclass(frozen=True)
class EnergyProfile:
    robot_id: str
    boot_id: UUID
    battery_id: str
    kind: str
    epoch: str
    capacity_revision: str
    revision: str
    whole_load_w: float
    reserve_j: float
    max_age_s: float
    min_soh: float
    min_temperature_c: float
    max_temperature_c: float

    def __post_init__(self):
        if (not all(_text(v) for v in (self.robot_id, self.battery_id, self.epoch,
                                      self.capacity_revision, self.revision))
                or type(self.boot_id) is not UUID or type(self.kind) is not str
                or self.kind not in ('bms', 'fuel_gauge', 'bench')
                or not _number(self.whole_load_w, 0., 1e9) or self.whole_load_w == 0
                or not _number(self.reserve_j, 0., 1e12) or self.reserve_j == 0
                or not _number(self.max_age_s, 0., 86400.) or self.max_age_s == 0
                or not _number(self.min_soh, 0., 100.)
                or not _number(self.min_temperature_c, -100., 200.)
                or not _number(self.max_temperature_c, -100., 200.)
                or self.min_temperature_c >= self.max_temperature_c):
            raise ValueError('bounded measured energy profile required')


@dataclass(frozen=True)
class EnergyReading:
    sequence: int
    stamp_ns: int
    battery_id: str
    epoch: str
    capacity_revision: str
    usable_wh_lower: float
    soc_percent: float
    soh_percent: float
    temperature_c: float
    fault: bool


@dataclass(frozen=True, eq=False)
class EnergyReceipt:
    profile: EnergyProfile
    reading: EnergyReading
    capture_mono: float
    valid_until_mono: float
    validated_mono: float
    available_j: int


@dataclass(frozen=True, eq=False)
class _Read:
    before: float


def covers(receipt, profile, *, end_mono, now):
    """Conservative whole-window arithmetic, NOT receipt/source authentication."""
    if (type(receipt) is not EnergyReceipt or type(profile) is not EnergyProfile
            or receipt.profile is not profile
            or not _number(now, 0., 1e15) or not _number(end_mono, 0., 1e15)
            or not receipt.validated_mono <= now < receipt.valid_until_mono or end_mono < now):
        return False
    # Round every debit upward. Idle time before another parent shares this
    # original capture; stop tail is already inside the parent's fixed end.
    span = max(0., _up(end_mono - receipt.capture_mono))
    required = _up(_up(profile.whole_load_w * span) + profile.reserve_j)
    return math.isfinite(required) and receipt.available_j > math.ceil(required)


class PackEnergySource:
    """Bounded original watermarks; no producer lock enters CORE's final path."""
    def __init__(self, *, profile, provider, clock=time.monotonic):
        if type(profile) is not EnergyProfile or provider is None or not callable(clock):
            raise ValueError('exact profile and trusted private provider required')
        self._profile, self._provider = profile, provider
        self._clock = clock
        self._lock = RLock()
        self._last_clock = None
        self._closed = False
        self._pending = None
        self._sequence = self._stamp = 0
        self._source_now = 0
        self._reading = self._receipt = None

    @property
    def profile(self):
        return self._profile

    @property
    def provider(self):
        return self._provider

    def _now(self):
        try:
            now = self._clock()
        except Exception:
            now = None
        if (not _number(now, 0., 1e15)
                or self._last_clock is not None and now < self._last_clock):
            self._closed = True
            self._receipt = None
            return None
        self._last_clock = now
        return now

    def begin(self, provider):
        with self._lock:
            before = self._now()
            if self._closed or provider is not self.provider or self._pending is not None:
                self._receipt = None
                return None
            self._pending = None if before is None else _Read(before)
            return self._pending

    def _healthy(self, reading):
        profile = self.profile
        return (all(_text(v) for v in (reading.battery_id, reading.epoch, reading.capacity_revision))
                and reading.battery_id == profile.battery_id and reading.epoch == profile.epoch
                and reading.capacity_revision == profile.capacity_revision
                and type(reading.fault) is bool and not reading.fault
                and _number(reading.usable_wh_lower, 0., 1e9)
                and _number(reading.soc_percent, 0., 100.)
                and _number(reading.soh_percent, profile.min_soh, 100.)
                and _number(reading.temperature_c, profile.min_temperature_c,
                            profile.max_temperature_c))

    def abort(self, ticket):
        with self._lock:
            if ticket is None or ticket is not self._pending:
                return False
            self._pending = self._receipt = None
            return True

    def complete(self, ticket, provider, reading, *, source_now_ns):
        with self._lock:
            if ticket is None or ticket is not self._pending:
                return None  # An unrelated/old token cannot consume the live read.
            self._pending = None
            prior = self._receipt
            self._receipt = None  # Every failed original stays failed at its watermark.
            now = self._now()
            if (self._closed or now is None or provider is not self.provider
                    or type(reading) is not EnergyReading):
                return None
            if type(source_now_ns) is not int or not 0 <= source_now_ns < 2**63:
                return None
            if source_now_ns < self._source_now:
                self._closed = True  # Clock reset, independently of header validity.
                return None
            self._source_now = source_now_ns
            valid_header = (type(reading.sequence) is int and 0 < reading.sequence < 2**63
                            and type(reading.stamp_ns) is int and 0 < reading.stamp_ns < 2**63)
            if not valid_header:
                return None
            same = reading.sequence == self._sequence and reading.stamp_ns == self._stamp
            newer = reading.sequence > self._sequence and reading.stamp_ns > self._stamp
            # Retain high watermarks even when a future/unsafe/mismatched reading
            # fails. Editing it or going backwards cannot make it a new fact.
            self._sequence = max(self._sequence, reading.sequence)
            self._stamp = max(self._stamp, reading.stamp_ns)
            if reading.stamp_ns > source_now_ns:
                return None
            if (not (same or newer) or not self._healthy(reading)
                    or same and (prior is None or reading != self._reading)):
                return None
            capture = _down(ticket.before - _up((source_now_ns - reading.stamp_ns) / 1e9))
            expiry = _down(capture + self.profile.max_age_s)
            if same:
                capture, expiry = min(capture, prior.capture_mono), min(expiry, prior.valid_until_mono)
            # Final clock sample includes validation/arithmetic, never a caller's
            # fresh receipt timestamp. Raw source state grants no CORE authority.
            available = math.floor(_down(reading.usable_wh_lower * 3600.))
            final = self._now()
            if final is None or not now <= final < expiry:
                return None
            self._reading = reading
            self._receipt = EnergyReceipt(self.profile, reading, capture, expiry, final, available)
            return self._receipt
