#!/usr/bin/env python3
"""Gazebo stand-in for the Pinky battery node (``battery/voltage``, std_msgs/Float32, 1 Hz).

Gazebo has no pack. Without this publisher a SIM CORE reports battery evidence ``missing`` and Fleet
refuses every trip start (TRIP_BATTERY_UNCONFIRMED). The sim pack sits mid-curve and below the
charger clamp, so it reads fresh, ``ok`` and not charging. It is a constant: no discharge is modelled.
"""

SIM_PACK_V = 7.6   # 2S pack, mid curve; at or above 8.40 V the curve clamps to 100 % (a charger's reading)
PERIOD_S = 1.0


def main():
    import rclpy
    from std_msgs.msg import Float32

    rclpy.init()
    node = rclpy.create_node('sim_battery')
    pub = node.create_publisher(Float32, 'battery/voltage', 10)
    node.create_timer(PERIOD_S, lambda: pub.publish(Float32(data=SIM_PACK_V)))
    rclpy.spin(node)


if __name__ == '__main__':
    main()
