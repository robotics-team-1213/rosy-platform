"""Read-only native-owner motor health: PWM utilization is not a torque/continuous rating.

LeRobot 0.4.4 X-series tables expose voltage registers in 0.1 V and temperature
in degrees C. Samples use the owner's existing bus and 5 Hz effort hook.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
import time
from pathlib import Path
from uuid import uuid4


class MotorHealth:
    def __init__(self, log_path=None, *, max_records=100_000):
        fallback = f"motor-health-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}.jsonl"
        self.path = Path(log_path or os.environ.get("ROSY_OMX_MONITOR_LOG") or fallback)
        self.path.touch(exist_ok=False)  # Never truncate an earlier session's evidence.
        self.max_records, self.records = max_records, 0
        self.motions = {}
        self.state_path = Path(os.environ.get('ROSY_OMX_MONITOR_STATE', 'motor-health-current.json')).absolute()
        self.owner_id = os.environ.get('ROSY_OMX_MONITOR_OWNER', 'omx')
        self.session_id = os.environ.get('ROSY_OMX_MONITOR_SESSION') or str(uuid4())
        from uuid import UUID
        if str(UUID(self.session_id)) != self.session_id:
            raise ValueError('invalid motor health session identity')
        self.status, self.stop_reasons = 'active', []
        self.terminal_at = None

    def publish(self):
        motors, stamps = [], []
        fields = ('joint', 'id', 'command_raw', 'present_raw', 'error_deg', 'pwm', 'pwm_limit',
                  'pwm_utilization', 'temperature_c', 'temperature_limit_c', 'voltage_v', 'warnings',
                  'hardware_error', 'torque_enabled', 'fault')
        for state in self.motions.values():
            last = state['last']
            if last is None:
                continue
            stamp = state['observed_at']
            stamps.append(stamp)
            for motor in last['motors']:
                motors.append({**{key: motor[key] for key in fields}, 'group': last['arm'],
                               'min_voltage_v': motor['min_voltage_raw'] / 10,
                               'max_voltage_v': motor['max_voltage_raw'] / 10, 'observed_at': stamp})
        row = dict(schema_version='rosy.motor-health.v1', owner_id=self.owner_id,
            session_id=self.session_id, status=self.status, observed_at=max(stamps) if stamps else self.terminal_at or time.time(),
            expected_motor_count=sum(len(state['limits']) for state in self.motions.values()),
            motors=motors, stop_reasons=self.stop_reasons)
        if self.terminal_at is not None:
            row['terminal_at'] = self.terminal_at
        atomic_snapshot(self.state_path, row)

    def end(self):
        if self.terminal_at is None:
            self.terminal_at = time.time()
        if self.status != 'fault':
            self.status = 'ended'
            self.stop_reasons = ['session ended']
        self.publish()

    @staticmethod
    def number(value, field):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"missing or non-finite motor health {field}: {value}")
        return value

    def emit(self, row):
        if self.records >= self.max_records:
            raise RuntimeError("motor health log record budget exhausted; stop and start a new session")
        row = {**row, "recorded_at_utc": datetime.now(timezone.utc).isoformat()}
        text = json.dumps(row, allow_nan=False)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
            handle.flush()
        self.records += 1

    @staticmethod
    def key(motion):
        return motion.label, id(motion.follower)

    def health(self, bus, name, limits):
        temperature = self.number(bus.read("Present_Temperature", name, normalize=False), "temperature")
        voltage = self.number(bus.read("Present_Input_Voltage", name, normalize=False), "voltage")
        violations = []
        if temperature >= limits["temperature_limit_c"]:
            violations.append(f"{name}: temperature {temperature} >= configured limit {limits['temperature_limit_c']}")
        if not limits["min_voltage_raw"] <= voltage <= limits["max_voltage_raw"]:
            violations.append(f"{name}: voltage {voltage} outside configured limits "
                              f"{limits['min_voltage_raw']}..{limits['max_voltage_raw']} (0.1 V)")
        return temperature, voltage, violations

    def admit(self, motion):
        bus = motion.follower
        limits = {}
        for name in motion.active:
            if bus.read("Torque_Enable", name, normalize=False) != 0:
                raise ValueError(f"{name}: motor health admission requires torque OFF")
            row = {key: self.number(bus.read(register, name, normalize=False), register)
                   for key, register in (("temperature_limit_c", "Temperature_Limit"),
                                         ("min_voltage_raw", "Min_Voltage_Limit"),
                                         ("max_voltage_raw", "Max_Voltage_Limit"))}
            cap = (motion.pwm_limits[name] if name in motion.pwm_limits
                   else bus.read("PWM_Limit", name, normalize=False))
            row["pwm_limit"] = self.number(cap, "PWM_Limit")
            if (not 0 < row["temperature_limit_c"] <= 100 or not 0 < row["pwm_limit"] <= 400
                    or not 0 < row["min_voltage_raw"] <= row["max_voltage_raw"]):
                raise ValueError(f"{name}: invalid motor health configured limits {row}")
            _, _, violations = self.health(bus, name, row)
            if violations:
                raise ValueError("; ".join(violations))
            limits[name] = row
        if not limits:
            raise ValueError("motor health requires active body joints")
        self.emit(dict(event="admission", arm=motion.label, limits=limits))
        self.motions[self.key(motion)] = dict(limits=limits, last=None, report=None, warnings=())
        self.publish()  # An admitted joint without a sample is explicitly incomplete evidence.

    def sample(self, motion, current, pwm, now):
        state = self.motions[self.key(motion)]
        self.number(now, "sample time")
        if state["last"] is not None and not 0 <= now - state["last"]["sample_time"] <= 0.5:
            raise ValueError("stale motor health sample (>0.5 seconds)")
        bus, motors, violations = motion.follower, [], []
        port = getattr(bus, "port", None)
        for name, limits in state["limits"].items():
            present = self.number(current.get(name), name + " position")
            command = int(self.number(motion.command.get(name), name + " command"))
            effort = (bus.read("Present_PWM", name, normalize=False) if name == "gripper" else pwm.get(name))
            effort = self.number(effort, name + " PWM")
            temperature, voltage, unsafe = self.health(bus, name, limits)
            hardware_error = torque_enabled = None
            if not unsafe:
                hardware_error = bus.read('Hardware_Error_Status', name, normalize=False)
                if type(hardware_error) is not int or not 0 <= hardware_error <= 255:
                    raise ValueError(f'{name}: invalid measured hardware status')
                if hardware_error:
                    unsafe.append(f'{name}: hardware error {hardware_error}')
                else:
                    torque_raw = bus.read('Torque_Enable', name, normalize=False)
                    if type(torque_raw) is not int or torque_raw not in (0, 1):
                        raise ValueError(f'{name}: invalid measured torque state')
                    torque_enabled = bool(torque_raw)
            violations.extend(unsafe)
            warnings = []
            utilization = abs(effort) / limits["pwm_limit"]
            if utilization >= 0.9:
                warnings.append("high_pwm")
            if temperature >= limits["temperature_limit_c"] - 5:
                warnings.append("near_temperature_limit")  # 5 C is a warning margin, not a continuous rating.
            motors.append(dict(joint=name, id=bus.motors[name].id, usb_port=port if isinstance(port, str) else None,
                               command_raw=command, present_raw=present, error_deg=abs(present - command) * 360 / 4096,
                               pwm=effort, pwm_utilization=utilization, temperature_c=temperature,
                               voltage_raw=voltage, voltage_v=voltage / 10, warnings=warnings,
                               hardware_error=hardware_error, torque_enabled=torque_enabled,
                               fault=bool(unsafe), **limits))
            if unsafe:
                break  # Stop further bus reads as soon as an actual configured hard limit is known.
        if not violations and not 0 <= self.number(motion.clock(), "sample completion time") - now <= 0.5:
            raise ValueError("stale motor health telemetry (>0.5 seconds)")
        row = dict(event="sample", arm=motion.label, sample_time=now, motors=motors, stop_reasons=violations)
        state["last"] = row
        state['observed_at'] = time.time() - max(0, motion.clock() - now)
        if violations:
            raise ValueError("; ".join(violations))  # The owner turns OFF before fault() persists this sample.
        self.emit(row)
        self.publish()
        warnings = tuple((m["id"], tuple(m["warnings"])) for m in motors if m["warnings"])
        if state["report"] is None or now - state["report"] >= 1 or warnings != state["warnings"]:
            detail = " | ".join(f"ID{m['id']} {m['joint']} error={m['error_deg']:.2f}deg "
                                f"PWM={m['pwm']}/{m['pwm_limit']}({100*m['pwm_utilization']:.0f}%) "
                                f"T={m['temperature_c']}C V={m['voltage_v']:.1f} "
                                f"{','.join(m['warnings'])}" for m in motors)
            print(f"motor-health {motion.label}: {detail}", flush=True)
            state["report"] = now
        state["warnings"] = warnings

    def fault(self, motion, exc):
        if self.terminal_at is None:
            self.terminal_at = time.time()
        state = self.motions.get(self.key(motion))
        last = state["last"] if state else None
        now = motion.clock()
        row = dict(event="fault", arm=motion.label, fault=str(exc) or type(exc).__name__,
                   fault_type=type(exc).__name__, telemetry="last_known",
                   fault_time=now, sample_time=last["sample_time"] if last else None,
                   sample_age_s=now - last["sample_time"] if last else None,
                   motors=last["motors"] if last else [],
                   active_motor_ids={name: motion.follower.motors[name].id for name in motion.active},
                   stop_reasons=last["stop_reasons"] if last else [])
        print(f"motor-health {motion.label}: FAULT {exc}; last sample age={row['sample_age_s']}", flush=True)
        self.status = 'fault'
        self.stop_reasons = [public_reason(exc)]
        try:
            self.emit(row)
        finally:
            self.publish()


def public_reason(exc):
    if isinstance(exc, KeyboardInterrupt):
        return 'operator interruption'
    if not isinstance(exc, ValueError):
        return 'control failure'
    text = str(exc).lower()
    if 'temperature' in text and '>= configured limit' in text:
        return 'temperature limit'
    if 'voltage' in text and 'outside configured limits' in text:
        return 'voltage limit'
    for needle, reason in (('hardware error', 'hardware error'), ('following error', 'following error'),
                           ('overload risk', 'overload risk'), ('stale', 'stale telemetry'),
                           ('alignment deadline', 'alignment deadline')):
        if needle in text:
            return reason
    return 'control failure'


def atomic_snapshot(path, row):
    """Readers see one complete session, never a partially replaced sample."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError('motor health snapshot must not be a symlink')
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            json.dump(row, handle, allow_nan=False)
            handle.flush()
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def finish_snapshot(path, owner_id, session_id, *, safe_end):
    """Parent fallback after OFF cleanup, before releasing the single-owner lock."""
    path = Path(path)
    if not path.exists():
        return
    if path.is_symlink() or path.stat().st_size > 256_000:
        raise ValueError('untrusted motor health snapshot')
    row = json.loads(path.read_text(encoding='utf-8'))
    if row.get('owner_id') != owner_id or row.get('session_id') != session_id:
        raise ValueError('motor health snapshot binding mismatch')
    if not safe_end:
        row['status'] = 'fault'
        row['stop_reasons'] = list(dict.fromkeys([*row.get('stop_reasons', []), 'cleanup unconfirmed']))
    elif row.get('status') != 'fault':
        row['status'], row['stop_reasons'] = 'ended', ['session ended']
    row.setdefault('terminal_at', time.time())
    atomic_snapshot(path, row)
