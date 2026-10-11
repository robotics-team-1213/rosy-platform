import math
import time

from dynamixel_sdk import *


UINT32_MODULUS = 1 << 32
INT32_SIGN_BIT = 1 << 31


def decode_signed_32(raw_value):
    """Decode an unsigned DYNAMIXEL register value as signed two's complement."""
    value = int(raw_value) & 0xFFFFFFFF
    return value - UINT32_MODULUS if value >= INT32_SIGN_BIT else value


def wrapped_encoder_delta(current, previous):
    """Return the shortest signed delta across a 32-bit encoder rollover."""
    return (
        int(current) - int(previous) + INT32_SIGN_BIT
    ) % UINT32_MODULUS - INT32_SIGN_BIT


def validate_motor_ids(dxl_ids):
    """Return exactly two distinct DYNAMIXEL unicast IDs without coercion."""
    values = tuple(dxl_ids)
    if len(values) != 2:
        raise ValueError('dxl_ids must contain two distinct motor IDs')
    if any(
        isinstance(dxl_id, bool)
        or not isinstance(dxl_id, int)
        or not 0 <= dxl_id <= 252
        for dxl_id in values
    ):
        raise ValueError('dxl_ids must be integers from 0 through 252')
    if values[0] == values[1]:
        raise ValueError('dxl_ids must contain two distinct motor IDs')
    return values


def validate_profile_acceleration(profile_acceleration):
    """Return a valid raw DYNAMIXEL Profile Acceleration value."""
    if (
        isinstance(profile_acceleration, bool)
        or not isinstance(profile_acceleration, int)
        or not 1 <= profile_acceleration <= 32767
    ):
        raise ValueError('profile acceleration must be an integer from 1 through 32767')
    return profile_acceleration

# Hardware Error Status bits (X-series Control Table, address 70).
HARDWARE_ERROR_BITS = (
    (0x01, 'input voltage'), (0x04, 'overheating'), (0x08, 'motor encoder'),
    (0x10, 'electrical shock'), (0x20, 'overload'),
)
# Start-up motion probe: ~5 rpm for 0.4 s is about 8 ticks/ms of 4096 per turn,
# a few millimetres of wheel travel. A free wheel moves well past the minimum.
# Opt-in only (motor_motion_check): it moves the wheels. Off by default.
PROBE_RPM = 5.0
PROBE_SECONDS = 0.4
PROBE_MIN_TICKS = 20
CURRENT_MA_PER_UNIT = 2.69
# Always-on, no-motion stall heuristic: a motor holding zero velocity should
# draw little current. Only a gross fault trips it; a stall that draws ~100 mA
# (8kcn ID 1) is caught by the hardware-error register or the opt-in probe.
IDLE_CURRENT_MAX_MA = 250.0


def describe_hardware_error(value):
    names = [name for bit, name in HARDWARE_ERROR_BITS if value & bit]
    return f"0x{value:02X} ({', '.join(names) or 'unknown'})"


