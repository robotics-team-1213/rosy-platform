#!/usr/bin/env python3
"""Gazebo stand-in for Pinky's IR ADC node (ir_sensor/range, UInt16MultiArray [left, mid, right]).

Each channel is a one-ray gpu_lidar pointing down from the URDF IR link (description
rosy_gz.urdf.xacro, ir_l/ir_mid/ir_r_link at 0.013 m above the floor). The ray decides only
whether floor is under the sensor: floor within FLOOR_MAX_M reads FLOOR_RAW (well above the
cliff_clear_raw 1500 of cliff_mode low), no floor reads CLIFF_RAW. Reflectance (tape vs carpet)
is not modelled, so this feeds the cliff/floor evidence, never IR line following.
Started only by launch_sim.launch.xml sim_sensors:=true.
"""
import math

FLOOR_RAW = 2000
CLIFF_RAW = 0
FLOOR_MAX_M = 0.05  # the IR emitters sit 0.013 m above the floor; a drop past 5 cm is a cliff
CHANNELS = ('left', 'mid', 'right')


def ir_raw(ranges):
    """[left, mid, right] floor distances (m; None = no reading yet) -> device-shaped ADC values."""
    return [FLOOR_RAW if r is not None and math.isfinite(r) and r <= FLOOR_MAX_M else CLIFF_RAW
            for r in ranges]


def main():
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import LaserScan
    from std_msgs.msg import UInt16MultiArray

    rclpy.init()
    node = rclpy.create_node('sim_ir_floor')
    latest = {name: None for name in CHANNELS}
    pub = node.create_publisher(UInt16MultiArray, 'ir_sensor/range', qos_profile_sensor_data)

    def on_ray(name, msg):
        latest[name] = min(msg.ranges) if msg.ranges else None
        if name == 'mid':  # one ADC frame per mid ray, like the device's one read of all three
            pub.publish(UInt16MultiArray(data=ir_raw([latest[c] for c in CHANNELS])))

    for name in CHANNELS:
        node.create_subscription(LaserScan, f'ir_sim/{name}',
                                 lambda msg, name=name: on_ray(name, msg), qos_profile_sensor_data)
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
