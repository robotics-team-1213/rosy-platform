#!/usr/bin/python3
"""ExecStopPost for rosy-io and rosy-navigation: write torque 0 to both wheels.

D-986 begin demands torque off after the stop. Bringup normally does it on exit,
but a repeat SIGINT can abort that (geg6 2026-11-09), so the unit repeats it.
Write-only; a failure is logged and never fails the stop.
"""
import sys

try:
    from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler
except ImportError:  # -I hides user paths; fall back to the release's copy
    sys.path.insert(0, "/opt/rosy/current/install/lib/python3.12/site-packages")
    from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler

DEVICE, BAUDRATE, ADDR_TORQUE_ENABLE, WHEEL_IDS = "/dev/rosy-motor", 1_000_000, 64, (1, 2)


def main() -> int:
    try:
        port = PortHandler(DEVICE)
        opened = port.openPort() and port.setBaudRate(BAUDRATE)
    except Exception as error:  # the SDK raises SerialException for a missing device
        print(f"FAIL torque-off: {error}", file=sys.stderr)
        return 0
    if not opened:
        print(f"FAIL torque-off: cannot open {DEVICE}", file=sys.stderr)
        return 0
    try:
        packet = PacketHandler(2.0)
        for motor_id in WHEEL_IDS:
            comm, err = packet.write1ByteTxRx(port, motor_id, ADDR_TORQUE_ENABLE, 0)
            ok = comm == COMM_SUCCESS and err == 0
            print(f"{'ok' if ok else 'FAIL'} torque-off id {motor_id} comm {comm} err {err}",
                  file=None if ok else sys.stderr)
    except Exception as error:
        print(f"FAIL torque-off: {error}", file=sys.stderr)
    finally:
        port.closePort()
    return 0


if __name__ == "__main__":
    sys.exit(main())
