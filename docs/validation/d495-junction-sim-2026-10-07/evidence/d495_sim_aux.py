#!/usr/bin/env python3
"""D-495/D-498 SIM-only helper node (model PC; started by d495_real.launch.py).

1. Ground truth: reads the Gazebo model pose of 'rosy' (gz topic dynamic_pose/info) and
   republishes it as geometry_msgs/Pose2D on d495/gt (x, y, yaw in the world = map frame).
2. IR reflectance stand-in: sim_ir_floor.py models floor vs cliff only, so the D-491/D-498 IR
   guard would always read 'clear'. Here each IR channel is a point at the URDF IR row
   (x 0.0295, y +0.020 / 0 / -0.020 on base_link; pinky core.yaml ir_row_x_m, geometry.yaml) and
   reads TAPE_RAW when the map_v2_fleet paint raster (control PaintMap, the same STL as the world)
   is within PAINT_SPOT_M of it, else CARPET_RAW. Published as the device-shaped
   ir_sensor/range [left, mid, right] at 20 Hz (ir_adc_node rate). line_observer's IR calibration
   in d495_real.launch.py uses black = CARPET_RAW, white = TAPE_RAW. No noise, no partial spot.
3. Fault injection relays: Gazebo scan/odom arrive on scan_gz/odom_gz (d495_bridge.yaml) and are
   republished unchanged on scan/odom. A std_msgs/String on d495/pause names what to withhold:
   any of 'ir', 'scan', 'odom' (comma separated); '' resumes everything.
"""
import json
import math
import os
import subprocess
import threading

TAPE_RAW, CARPET_RAW = 2600, 600
PAINT_SPOT_M = 0.003
IR_ROW = ((0.0295, 0.020), (0.0295, 0.0), (0.0295, -0.020))  # left, mid, right


def main():
    import numpy as np
    import rclpy
    from ament_index_python.packages import get_package_share_directory
    from control.sensing.perception.paint_localizer import PaintMap
    from geometry_msgs.msg import Pose2D
    from nav_msgs.msg import Odometry
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import LaserScan
    from std_msgs.msg import String, UInt16MultiArray

    paint = PaintMap.from_bundle(os.path.join(
        get_package_share_directory('control'), 'map', 'map_v2_fleet'))
    rclpy.init()
    node = rclpy.create_node('d495_sim_aux')
    paused = set()
    gt = [None]
    node.create_subscription(String, 'd495/pause', lambda m: (
        paused.clear(), paused.update(p for p in m.data.split(',') if p),
        node.get_logger().info(f'pause {sorted(paused)}')), 10)

    for kind, src, dst, key in ((LaserScan, 'scan_gz', 'scan', 'scan'),
                                (Odometry, 'odom_gz', 'odom', 'odom')):
        pub = node.create_publisher(kind, dst, 10)
        node.create_subscription(kind, src, lambda m, pub=pub, key=key: (
            None if key in paused else pub.publish(m)), qos_profile_sensor_data)

    gt_pub = node.create_publisher(Pose2D, 'd495/gt', 10)
    ir_pub = node.create_publisher(UInt16MultiArray, 'ir_sensor/range', qos_profile_sensor_data)

    def gt_reader():
        proc = subprocess.Popen(['gz', 'topic', '-e', '-t', '/world/map_v2_fleet/dynamic_pose/info',
                                 '--json-output'], stdout=subprocess.PIPE, text=True)
        for line in proc.stdout:
            if '"rosy"' not in line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            for p in msg.get('pose', []):
                if p.get('name') == 'rosy':
                    pos, q = p.get('position', {}), p.get('orientation', {})
                    w, z, x_, y_ = (q.get(k, d) for k, d in (('w', 1.), ('z', 0.), ('x', 0.), ('y', 0.)))
                    gt[0] = (pos.get('x', 0.), pos.get('y', 0.),
                             math.atan2(2*(w*z+x_*y_), 1-2*(y_*y_+z*z)))
                    gt_pub.publish(Pose2D(x=gt[0][0], y=gt[0][1], theta=gt[0][2]))
                    break

    threading.Thread(target=gt_reader, daemon=True).start()

    def ir_tick():
        if gt[0] is None or 'ir' in paused:
            return
        x, y, yaw = gt[0]
        c, s = math.cos(yaw), math.sin(yaw)
        pts = np.array([[x+c*bx-s*by, y+s*bx+c*by] for bx, by in IR_ROW])
        d = paint.distance_at(pts)
        ir_pub.publish(UInt16MultiArray(data=[TAPE_RAW if v <= PAINT_SPOT_M else CARPET_RAW for v in d]))

    node.create_timer(0.05, ir_tick)
    rclpy.spin(node)


if __name__ == '__main__':
    main()
