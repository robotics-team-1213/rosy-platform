"""Read-only DYNAMIXEL UART commissioning probe.

The probe intentionally performs ping and torque-state reads only. It never
enables torque, changes an operating mode, or writes a goal velocity.
"""

from __future__ import annotations

import argparse
import sys

from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler


ADDR_TORQUE_ENABLE = 64
PROTOCOL_VERSION = 2.0


def _motor_id(value: str) -> int:
    parsed = int(value)
    if not 0 <= parsed <= 252:
        raise argparse.ArgumentTypeError("motor ID must be between 0 and 252")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ping DYNAMIXEL motors and read torque state without writes.",
    )
    parser.add_argument("--device", default="/dev/rosy-motor")
    parser.add_argument("--baudrate", type=int, default=1_000_000)
    parser.add_argument("--ids", type=_motor_id, nargs="+", default=[1, 2])
    args = parser.parse_args(argv)
    if not args.device.startswith("/dev/"):
        parser.error("--device must be an absolute /dev path")
    if args.baudrate <= 0:
        parser.error("--baudrate must be positive")
    if len(args.ids) != len(set(args.ids)):
        parser.error("--ids must not contain duplicates")
    return args


def probe(device: str, baudrate: int, motor_ids: list[int]) -> bool:
    port = PortHandler(device)
    packet = PacketHandler(PROTOCOL_VERSION)
    if not port.openPort():
        print(f"FAIL UART unable to open {device}", file=sys.stderr)
        return False
    try:
        if not port.setBaudRate(baudrate):
            print(f"FAIL UART unable to set {baudrate} baud", file=sys.stderr)
            return False

        all_ok = True
        for motor_id in motor_ids:
            _model_number, comm_result, packet_error = packet.ping(port, motor_id)
            if comm_result != COMM_SUCCESS or packet_error != 0:
                print(
                    f"FAIL DXL id={motor_id} ping communication={comm_result} "
                    f"device_error={packet_error}",
                    file=sys.stderr,
                )
                all_ok = False
                continue

            torque_enabled, comm_result, packet_error = packet.read1ByteTxRx(
                port,
                motor_id,
                ADDR_TORQUE_ENABLE,
            )
            if comm_result != COMM_SUCCESS or packet_error != 0:
                print(
                    f"FAIL DXL id={motor_id} torque-state read communication={comm_result} "
                    f"device_error={packet_error}",
                    file=sys.stderr,
                )
                all_ok = False
            elif torque_enabled:
                print(
                    f"FAIL DXL id={motor_id} torque is already enabled; power-cycle or "
                    "stop the motor runtime before commissioning",
                    file=sys.stderr,
                )
                all_ok = False
            else:
                print(f"PASS DXL id={motor_id} responded with torque disabled")
        return all_ok
    finally:
        port.closePort()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return 0 if probe(args.device, args.baudrate, args.ids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
