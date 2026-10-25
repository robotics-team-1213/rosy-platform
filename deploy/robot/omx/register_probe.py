#!/usr/bin/env python3
"""Read six confirmed OMX follower motors without configuring or enabling them."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess


def read_packet_allowed(packet):
    packet = bytes(packet)
    if (len(packet) < 10 or packet[:4] != b"\xff\xff\xfd\x00"
            or packet[4] not in range(11, 17)
            or int.from_bytes(packet[5:7], "little") != len(packet) - 7):
        return False
    return ((packet[7] == 1 and len(packet) == 10)
            or (packet[7] == 2 and len(packet) == 14
                and packet[8:12] == b"\x00\x00\x93\x00"))


def readonly_writer(write):
    def guarded(packet):
        if not read_packet_allowed(packet):
            raise ValueError("Only unicast PING and READ(0,147) for IDs 11..16 are allowed")
        return write(packet)
    return guarded


def decode_registers(model, data):
    # Only the control tables inspected in the pinned vendor source are supported.
    if model not in (1060, 1200) or len(data) != 147:
        raise ValueError("Unsupported model or incomplete register response")
    data = bytes(data)
    def value(address, length=1, signed=False):
        return int.from_bytes(data[address:address + length], "little", signed=signed)
    return {
        "firmware": value(6), "operating_mode": value(11), "drive_mode": value(10),
        "torque_enabled": value(64), "hardware_error": value(70),
        "position_raw": value(132, 4, True), "velocity_raw": value(128, 4, True),
        "min_position_raw": value(52, 4), "max_position_raw": value(48, 4),
        "velocity_limit_raw": value(44, 4), "homing_offset_raw": value(20, 4, True),
        "goal_position_raw": value(116, 4, True),
        # XL430-W250 (1060) has no Current Limit / Goal Current registers.
        "goal_current_raw": value(102, 2, True) if model == 1200 else None,
        "profile_acceleration_raw": value(108, 4), "profile_velocity_raw": value(112, 4),
        "current_limit_raw": value(38, 2) if model == 1200 else None,
        "pwm_limit_raw": value(36, 2),
        "present_pwm_raw": value(124, 2, True), "temperature_limit": value(31),
        "min_voltage_raw": value(34, 2), "max_voltage_raw": value(32, 2),
        "bus_watchdog_raw": value(98, 1, True), "position_p_gain_raw": value(84, 2),
        "position_i_gain_raw": value(82, 2), "position_d_gain_raw": value(80, 2),
        "voltage_raw": value(144, 2), "temperature": value(146),
    }


def check_exclusive_owner(device, pid):
    users = subprocess.run(["fuser", str(device)], capture_output=True, text=True, timeout=5)
    if users.returncode != 0 or users.stdout.split() != [str(pid)]:
        raise RuntimeError("Serial device has another owner or ownership is unverified")


@contextmanager
def open_readonly_port(device):
    import fcntl
    import termios
    import serial
    from dynamixel_sdk import PortHandler

    path = Path(device)
    if path.parent != Path("/dev/serial/by-id") or not path.is_symlink():
        raise ValueError("A physically confirmed /dev/serial/by-id symlink is required")
    resolved = path.resolve(strict=True)
    users = subprocess.run(["fuser", str(resolved)], capture_output=True, text=True, timeout=5)
    if users.returncode != 1 or users.stdout.strip() or users.stderr.strip():
        raise RuntimeError("Serial device is busy or its ownership could not be checked")
    port = PortHandler(str(resolved))
    port.ser = serial.Serial(port=None, baudrate=1000000, timeout=0, exclusive=True)
    port.ser.port = str(resolved)
    # Avoid the SDK open/reset path and deassert reset-related control lines before open.
    port.ser.dtr = False
    port.ser.rts = False
    port.writePort = readonly_writer(port.ser.write)
    try:
        port.ser.open()
        fcntl.ioctl(port.ser.fileno(), termios.TIOCEXCL)
        # TIOCEXCL blocks new opens, but does not evict an opener racing the first check.
        check_exclusive_owner(resolved, os.getpid())
        port.is_open = True
        port.tx_time_per_byte = .01
        yield port
    finally:
        port.ser.close()


def read_motors(port, *, allow_fault=False):
    from dynamixel_sdk import PacketHandler, COMM_SUCCESS
    packet = PacketHandler(2.0)
    rows = []
    for motor_id in range(11, 17):
        model, comm, error = packet.ping(port, motor_id)
        ping_alert = error == 128 and allow_fault
        if comm != COMM_SUCCESS or (error and not ping_alert):
            raise RuntimeError(f"Motor {motor_id}: ping failed ({comm}, {error})")
        if model not in (1060, 1200):
            raise ValueError(f"Motor {motor_id}: unsupported model {model}")
        data, comm, error = packet.readTxRx(port, motor_id, 0, 147)
        read_alert = error == 128 and allow_fault
        if comm != COMM_SUCCESS or (error and not read_alert):
            raise RuntimeError(f"Motor {motor_id}: read failed ({comm}, {error})")
        row = {"id": motor_id, "model_number": model, **decode_registers(model, data)}
        if (ping_alert or read_alert) and (model != 1060 or not row['hardware_error']):
            raise RuntimeError(f'Motor {motor_id}: unconfirmed hardware alert')
        rows.append(row)
    return rows


def collect(device):
    with open_readonly_port(device) as port:
        return read_motors(port)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True, help="physically confirmed follower by-id path")
    args = parser.parse_args(argv)
    report = {"scope": "readonly_register_snapshot", "motion_admitted": False}
    try:
        report["motors"] = collect(args.device)
        report["snapshot_complete"] = True
    except Exception as error:
        report.update(snapshot_complete=False, error=str(error))
    print(json.dumps(report))
    return 0 if report["snapshot_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
