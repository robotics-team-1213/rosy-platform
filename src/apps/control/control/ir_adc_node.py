#!/usr/bin/env python3
"""Publish Pinky's three IR reflectance ADC channels as sensing evidence only."""

import os
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import UInt16MultiArray

from .sensing.ir_adc import decode_adc12


I2C_SLAVE = 0x0703
CHANNEL_COMMANDS = (0x88, 0xC8, 0x98)


class _ADCReader:
    def __init__(self, interface: str, address: int) -> None:
        import fcntl

        self._fd = os.open(interface, os.O_RDWR)
        fcntl.ioctl(self._fd, I2C_SLAVE, address)

    def read_channels(self) -> list[int]:
        import fcntl

        # D-192 bus ownership: the MCU keeps one register pointer, and
        # rosylib.Battery (bringup battery_publisher) reads channel 4 of the
        # same MCU from another process. Every Rosy reader holds an exclusive
        # flock on its /dev/i2c-1 descriptor for the whole pointer-write,
        # settle, read sequence.
        values = []
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        try:
            for command in CHANNEL_COMMANDS:
                os.write(self._fd, bytes((command,)))
                time.sleep(0.006)
                values.append(decode_adc12(os.read(self._fd, 2)))
        finally:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        return [values[2], values[1], values[0]]

    def close(self) -> None:
        os.close(self._fd)


class IRADCNode(Node):
    def __init__(self) -> None:
        super().__init__('ir_adc_node')
        self.declare_parameter('interface', '/dev/i2c-1')
        self.declare_parameter('address', 0x08)
        self.declare_parameter('rate_hz', 20.0)
        self._reader = None
        self._publisher = self.create_publisher(UInt16MultiArray, 'ir_sensor/range', 10)
        rate = max(1.0, float(self.get_parameter('rate_hz').value))
        self.create_timer(1.0 / rate, self._tick)

    def _connect(self) -> bool:
        if self._reader is not None:
            return True
        try:
            self._reader = _ADCReader(
                str(self.get_parameter('interface').value),
                int(self.get_parameter('address').value),
            )
            self.get_logger().info('IR ADC connected')
            return True
        except (OSError, ValueError) as exc:
            self.get_logger().warning(
                f'IR ADC unavailable: {exc}', throttle_duration_sec=2.0)
            return False

    def _tick(self) -> None:
        if not self._connect():
            return
        try:
            sample = self._reader.read_channels()
        except (OSError, ValueError) as exc:
            self.get_logger().warning(
                f'IR ADC read failed: {exc}', throttle_duration_sec=2.0)
            try:
                self._reader.close()
            except OSError:
                pass
            self._reader = None
            return
        self._publisher.publish(UInt16MultiArray(data=sample))

    def destroy_node(self):
        if self._reader is not None:
            try:
                self._reader.close()
            except OSError:
                pass
            self._reader = None
        super().destroy_node()


def main() -> None:
    rclpy.init()
    node = IRADCNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
