import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32
# Rosy-owned stand-in for the vendor's closed pinkylib.Battery (D-192).
from rosylib import Battery


class BatteryPublisher(Node):
    def __init__(self, battery_factory=Battery):
        super().__init__('battery_publisher')

        # D-192 review: the bus may be missing at start (no /dev/i2c-1 yet, or
        # the MCU not answering). The node stays up and retries the open from
        # its timers; until then it publishes nothing (fail-closed).
        self._battery_factory = battery_factory
        self.battery = None

        self.percentage_publisher = self.create_publisher(
            Float32,
            'battery/percent',
            10
        )

        self.voltage_publisher = self.create_publisher(
            Float32,
            'battery/voltage',
            10
        )

        self.timer_period = 5.0
        self.percentage_timer = self.create_timer(self.timer_period, self.percentage_callback)
        self.voltage_timer = self.create_timer(self.timer_period, self.voltage_callback)
        self._ensure_battery()

    def _ensure_battery(self):
        if self.battery is not None:
            return True
        try:
            self.battery = self._battery_factory()
        except OSError as exc:
            self.get_logger().warning(
                f'battery ADC unavailable: {exc}; retrying every {self.timer_period:.0f} s',
                throttle_duration_sec=60.0)
            return False
        self.get_logger().info('battery ADC connected')
        return True

    def _read(self, method):
        """One reading, or None. A failed read drops the handle so it reopens."""
        if not self._ensure_battery():
            return None
        try:
            return float(getattr(self.battery, method)())
        except OSError as exc:
            self.get_logger().warning(
                f'battery ADC read failed: {exc}', throttle_duration_sec=10.0)
            try:
                self.battery.close()
            except OSError:
                pass
            self.battery = None
            return None

    # Fail-closed (sensor_adc pattern): a failed bus transaction publishes
    # nothing. CORE judges freshness by arrival; a zero would read as empty.
    def percentage_callback(self):
        value = self._read('battery_percentage')
        if value is None:
            return
        pct_msg = Float32()
        pct_msg.data = value
        self.percentage_publisher.publish(pct_msg)

    def voltage_callback(self):
        value = self._read('get_voltage')
        if value is None:
            return
        volt_msg = Float32()
        volt_msg.data = value
        self.voltage_publisher.publish(volt_msg)

    def destroy_node(self):
        if self.battery is not None:
            try:
                self.battery.close()
            except OSError:
                pass
            self.battery = None
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)

    publisher = BatteryPublisher()

    try:
        rclpy.spin(publisher)
    except KeyboardInterrupt:
        pass
    finally:
        publisher.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
