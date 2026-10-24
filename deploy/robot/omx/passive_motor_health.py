"""Health snapshots from the passive observer's EXISTING full register read only."""
import math
import time
from pathlib import Path
from uuid import uuid4

from core_common.motor_health import write_motor_health_snapshot
from core_common.protocol.motor_health import MotorHealthSample

JOINTS = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1']


class PassiveMotorHealth:
    def __init__(self, path, owner):
        self.path, self.owner = Path(path).absolute(), owner
        self.session = str(uuid4())
        self.last = None

    def sample(self, rows, *, captured_at, elapsed):
        if not math.isfinite(elapsed) or not 0 <= elapsed <= .25:
            raise ValueError('stale passive motor health read')
        if [row['id'] for row in rows] != list(range(11, 17)):
            raise ValueError('passive health requires six ordered follower motors')
        motors, reasons = [], []
        for joint, row in zip(JOINTS, rows):
            if row['model_number'] != (1060 if row['id'] < 14 else 1200):
                raise ValueError('passive motor model mismatch')
            temperature, voltage = row['temperature'], row['voltage_raw'] / 10
            warnings = []
            cap = row['pwm_limit_raw']
            if type(cap) not in (int, float) or not math.isfinite(cap) or cap <= 0:
                raise ValueError('invalid passive motor PWM limit')
            utilization = abs(row['present_pwm_raw']) / row['pwm_limit_raw']
            if utilization >= .9:
                warnings.append('high_pwm')
            if temperature >= row['temperature_limit'] - 5:
                warnings.append('near_temperature_limit')
            fault = row['hardware_error'] != 0
            if fault:
                reasons.append('hardware error')
            if temperature >= row['temperature_limit']:
                fault = True
                reasons.append('temperature limit')
            if not row['min_voltage_raw'] <= row['voltage_raw'] <= row['max_voltage_raw']:
                fault = True
                reasons.append('voltage limit')
            if row['torque_enabled'] != 0:
                fault = True
                reasons.append('control failure')
            motor = MotorHealthSample(group=self.owner, joint=joint, id=row['id'], sample_age_s=0.,
                command_raw=row['goal_position_raw'], present_raw=row['position_raw'],
                error_deg=abs(row['goal_position_raw'] - row['position_raw']) * 360 / 4096,
                pwm=row['present_pwm_raw'], pwm_limit=row['pwm_limit_raw'], pwm_utilization=utilization,
                temperature_c=temperature, temperature_limit_c=row['temperature_limit'], voltage_v=voltage,
                min_voltage_v=row['min_voltage_raw'] / 10, max_voltage_v=row['max_voltage_raw'] / 10,
                warnings=warnings, hardware_error=row['hardware_error'], fault=fault,
                torque_enabled=bool(row['torque_enabled']))
            public = motor.model_dump(exclude={'sample_age_s'})
            motors.append({**public, 'observed_at': captured_at})
        if self.last is not None and self.last['status'] == 'fault':
            reasons = [*self.last['stop_reasons'], *reasons]
        self.last = dict(schema_version='rosy.motor-health.v1', owner_id=self.owner, session_id=self.session,
            status='fault' if reasons else 'active', observed_at=captured_at, expected_motor_count=6,
            motors=motors, stop_reasons=list(dict.fromkeys(reasons)))
        if reasons:
            self.last['terminal_at'] = captured_at
        write_motor_health_snapshot(self.path, self.last)

    def end(self, error=None):
        if self.last is None:
            return  # No synthetic motor values when a transport fails before its first sample.
        if error is not None:
            if self.last['status'] != 'fault':
                self.last['terminal_at'] = time.time()
            self.last['status'] = 'fault'
            self.last['stop_reasons'] = list(dict.fromkeys([*self.last['stop_reasons'], 'control failure']))
        elif self.last['status'] != 'fault':
            self.last['status'], self.last['stop_reasons'] = 'ended', ['session ended']
            self.last['terminal_at'] = time.time()
        write_motor_health_snapshot(self.path, self.last)
