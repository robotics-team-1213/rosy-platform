#!/usr/bin/env python3
"""Gazebo stand-in for the robot's IR ADC node (ir_sensor/range, UInt16MultiArray [left, mid, right]).

Each channel is a one-ray gpu_lidar pointing down from the URDF IR link (description
rosy_gz.urdf.xacro, ir_l/ir_mid/ir_r_link at 0.013 m above the floor). The ray decides only
whether floor is under the sensor: floor within FLOOR_MAX_M reads FLOOR_RAW (well above the
cliff_clear_raw 1500 of cliff_mode low), no floor reads CLIFF_RAW. Reflectance (tape vs carpet)
is not modelled, so this feeds the cliff/floor evidence, never IR line following.
Started only by launch_sim.launch.xml sim_sensors:=true.
"""
import math

FLOOR_RAW = 2000
# A valid low reading, not 0: the safety worker (safety/hazard.py on_ir) takes only 0 < v < 4000
# as valid IR, and cliff_mode low trips below cliff_raw_max 800 (safety/node.py default).
CLIFF_RAW = 100
FLOOR_MAX_M = 0.05  # the IR emitters sit 0.013 m above the floor; a drop past 5 cm is a cliff
# Published order = the device's: ir_adc_node.py sends [ch2, ch1, ch0] = robot left, centre,
# right (sensing/perception/ir_calibration.py CHANNELS).
CHANNELS = ('left', 'mid', 'right')
RAY_PERIOD_NS = 50_000_000  # The three URDF rays run at 20 Hz.


def ir_raw(ranges):
    """[left, mid, right] floor distances (m; None = no reading yet) -> device-shaped ADC values.

    None until every channel has a reading: a frame never stands in for an unseen sensor.
    """
    if any(r is None for r in ranges):
        return None
    return [FLOOR_RAW if math.isfinite(r) and r <= FLOOR_MAX_M else CLIFF_RAW for r in ranges]


def main():
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import LaserScan
    from std_msgs.msg import UInt16MultiArray

    rclpy.init()
    node = rclpy.create_node('sim_ir_floor')
    latest = {name: None for name in CHANNELS}
    published_ns = -1
    pub = node.create_publisher(UInt16MultiArray, 'ir_sensor/range', qos_profile_sensor_data)

    def on_ray(name, msg):
        stamp = msg.header.stamp
        if stamp.sec < 0 or not 0 <= stamp.nanosec < 1_000_000_000:
            latest[name] = None
            return
        latest[name] = (stamp.sec * 1_000_000_000 + stamp.nanosec,
                        min(msg.ranges) if msg.ranges else None)

    def publish_frame():
        nonlocal published_ns
        if any(latest[c] is None for c in CHANNELS):
            return
        samples = [latest[c] for c in CHANNELS]
        stamp = samples[0][0]
        # Wait for a complete physics frame and /clock; never refresh old ray evidence.
        if (any(sample[0] != stamp for sample in samples) or stamp <= published_ns
                or not 0 <= node.get_clock().now().nanoseconds - stamp <= RAY_PERIOD_NS):
            return
        frame = ir_raw([sample[1] for sample in samples])
        if frame is not None:
            pub.publish(UInt16MultiArray(data=frame))
            published_ns = stamp

    for name in CHANNELS:
        node.create_subscription(LaserScan, f'ir_sim/{name}',
                                 lambda msg, name=name: on_ray(name, msg), qos_profile_sensor_data)
    node.create_timer(RAY_PERIOD_NS / 1e9, publish_frame)
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
