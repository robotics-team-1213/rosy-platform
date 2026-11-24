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


def _safe_print(text: str) -> None:
    try:
        print(text, flush=True)
    except Exception:  # noqa: BLE001  closed or broken stdout must never drop a powered HOLD
        pass


class TelemetryReadError(ValueError): recoverable_telemetry = True


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
        fields = ('joint', 'id', 'command_raw', 'present_raw', 'error_deg', 'pwm', 'pwm_limit', 'pwm_utilization',
                  'temperature_c', 'temperature_limit_c', 'voltage_v', 'warnings', 'hardware_error', 'torque_enabled', 'fault')
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
            raise TelemetryReadError(f"missing or non-finite motor health {field}: {value}")
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

    @staticmethod
    def _finite(v):
        return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)

    @staticmethod
    def _limit_violation(kind, name, value, limits):
        if kind == "temperature":
            return f"{name}: temperature {value} >= configured limit {limits['temperature_limit_c']}" if value >= limits["temperature_limit_c"] else None
        lo, hi = limits["min_voltage_raw"], limits["max_voltage_raw"]
        return None if lo <= value <= hi else f"{name}: voltage {value} outside configured limits {lo}..{hi} (0.1 V)"

    def _read_register(self, bus, register, names, batch, *, stop_if=None, valid=None):
        values, err, missing = {}, None, list(names)
        if batch:
            try:
                raw = bus.sync_read(register, names, normalize=False, num_retry=2)
                if isinstance(raw, dict):
                    values.update(raw)
                    if stop_if is not None and any(n in values and stop_if(n, values[n]) for n in names):
                        return values, None
                    missing = [n for n in names if n not in values or not (valid or self._finite)(values[n])]
                    if not missing:
                        return values, None
                else: err = TelemetryReadError(f"missing motor health {register}: {raw}")
            except (OSError, TimeoutError, ConnectionError) as exc:
                err = exc
        read = getattr(bus, "read", None)
        if callable(read):
            for name in missing:
                try:
                    val = values[name] = read(register, name, normalize=False)
                    if stop_if is not None and stop_if(name, val):
                        break
                except (OSError, TimeoutError, ConnectionError) as exc:
                    err = err or exc
        return values, err

    def health(self, bus, name, limits):
        violations, vals, err = [], {"temperature": None, "voltage": None}, None
        for reg, kind in (("Present_Temperature", "temperature"), ("Present_Input_Voltage", "voltage")):
            try:
                val = vals[kind] = self.number(bus.read(reg, name, normalize=False), kind)
                if (msg := self._limit_violation(kind, name, val, limits)):
                    violations.append(msg)
                    if kind == "temperature":
                        return val, None, violations
            except (OSError, TimeoutError, ConnectionError, ValueError) as exc:
                err = err or exc
        if not violations and err is not None:
            raise err
        return vals["temperature"], vals["voltage"], violations

    def probe_limits(self, motion):
        state = self.motions.get(self.key(motion))
        if not state:
            return
        bus, limits_map = motion.follower, state["limits"]
        names, batch = list(limits_map), "read" not in vars(bus) and hasattr(bus, "model_ctrl_table")
        for reg, kind in (("Present_Temperature", "temperature"), ("Present_Input_Voltage", "voltage")):
            stop = lambda n, v, k=kind: self._finite(v) and bool(self._limit_violation(k, n, v, limits_map[n]))
            raw, _ = self._read_register(bus, reg, names, batch, stop_if=stop)
            bad = [m for n in names if n in raw and self._finite(raw[n]) and (m := self._limit_violation(kind, n, raw[n], limits_map[n]))]
            if bad:
                raise ValueError("; ".join(bad))

    def check_temperature(self, motion, name, temp):
        state = self.motions.get(self.key(motion))
        limits = state["limits"].get(name) if state else None
        if limits and self._finite(temp) and (msg := self._limit_violation("temperature", name, temp, limits)):
            raise ValueError(msg)

    def admit(self, motion):
        bus, limits = motion.follower, {}
        for name in motion.active:
            if bus.read("Torque_Enable", name, normalize=False) != 0:
                raise ValueError(f"{name}: motor health admission requires torque OFF")
            row = {k: self.number(bus.read(r, name, normalize=False), r) for k, r in (
                ("temperature_limit_c", "Temperature_Limit"), ("min_voltage_raw", "Min_Voltage_Limit"), ("max_voltage_raw", "Max_Voltage_Limit"))}
            cap = motion.pwm_limits[name] if name in motion.pwm_limits else bus.read("PWM_Limit", name, normalize=False)
            row["pwm_limit"] = self.number(cap, "PWM_Limit")
            ceiling = 600 if name in motion.pwm_limits else 400  # body caps already passed guarded_native.PWM_ADMIT_MAX
            if (not 0 < row["temperature_limit_c"] <= 100 or not 0 < row["pwm_limit"] <= ceiling
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

    def resume(self, motion):
        """The guard restarted after a pause it was told about (lerobot saving an episode): skip the next sample-age check."""
        self.motions[self.key(motion)]["resumed"] = True

    supports_hold_gap = True

    def sample(self, motion, current, pwm, now, *, allow_gap=False):
        state = self.motions[self.key(motion)]
        self.number(now, "sample time")
        if state["last"] is not None and not state.pop("resumed", False):
            gap = now - state["last"]["sample_time"]
            if gap < 0 or (not allow_gap and gap > 0.5):
                raise ValueError("stale motor health sample (>0.5 seconds)")
        bus, limits_map = motion.follower, state["limits"]
        names, port = list(limits_map), getattr(bus, "port", None)
        batch = "read" not in vars(bus) and hasattr(bus, "model_ctrl_table")
        violations, first_err, hw_errs, torques = [], None, {}, {}

        def check_limits(register, kind):
            nonlocal first_err
            stop = lambda n, v: self._finite(v) and bool(self._limit_violation(kind, n, v, limits_map[n]))
            raw, err = self._read_register(bus, register, names, batch, stop_if=stop)
            first_err = first_err or err
            for name in names:
                val = raw.get(name) if name in raw else None
                if name not in raw or not self._finite(val):
                    first_err = first_err or TelemetryReadError(f"missing or non-finite motor health {kind}: {val}")
                elif (msg := self._limit_violation(kind, name, val, limits_map[name])):
                    violations.append(msg)
            return raw

        temps = check_limits("Present_Temperature", "temperature")
        volts = check_limits("Present_Input_Voltage", "voltage") if not violations else {}
        if not violations:
            hw_errs, err = self._read_register(bus, "Hardware_Error_Status", names, batch,
                valid=lambda v: type(v) is int and 0 <= v <= 255, stop_if=lambda _n, v: type(v) is int and 0 < v <= 255)
            first_err = first_err or err
            for name in names:
                hw = hw_errs.get(name)
                if type(hw) is not int or not 0 <= hw <= 255:
                    first_err = first_err or TelemetryReadError(f"{name}: invalid measured hardware status")
                elif hw:
                    violations.append(f"{name}: hardware error {hw}")
        if not violations and first_err is None:
            torques, err = self._read_register(bus, "Torque_Enable", names, batch, valid=lambda v: type(v) is int and v in (0, 1))
            first_err = first_err or err
            if (bad_tq := next((n for n in names if type(torques.get(n)) is not int or torques[n] not in (0, 1)), None)) is not None:
                first_err = first_err or TelemetryReadError(f"{bad_tq}: invalid measured torque state")
        if not violations and first_err is not None:
            raise first_err
        motors = []
        for name, limits in limits_map.items():
            if violations:
                rp, rc, re_ = (current or {}).get(name), (motion.command or {}).get(name), None if name == "gripper" else (pwm or {}).get(name)
                present, command, effort = (rp if self._finite(rp) else None), (int(rc) if self._finite(rc) else None), (re_ if self._finite(re_) else None)
            else:
                present = self.number(current.get(name), name + " position")
                command = int(self.number(motion.command.get(name), name + " command"))
                effort = self.number(bus.read("Present_PWM", name, normalize=False) if name == "gripper" else pwm.get(name), name + " PWM")
            temperature, voltage = (temps.get(name) if self._finite(temps.get(name)) else None), (volts.get(name) if self._finite(volts.get(name)) else None)
            hw, tq = hw_errs.get(name), torques.get(name)
            hardware_error = hw if type(hw) is int and 0 <= hw <= 255 else None
            torque_enabled = bool(tq) if type(tq) is int and tq in (0, 1) else None
            fault = bool((temperature is not None and self._limit_violation("temperature", name, temperature, limits))
                         or (voltage is not None and self._limit_violation("voltage", name, voltage, limits))
                         or (hardware_error is not None and hardware_error != 0))
            utilization = abs(effort) / limits["pwm_limit"] if effort is not None else None
            warnings = [w for cond, w in ((utilization is not None and utilization >= 0.9, "high_pwm"), (temperature is not None and temperature >= limits["temperature_limit_c"] - 5, "near_temperature_limit")) if cond]
            error_deg = abs(present - command) * 360 / 4096 if present is not None and command is not None else None
            motors.append(dict(
                joint=name, id=bus.motors[name].id, usb_port=port if isinstance(port, str) else None, command_raw=command,
                present_raw=present, error_deg=error_deg, pwm=effort, pwm_utilization=utilization, temperature_c=temperature,
                voltage_raw=voltage, voltage_v=None if voltage is None else voltage / 10, warnings=warnings,
                hardware_error=hardware_error, torque_enabled=torque_enabled, fault=fault, **limits))
        if not violations and not 0 <= self.number(motion.clock(), "sample completion time") - now <= 0.5:
            raise ValueError("stale motor health telemetry (>0.5 seconds)")
        row = dict(event="sample", arm=motion.label, sample_time=now, motors=motors, stop_reasons=violations)
        state["last"] = row
        state['observed_at'] = time.time() - max(0, motion.clock() - now)
        if violations:
            raise ValueError("; ".join(violations))  # The owner turns OFF before fault() persists this sample.
        warnings = tuple((m["id"], tuple(m["warnings"])) for m in motors if m["warnings"])
        due = state["report"] is None or now - state["report"] >= 0.5 or warnings != state["warnings"]
        try:
            self.emit(row)
            if due:
                self.publish()
        except OSError as exc:
            if not allow_gap:
                raise
            _safe_print(f"motor-health {motion.label}: diagnostic write failed ({exc})")
        else:
            if due:
                detail = " | ".join(f"ID{m['id']} {m['joint']} error={m['error_deg']:.2f}deg PWM={m['pwm']}/{m['pwm_limit']}({100*m['pwm_utilization']:.0f}%) "
                                    f"T={m['temperature_c']}C V={m['voltage_v']:.1f} {','.join(m['warnings'])}" for m in motors)
                _safe_print(f"motor-health {motion.label}: {detail}")
                state["report"] = now
            state["warnings"] = warnings

    def fault(self, motion, exc):
        if self.terminal_at is None:
            self.terminal_at = time.time()
        state = self.motions.get(self.key(motion))
        last = state["last"] if state else None
        if last:  # the public reason has no joint; flag the one the guard names ("wrist_roll: following error ...")
            joint = str(exc).split(':', 1)[0]
            last["motors"] = [{**m, "fault": m["fault"] or m["joint"] == joint} for m in last["motors"]]
        now = motion.clock()
        row = dict(event="fault", arm=motion.label, fault=str(exc) or type(exc).__name__,
                   fault_type=type(exc).__name__, telemetry="last_known",
                   fault_time=now, sample_time=last["sample_time"] if last else None,
                   sample_age_s=now - last["sample_time"] if last else None,
                   motors=last["motors"] if last else [],
                   active_motor_ids={name: motion.follower.motors[name].id for name in motion.active},
                   stop_reasons=last["stop_reasons"] if last else [])
        _safe_print(f"motor-health {motion.label}: FAULT {exc}; last sample age={row['sample_age_s']}")
        self.status = 'fault'
        self.stop_reasons = [public_reason(exc)]
        try:
            self.emit(row)
        finally:
            self.publish()
            keep_fault(self.state_path.parent / 'faults', self.owner_id, self.session_id, row)


FAULT_FRAMES = 'top=http://127.0.0.1:8767/frame/top.jpg,side=http://127.0.0.1:8767/frame/side.jpg'  # rosy-omx-camera-view


def keep_fault(directory, owner_id, session_id, row, frames=None):
    """One record per guard fault plus cell camera snapshots fetched off-thread after torque OFF."""
    import threading
    import urllib.request
    try:
        directory = Path(directory)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        stem = f"{owner_id}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:6]}"
        record = dict(schema_version='rosy.motor-fault.v1', owner_id=owner_id, session_id=session_id,
                      at=time.time(), **row, frames={})
        atomic_snapshot(directory / f"{stem}.json", record)
    except (OSError, ValueError):
        return None
    wanted = frames if frames is not None else os.environ.get('ROSY_OMX_FAULT_FRAMES', FAULT_FRAMES)
    sources = dict(item.split('=', 1) for item in wanted.split(',') if '=' in item)

    def fetch():
        for name, url in sources.items():
            if not name.isidentifier() or not url.startswith(('http://127.0.0.1', 'http://localhost')):
                continue  # local camera view only: a fault record never reaches out
            try:
                with urllib.request.urlopen(url, timeout=1.5) as response:
                    image = response.read(4_000_000)
                if image[:2] == b'\xff\xd8':
                    (directory / f"{stem}-{name}.jpg").write_bytes(image)
                    record['frames'][name] = f"{stem}-{name}.jpg"
            except (OSError, ValueError):
                continue
        atomic_snapshot(directory / f"{stem}.json", record)

    worker = threading.Thread(target=fetch, name='fault-frames')  # not a daemon: the frames outlive a crashing runner
    worker.start()
    return worker


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
