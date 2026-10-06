#!/usr/bin/env python3
"""D-476 sim-only shims for wall-clock mode (d476_real.launch.py, run_sim.sh ENFORCE=1).

1. Restamp: scan_gz, odom_gz, camera/front_gz (Gazebo, sim stamps) -> scan, odom, camera/front
   with stamp + (wall now - latest /clock). Content unchanged except scan range_max 12 -> 40 m:
   CORE's safety worker (control/sensing/lidar.py is_robot_scan) keeps only scans with an epoch
   stamp, >= 500 beams and range_max >= 20 m, the device C1 shape.
2. IR/IMU stand-ins (Gazebo has neither), 20 Hz: ir_sensor/range = [2000, 2000, 2000] (floor;
   cliff_mode low threshold 800) and imu_raw = level body at rest. Synthetic: the floor half of
   the D-468 motion proof is NOT tested in sim.
"""
import time

import rclpy
from nav_msgs.msg import Odometry
from rclpy.qos import qos_profile_sensor_data
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import Image, Imu, LaserScan
from std_msgs.msg import UInt16MultiArray


def main():
    rclpy.init()
    node = rclpy.create_node('d476_sim_wall_shims')
    offset = [None]

    def on_clock(m):
        offset[0] = time.time() - (m.clock.sec + m.clock.nanosec*1e-9)

    def restamp(msg):
        t = msg.header.stamp.sec + msg.header.stamp.nanosec*1e-9 + offset[0]
        msg.header.stamp.sec, msg.header.stamp.nanosec = int(t), int((t % 1)*1e9)
        return msg

    node.create_subscription(Clock, 'clock', on_clock, 10)
    for kind, src, dst, qos, fix in (
            (LaserScan, 'scan_gz', 'scan', qos_profile_sensor_data, lambda m: setattr(m, 'range_max', 40.0)),
            (Odometry, 'odom_gz', 'odom', 10, None),
            (Image, 'camera/front_gz', 'camera/front', qos_profile_sensor_data, None)):
        pub = node.create_publisher(kind, dst, 10)  # reliable: matches either subscriber kind

        def cb(msg, pub=pub, fix=fix):
            if offset[0] is None:
                return
            if fix:
                fix(msg)
            pub.publish(restamp(msg))

        node.create_subscription(kind, src, cb, qos)

    ir = node.create_publisher(UInt16MultiArray, 'ir_sensor/range', qos_profile_sensor_data)
    imu = node.create_publisher(Imu, 'imu_raw', qos_profile_sensor_data)

    def tick():
        ir.publish(UInt16MultiArray(data=[2000, 2000, 2000]))
        msg = Imu()
        msg.header.stamp = node.get_clock().now().to_msg()
        msg.header.frame_id = 'imu_link'
        msg.linear_acceleration.z = 9.81
        msg.orientation.w = 1.0
        imu.publish(msg)

    node.create_timer(0.05, tick)
    rclpy.spin(node)


if __name__ == '__main__':
    main()
