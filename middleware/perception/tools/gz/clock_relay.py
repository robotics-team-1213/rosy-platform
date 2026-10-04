"""Rig-only /clock relay (D-185 R6): Gazebo /clock throttled to at most RIG_CLOCK_HZ messages per wall second.

Gazebo publishes /clock on every physics step (about 265 messages per wall second at 0.3x in
the calibration rig), and every rig node wakes for each one. ros_gz_bridge 1.0.22 cannot
throttle, so this subscribes through gz-transport with SubscribeOptions.msgs_per_sec and
republishes each kept sample on ROS /clock. gz-transport only drops messages, so the rate is
a ceiling (100 requested gave about 88 delivered), and the sim clock advances in steps of about
real-time factor / RIG_CLOCK_HZ seconds; values are copied, never interpolated.

The rate must be at least MIN_HZ_PER_RTF x the requested real-time factor, which keeps one step
at 20 ms of sim time or less: under the 50 ms control tick and lidar_guard's -0.05 s tolerance.
Strict freshness checks (safety 0 <= age <= .2) still see up to one step of lag, so an A/B must
count stale reasons in both arms.

Usage (from run_track260905.sh):
  python3 tools/gz/clock_relay.py --check <messages_per_second> <real_time_factor>   (no ROS; exit 2 if bad)
  python3 tools/gz/clock_relay.py <messages_per_second> <real_time_factor>
Restricted to the isolated rig domain; never a robot entry point.
"""
import os
import sys

MIN_HZ_PER_RTF = 50


def relay_rate(value, realtime_factor=1.):
    """A positive whole number of messages per wall second, fine enough for the requested RTF."""
    text = str(value).strip()
    if not text.isdigit() or int(text) <= 0:
        raise ValueError(f'RIG_CLOCK_HZ must be a positive integer, not {value!r}')
    floor = MIN_HZ_PER_RTF*float(realtime_factor)
    if int(text) < floor:
        raise ValueError(f'RIG_CLOCK_HZ must be at least {floor:g} at real-time factor '
                         f'{float(realtime_factor):g} (sim-time step <= 20 ms), not {int(text)}')
    return int(text)


def to_ros_clock(gz_clock, ros_clock_type):
    """Copy Gazebo's sim time into a rosgraph_msgs/Clock without conversion loss."""
    message = ros_clock_type()
    message.clock.sec, message.clock.nanosec = int(gz_clock.sim.sec), int(gz_clock.sim.nsec)
    return message


def main(argv):
    if argv[1:2] == ['--check']:
        try:
            relay_rate(argv[2], argv[3])
        except (IndexError, ValueError) as error:
            print(error if isinstance(error, ValueError) else __doc__, file=sys.stderr)
            return 2
        return 0
    if os.environ.get('ROS_DOMAIN_ID') != '227' or os.environ.get('GZ_PARTITION') != 'pinky_calmap227':
        raise RuntimeError('The clock relay is restricted to the isolated rig domain')
    rate = relay_rate(argv[1], argv[2])
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from rosgraph_msgs.msg import Clock
    from gz.msgs10.clock_pb2 import Clock as GzClock
    from gz.transport13 import Node as GzNode, SubscribeOptions
    rclpy.init()
    node = rclpy.create_node('rig_clock_relay')
    # Relative name (D-4); the rig has no namespace, so this is /clock.
    publisher = node.create_publisher(Clock, 'clock', QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE))
    stopping = []
    options = SubscribeOptions()
    options.msgs_per_sec = rate
    gazebo = GzNode()
    if not gazebo.subscribe(GzClock, '/clock',
                            lambda msg: stopping or publisher.publish(to_ros_clock(msg, Clock)), options):
        raise RuntimeError('Could not subscribe to Gazebo /clock')
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        stopping.append(True)
        gazebo.unsubscribe('/clock')
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