class DynamixelDriver:
    def __init__(self, port, baudrate, dxl_ids, max_rpm=100.0):
        self.ADDR_OPERATING_MODE    = 11
        self.ADDR_TORQUE_ENABLE     = 64
        self.ADDR_LED_RED           = 65
        self.ADDR_GOAL_VELOCITY     = 104
        self.ADDR_PROFILE_ACCEL     = 108
        self.ADDR_HARDWARE_ERROR    = 70
        self.ADDR_PRESENT_CURRENT   = 126
        self.ADDR_PRESENT_VELOCITY  = 128
        self.ADDR_PRESENT_POSITION  = 132

        self.LEN_GOAL_VELOCITY      = 4
        self.LEN_PRESENT_VELOCITY   = 4
        self.LEN_PRESENT_POSITION   = 4

        self.PROTOCOL_VERSION       = 2.0
        dxl_ids = validate_motor_ids(dxl_ids)
        try:
            max_rpm = float(max_rpm)
        except (TypeError, ValueError) as error:
            raise ValueError('max_rpm must be a positive finite number') from error
        if not math.isfinite(max_rpm) or max_rpm <= 0:
            raise ValueError('max_rpm must be a positive finite number')

        self.DXL_IDS                = list(dxl_ids)
        self.BAUDRATE               = baudrate
        self.DEVICENAME             = port
        self.MAX_RPM                = max_rpm

        self.RPM_TO_VALUE_SCALE = 1 / 0.229

        self.portHandler = PortHandler(self.DEVICENAME)
        self.packetHandler = PacketHandler(self.PROTOCOL_VERSION)

        self.groupSyncWrite = GroupSyncWrite(self.portHandler, self.packetHandler, self.ADDR_GOAL_VELOCITY, self.LEN_GOAL_VELOCITY)
        self.groupBulkRead = GroupBulkRead(self.portHandler, self.packetHandler)

    def begin(self):
        if not self.portHandler.openPort(): return False
        if not self.portHandler.setBaudRate(self.BAUDRATE):
            self.portHandler.closePort()
            return False
        return True

    def terminate(self):
        try:
            try:
                self.set_double_rpm(0, 0)
                time.sleep(0.1)
            except Exception:
                pass
            self._disable_all()
            time.sleep(0.1)
        finally:
            self.portHandler.closePort()

    @staticmethod
    def _packet_ok(result):
        return len(result) >= 2 and result[-2] == COMM_SUCCESS and result[-1] == 0

    def _disable_all(self):
        for dxl_id in self.DXL_IDS:
            for address in (self.ADDR_TORQUE_ENABLE, self.ADDR_LED_RED):
                try:
                    self.packetHandler.write1ByteTxRx(
                        self.portHandler, dxl_id, address, 0
                    )
                except Exception:
                    pass

    def initialize_motors(self, profile_accel=200, enable_torque=True):
        """Reboot, velocity mode, zero goal confirmed, then torque on.

        enable_torque=False (D-192 no-motion mode) stops after the zero goal is
        confirmed: torque stays off, so the wheels cannot be driven whatever is
        written later, while Present Velocity/Position still read back.
        """
        try:
            profile_accel = validate_profile_acceleration(profile_accel)
        except ValueError:
            return False
        for dxl_id in self.DXL_IDS:
            try:
                reboot_result = self.packetHandler.reboot(self.portHandler, dxl_id)
                if not self._packet_ok(reboot_result):
                    self._disable_all()
                    return False
                time.sleep(0.5)
            except Exception as e:
                print(f"Warning: Could not reboot motor {dxl_id}. Error: {e}")
                self._disable_all()
                return False

        for dxl_id in self.DXL_IDS:
            steps = (
                self.packetHandler.write1ByteTxRx(
                    self.portHandler, dxl_id, self.ADDR_TORQUE_ENABLE, 0
                ),
                self.packetHandler.write1ByteTxRx(
                    self.portHandler, dxl_id, self.ADDR_OPERATING_MODE, 1
                ),
                self.packetHandler.write4ByteTxRx(
                    self.portHandler, dxl_id, self.ADDR_PROFILE_ACCEL, profile_accel
                ),
            )
            if not all(self._packet_ok(result) for result in steps):
                self._disable_all()
                return False

        # A retained goal must never become live when drive torque is enabled.
        if not self.set_double_rpm(0, 0):
            self._disable_all()
            return False
        for dxl_id in self.DXL_IDS:
            goal, comm_result, packet_error = self.packetHandler.read4ByteTxRx(
                self.portHandler,
                dxl_id,
                self.ADDR_GOAL_VELOCITY,
            )
            if comm_result != COMM_SUCCESS or packet_error != 0 or goal != 0:
                self._disable_all()
                return False

        if not enable_torque:
            return True

        for dxl_id in self.DXL_IDS:
            if not self._packet_ok(
                self.packetHandler.write1ByteTxRx(
                    self.portHandler, dxl_id, self.ADDR_TORQUE_ENABLE, 1
                )
            ):
                self._disable_all()
                return False
            if not self._packet_ok(
                self.packetHandler.write1ByteTxRx(
                    self.portHandler, dxl_id, self.ADDR_LED_RED, 1
                )
            ):
                self._disable_all()
                return False
        return True

    def _read_register(self, reader, dxl_id, address):
        """Value of one register, or None without a clean reply (alert bit 0x80 is data, not failure)."""
        try:
            value, comm_result, packet_error = reader(self.portHandler, dxl_id, address)
        except Exception:
            return None
        if comm_result != COMM_SUCCESS or packet_error & 0x7F:
            return None
        return value

    def verify_motors(self, expect_torque, check_motion):
        """Return fault strings for motors that are not really ready; [] means healthy.

        Always reads each motor's hardware-error status, torque flag, position
        and idle current (no wheel motion). Only with check_motion (opt-in, it
        moves the wheels) does it also spin both wheels at PROBE_RPM for PROBE_SECONDS
        and requires the position to move (a latched overload stalls at
        constant position while the current climbs), then stops them.
        """
        read1 = self.packetHandler.read1ByteTxRx
        faults = []
        for dxl_id in self.DXL_IDS:
            hardware_error = self._read_register(read1, dxl_id, self.ADDR_HARDWARE_ERROR)
            if hardware_error is None:
                faults.append(f'ID {dxl_id}: no reply reading hardware error status')
            elif hardware_error:
                faults.append(
                    f'ID {dxl_id}: hardware error {describe_hardware_error(hardware_error)}')
            torque = self._read_register(read1, dxl_id, self.ADDR_TORQUE_ENABLE)
            if torque != int(bool(expect_torque)):
                faults.append(f'ID {dxl_id}: torque enable is {torque}, expected {int(bool(expect_torque))}')
        if faults:
            return faults
        # No-motion checks (goal is zero here): position and present current readable and sane.
        for dxl_id in self.DXL_IDS:
            if self._read_register(self.packetHandler.read4ByteTxRx, dxl_id,
                                   self.ADDR_PRESENT_POSITION) is None:
                faults.append(f'ID {dxl_id}: present position unreadable')
            current = self._read_register(self.packetHandler.read2ByteTxRx, dxl_id,
                                          self.ADDR_PRESENT_CURRENT)
            if current is None:
                faults.append(f'ID {dxl_id}: present current unreadable')
                continue
            milliamps = abs(current - 65536 if current >= 32768 else current) * CURRENT_MA_PER_UNIT
            if milliamps > IDLE_CURRENT_MAX_MA:
                faults.append(
                    f'ID {dxl_id}: {milliamps:.0f} mA at zero velocity (> {IDLE_CURRENT_MAX_MA:.0f} mA), stall or load suspected')
        if faults or not check_motion:
            return faults

        read4 = self.packetHandler.read4ByteTxRx
        before = [self._read_register(read4, i, self.ADDR_PRESENT_POSITION) for i in self.DXL_IDS]
        try:
            if not self.set_double_rpm(PROBE_RPM, PROBE_RPM):
                return ['motion probe command was refused']
            time.sleep(PROBE_SECONDS)
            after = [self._read_register(read4, i, self.ADDR_PRESENT_POSITION) for i in self.DXL_IDS]
            currents = [self._read_register(self.packetHandler.read2ByteTxRx, i,
                                            self.ADDR_PRESENT_CURRENT) for i in self.DXL_IDS]
            errors = [self._read_register(read1, i, self.ADDR_HARDWARE_ERROR) for i in self.DXL_IDS]
        finally:
            self.set_double_rpm(0, 0)
        for index, dxl_id in enumerate(self.DXL_IDS):
            if errors[index]:
                faults.append(
                    f'ID {dxl_id}: hardware error {describe_hardware_error(errors[index])} during motion probe')
                continue
            if before[index] is None or after[index] is None:
                faults.append(f'ID {dxl_id}: no position reply during motion probe')
                continue
            moved = abs(decode_signed_32(after[index]) - decode_signed_32(before[index]))
            if moved < PROBE_MIN_TICKS:
                current = currents[index]
                text = 'unknown' if current is None else (
                    f'{abs(current - 65536 if current >= 32768 else current) * CURRENT_MA_PER_UNIT:.0f} mA')
                faults.append(
                    f'ID {dxl_id}: stalled, moved {moved} ticks (< {PROBE_MIN_TICKS}) at {PROBE_RPM:g} rpm, current {text}')
        return faults

    def set_double_rpm(self, rpm_l, rpm_r):
        try:
            velocities = [float(rpm_l), float(rpm_r)]
        except (TypeError, ValueError):
            return False
        if any(
            not math.isfinite(velocity) or abs(velocity) > self.MAX_RPM
            for velocity in velocities
        ):
            return False
        self.groupSyncWrite.clearParam()

        for i, dxl_id in enumerate(self.DXL_IDS):
            dxl_vel = int(velocities[i] * self.RPM_TO_VALUE_SCALE)
            param = [DXL_LOBYTE(DXL_LOWORD(dxl_vel)), DXL_HIBYTE(DXL_LOWORD(dxl_vel)),
                     DXL_LOBYTE(DXL_HIWORD(dxl_vel)), DXL_HIBYTE(DXL_HIWORD(dxl_vel))]
            if not self.groupSyncWrite.addParam(dxl_id, param):
                self.groupSyncWrite.clearParam()
                return False

        return self.groupSyncWrite.txPacket() == COMM_SUCCESS

    def get_feedback(self):
        self.groupBulkRead.clearParam()
        read_len = self.LEN_PRESENT_VELOCITY + self.LEN_PRESENT_POSITION
        
        for dxl_id in self.DXL_IDS:
            if not self.groupBulkRead.addParam(
                dxl_id, self.ADDR_PRESENT_VELOCITY, read_len
            ):
                self.groupBulkRead.clearParam()
                return None, None, None, None

        if self.groupBulkRead.txRxPacket() != COMM_SUCCESS:
            return None, None, None, None
        
        id_l, id_r = self.DXL_IDS[0], self.DXL_IDS[1]
        if not self.groupBulkRead.isAvailable(id_l, self.ADDR_PRESENT_VELOCITY, read_len) or \
           not self.groupBulkRead.isAvailable(id_r, self.ADDR_PRESENT_VELOCITY, read_len):
            return None, None, None, None

        vel_raw_l = self.groupBulkRead.getData(id_l, self.ADDR_PRESENT_VELOCITY, self.LEN_PRESENT_VELOCITY)
        pos_raw_l = self.groupBulkRead.getData(id_l, self.ADDR_PRESENT_POSITION, self.LEN_PRESENT_POSITION)
        
        vel_raw_r = self.groupBulkRead.getData(id_r, self.ADDR_PRESENT_VELOCITY, self.LEN_PRESENT_VELOCITY)
        pos_raw_r = self.groupBulkRead.getData(id_r, self.ADDR_PRESENT_POSITION, self.LEN_PRESENT_POSITION)
        
        vel_raw_l = decode_signed_32(vel_raw_l)
        pos_raw_l = decode_signed_32(pos_raw_l)
        rpm_l = vel_raw_l / self.RPM_TO_VALUE_SCALE

        vel_raw_r = decode_signed_32(vel_raw_r)
        pos_raw_r = decode_signed_32(pos_raw_r)
        rpm_r = vel_raw_r / self.RPM_TO_VALUE_SCALE

        return rpm_l, rpm_r, pos_raw_l, pos_raw_r
