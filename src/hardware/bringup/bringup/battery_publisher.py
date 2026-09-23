import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32
# Rosy-owned stand-in for the vendor's closed pinkylib.Battery (D-192).
from rosylib import Battery

class BatteryPublisher(Node):
    def __init__(self):
        super().__init__('battery_publisher')
        
        self.battery = Battery()

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

    # Fail-closed (sensor_adc pattern): a failed bus transaction publishes
    # nothing. CORE judges freshness by arrival; a zero would read as empty.
    def percentage_callback(self):
        try:
            value = float(self.battery.battery_percentage())
        except OSError as exc:
            self.get_logger().warning(
                f'battery ADC read failed: {exc}', throttle_duration_sec=10.0)
            return
        pct_msg = Float32()
        pct_msg.data = value
        self.percentage_publisher.publish(pct_msg)

    def voltage_callback(self):
        try:
            value = float(self.battery.get_voltage())
        except OSError as exc:
            self.get_logger().warning(
                f'battery ADC read failed: {exc}', throttle_duration_sec=10.0)
            return
        volt_msg = Float32()
        volt_msg.data = value
        self.voltage_publisher.publish(volt_msg)

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
