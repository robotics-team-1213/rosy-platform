"""Rig-only /clock relay (D-185 R6): Gazebo /clock throttled to RIG_CLOCK_HZ messages per wall second.

Gazebo publishes /clock on every physics step (about 265 messages per wall second at 0.3x in
the calibration rig), and every rig node wakes for each one. ros_gz_bridge 1.0.22 cannot
throttle, so this subscribes through gz-transport with SubscribeOptions.msgs_per_sec and
republishes each kept sample on ROS /clock. The sim clock then advances in steps of about
real-time factor / RIG_CLOCK_HZ seconds; values are copied, never interpolated.

Usage (from run_track260905.sh): python3 tools/gz/clock_relay.py <messages_per_second>
Restricted to the isolated rig domain; never a robot entry point.
"""
import os
import sys


def relay_rate(value):
    """A positive whole number of messages per wall second."""
    text = str(value).strip()
    if not text.isdigit() or int(text) <= 0:
        raise ValueError(f'RIG_CLOCK_HZ must be a positive integer, not {value!r}')
    return int(text)


def to_ros_clock(gz_clock, ros_clock_type):
    """Copy Gazebo's sim time into a rosgraph_msgs/Clock without conversion loss."""
    message = ros_clock_type()
    message.clock.sec, message.clock.nanosec = int(gz_clock.sim.sec), int(gz_clock.sim.nsec)
    return message


def main(argv):
    if os.environ.get('ROS_DOMAIN_ID') != '227' or os.environ.get('GZ_PARTITION') != 'pinky_calmap227':
        raise RuntimeError('The clock relay is restricted to the isolated rig domain')
    rate = relay_rate(argv[1])
    import rclpy
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from rosgraph_msgs.msg import Clock
    from gz.msgs10.clock_pb2 import Clock as GzClock
    from gz.transport13 import Node as GzNode, SubscribeOptions
    rclpy.init()
    node = rclpy.create_node('rig_clock_relay')
    publisher = node.create_publisher(Clock, '/clock', QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE))
    options = SubscribeOptions()
    options.msgs_per_sec = rate
    gazebo = GzNode()
    if not gazebo.subscribe(GzClock, '/clock', lambda msg: publisher.publish(to_ros_clock(msg, Clock)), options):
        raise RuntimeError('Could not subscribe to Gazebo /clock')
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main(sys.argv)
