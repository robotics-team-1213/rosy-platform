"""Subject: the ROS edge of SafetyNode (D-171 track 1). Split out of node.py (D-766).

The ROS-free safety mixins (bumper, hazard, gate, scale, obstacles) call these
methods for the clock, TF lookups, fresh messages and the drive-sign parameter
write; SafetyNode inherits them, so the mixins still import no ROS.
"""
from geometry_msgs.msg import Twist
from rclpy.time import Time
from std_msgs.msg import Bool, Float32, String
from tf2_ros import TransformException


class RosEdges:
    def now(self):
        return self.get_clock().now()

    def stamp_time(self, stamp):
        """Time edge for the ROS-free safety mixins (D-171): header stamp -> rclpy Time."""
        return Time.from_msg(stamp)

    def lookup_base_from(self, frame_id, stamp):
        """TF edge (D-171): base_link<-frame at the stamp. A TF failure becomes ValueError
        with the same text, so the mixin's single except keeps its warning unchanged."""
        try:
            return self.lidar_tf.lookup_transform('base_link', frame_id, Time.from_msg(stamp))
        except TransformException as error:
            raise ValueError(str(error)) from error

    def lookup_odom_base(self):
        """TF edge for the ROS-free safety mixins (D-171): latest odom<-base_link, None if unavailable."""
        try:
            return self.lidar_tf.lookup_transform('odom', 'base_link', Time())
        except TransformException:
            return None

    def zero_twist(self):
        """Message edge for the ROS-free safety mixins (D-171): a fresh all-zero Twist."""
        return Twist()

    def set_linear_sign_parameter(self, value):
        """Message edge for the ROS-free gate mixin (D-171)."""
        from rclpy.parameter import Parameter
        self.set_parameters([Parameter('cmd_linear_sign', Parameter.Type.DOUBLE, value)])

    def publish_text(self, publisher, data):
        """Message edge for the ROS-free safety mixins (D-171)."""
        publisher.publish(String(data=data))

    def publish_bool(self, publisher, value):
        """Message edge for the ROS-free safety mixins (D-171)."""
        publisher.publish(Bool(data=value))

    def publish_float(self, publisher, value):
        """Message edge for the ROS-free safety mixins (D-171)."""
        publisher.publish(Float32(data=value))

    def age(self, stamp):
        if stamp is None:
            return 1e9
        return (self.now() - stamp).nanoseconds / 1e9
