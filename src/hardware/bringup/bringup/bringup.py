#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
import math
import time

from geometry_msgs.msg import Twist, TransformStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import JointState
from tf2_ros import TransformBroadcaster
from tf_transformations import quaternion_from_euler
from std_msgs.msg import Bool, Float32
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

from .command_deadman import CommandDeadman
from .dynamixel_driver import (
    DynamixelDriver,
    validate_motor_ids,
    validate_profile_acceleration,
    wrapped_encoder_delta,
)
from .motor_control import (
    CommandStatus,
    DriveGeometry,
    DriveLimits,
    MotorController,
)
from .pinky_pro_adapter import PinkyProAdapter

TWIST_SUB_TOPIC_NAME = "cmd_vel"
ODOM_PUB_TOPIC_NAME = "odom"
JOINT_PUB_TOPIC_NAME = "joint_states"
DEFAULT_ODOM_FRAME_ID = "odom"
DEFAULT_ODOM_CHILD_FRAME_ID = "base_footprint"

DEFAULT_SERIAL_PORT_NAME = "/dev/ttyAMA4"
DEFAULT_BAUDRATE = 1000000
DEFAULT_DYNAMIXEL_IDS = [1, 2]  # [왼쪽 바퀴 ID, 오른쪽 바퀴 ID]

JOINT_NAME_WHEEL_L = "left_wheel_joint"
JOINT_NAME_WHEEL_R = "right_wheel_joint"

PULSE_PER_ROT = 4096 
RPM2RAD = 2 * math.pi / 60

BATTERY_VOLTAGE_TOPIC = "battery/voltage"
MOTOR_READY_TOPIC = "motor/ready"
LOW_BATTERY_THRESHOLD = 6.8

_MOTOR_READY_QOS = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
)

class Rosy(Node):
    def __init__(self):
        super().__init__('bringup')
        self.is_initialized = False
        
        self.get_logger().info('Initializing Rosy Bringup Node with Dynamixel...')
        
        self.declare_parameter('wheel_radius', 0.027)
        self.declare_parameter('wheel_separation', 0.0961)
        self.declare_parameter('cmd_vel_timeout_s', 0.5)
        self.declare_parameter('frame_prefix', '')  # P0-3 (A-2): namespace 기반 프레임 식별
        self.declare_parameter('motor_device', DEFAULT_SERIAL_PORT_NAME)
        self.declare_parameter('motor_baudrate', DEFAULT_BAUDRATE)
        self.declare_parameter('motor_ids', DEFAULT_DYNAMIXEL_IDS)
        self.declare_parameter('max_linear_mps', 0.20)
        self.declare_parameter('max_angular_rps', 0.80)
        self.declare_parameter('max_wheel_rpm', 100.0)
        self.declare_parameter('motor_profile_acceleration', 200)
        # D-192 no-motion mode: false keeps motor torque off, never subscribes
        # cmd_vel and never reports motor/ready, while odometry, joint states
        # and TF still come from the encoders. Not a board parameter, so it
        # stays outside the PinkyProAdapter mapping.
        self.declare_parameter('drive_enabled', True)
        drive_enabled = self.get_parameter('drive_enabled').value
        if not isinstance(drive_enabled, bool):
            raise ValueError('drive_enabled must be a boolean')
        self.drive_enabled = drive_enabled

        # Keep the board-specific boundary explicit.  This validates the
        # complete ROS parameter set before any SDK object opens a UART; the
        # existing driver validations remain as a second, device-side guard.
        self.pinky_pro_adapter = PinkyProAdapter.from_mapping({
            'wheel_radius': self.get_parameter('wheel_radius').value,
            'wheel_separation': self.get_parameter('wheel_separation').value,
            'cmd_vel_timeout_s': self.get_parameter('cmd_vel_timeout_s').value,
            'frame_prefix': self.get_parameter('frame_prefix').value,
            'motor_device': self.get_parameter('motor_device').value,
            'motor_baudrate': self.get_parameter('motor_baudrate').value,
            'motor_ids': self.get_parameter('motor_ids').value,
            'max_linear_mps': self.get_parameter('max_linear_mps').value,
            'max_angular_rps': self.get_parameter('max_angular_rps').value,
            'max_wheel_rpm': self.get_parameter('max_wheel_rpm').value,
            'motor_profile_acceleration': self.get_parameter(
                'motor_profile_acceleration'
            ).value,
        })

        adapter_params = self.pinky_pro_adapter.parameters
        self.wheel_radius = float(adapter_params['wheel_radius'])
        self.wheel_separation = float(adapter_params['wheel_separation'])
        self.cmd_vel_timeout_s = float(adapter_params['cmd_vel_timeout_s'])
        self.command_deadman = CommandDeadman(self.cmd_vel_timeout_s)
        self.motor_device = str(adapter_params['motor_device'])
        self.motor_baudrate = int(adapter_params['motor_baudrate'])
        raw_motor_ids = list(self.get_parameter('motor_ids').value)
        self.motor_ids = list(validate_motor_ids(raw_motor_ids))
        self.max_linear_mps = float(adapter_params['max_linear_mps'])
        self.max_angular_rps = float(adapter_params['max_angular_rps'])
        self.max_wheel_rpm = float(adapter_params['max_wheel_rpm'])
        raw_profile_acceleration = self.get_parameter(
            'motor_profile_acceleration'
        ).value
        self.motor_profile_acceleration = validate_profile_acceleration(
            raw_profile_acceleration
        )
        if not self.motor_device.startswith('/dev/'):
            raise ValueError('motor_device must be an absolute /dev path')
        if self.motor_baudrate <= 0:
            raise ValueError('motor_baudrate must be positive')
        frame_prefix = str(adapter_params['frame_prefix'])
        if frame_prefix and not frame_prefix.endswith('/'):
            frame_prefix += '/'
        self.odom_frame_id = f'{frame_prefix}{DEFAULT_ODOM_FRAME_ID}'
        self.odom_child_frame_id = f'{frame_prefix}{DEFAULT_ODOM_CHILD_FRAME_ID}'
        self.get_logger().info(f'Frames: {self.odom_frame_id} -> {self.odom_child_frame_id}')
        
        self.get_logger().info(f'Wheel radius: {self.wheel_radius}')
        self.get_logger().info(f'Wheel separation: {self.wheel_separation}')
        self.get_logger().info(f'cmd_vel deadman: {self.cmd_vel_timeout_s:.3f}s')
        self.get_logger().info(
            f'Motor transport: {self.motor_device} at {self.motor_baudrate} baud, '
            f'IDs {self.motor_ids}'
        )
        
        self.circumference = 2 * math.pi * self.wheel_radius
        self.driver = DynamixelDriver(
            self.motor_device,
            self.motor_baudrate,
            self.motor_ids,
            max_rpm=self.max_wheel_rpm,
        )
        self.motor_controller = MotorController(
            DriveGeometry(
                wheel_radius_m=self.wheel_radius,
                wheel_separation_m=self.wheel_separation,
            ),
            DriveLimits(
                max_linear_mps=self.max_linear_mps,
                max_angular_rps=self.max_angular_rps,
                max_wheel_rpm=self.max_wheel_rpm,
            ),
            self.driver.set_double_rpm,
        )
        self.motor_ready_pub = self.create_publisher(Bool, MOTOR_READY_TOPIC, _MOTOR_READY_QOS)
        # Publish a latched false before opening the transport.  CORE can then
        # distinguish a discovered node that is still starting from a ready
        # adapter, and late joiners receive the current state immediately.
        self.motor_ready_pub.publish(Bool(data=False))

        try:
            self.get_logger().info('1. Opening serial port...')
            if not self.driver.begin():
                self.get_logger().error('Failed to open serial port! Shutting down.')
                raise RuntimeError('failed to open Dynamixel serial port')

            self.get_logger().info('2. Initializing motors...')
            if not self.driver.initialize_motors(
                profile_accel=self.motor_profile_acceleration,
                enable_torque=self.drive_enabled,
            ):
                self.get_logger().error('Failed to initialize motors! Shutting down.')
                raise RuntimeError('failed to initialize Dynamixel motors')

            self.get_logger().info('Waiting for motors to be ready...')
            time.sleep(1.0)

            if self.drive_enabled:
                self.get_logger().info('3. Setting initial RPM to zero...')
                if not self.driver.set_double_rpm(0, 0):
                    self.get_logger().error('Failed to set initial RPM! Shutting down.')
                    raise RuntimeError('failed to set initial zero RPM')
            else:
                self.get_logger().warn(
                    '3. Drive disabled (no-motion mode): torque stays off, '
                    'cmd_vel is not subscribed, motor/ready stays false.'
                )

            self.get_logger().info('4. Reading initial encoder values...')
            _, _, self.last_encoder_l, self.last_encoder_r = self.driver.get_feedback()
            if self.last_encoder_l is None:
                self.get_logger().error(
                    'Failed to read initial encoder position! Shutting down.'
                )
                raise RuntimeError('failed to read initial encoder position')

            self.get_logger().info(
                f'Initial Encoder read: L={self.last_encoder_l}, '
                f'R={self.last_encoder_r}. Controller is responsive.'
            )

            self.odom_pub = self.create_publisher(Odometry, ODOM_PUB_TOPIC_NAME, 10)
            self.joint_pub = self.create_publisher(JointState, JOINT_PUB_TOPIC_NAME, 10)
            self.twist_sub = None
            if self.drive_enabled:
                self.twist_sub = self.create_subscription(
                    Twist, TWIST_SUB_TOPIC_NAME, self.twist_callback, 10
                )
            self.tf_broadcaster = TransformBroadcaster(self)
            self.timer = self.create_timer(1.0 / 30.0, self.update_and_publish)

            self.battery_sub = self.create_subscription(
                Float32,
                BATTERY_VOLTAGE_TOPIC,
                self.battery_voltage_callback,
                10
            )

            self.x = 0.0
            self.y = 0.0
            self.theta = 0.0
            self.last_time = self.get_clock().now()
            self.is_initialized = True
            self.motor_ready_pub.publish(Bool(data=self.drive_enabled))
            self.get_logger().info(
                'Rosy Bringup with Dynamixel has been started successfully.'
            )
        except Exception:
            self.driver.terminate()
            raise

    def twist_callback(self, msg: Twist):
        outcome = self.motor_controller.command_twist(msg.linear.x, msg.angular.z)
        if not outcome.accepted:
            self.get_logger().error(
                f'Motor command {outcome.status.value}: {outcome.reason}'
            )
            stop_outcome = self.motor_controller.stop()
            if stop_outcome.accepted:
                self.command_deadman.mark_stopped()
            else:
                self.command_deadman.mark_stop_required()
                self.get_logger().error(
                    f'Immediate motor stop failed: {stop_outcome.reason}'
                )
            return
        if outcome.status is CommandStatus.LIMITED:
            self.get_logger().warn(
                f'Motor command LIMITED: {outcome.reason}; '
                f'applied=({outcome.plan.applied_linear_mps:.3f} m/s, '
                f'{outcome.plan.applied_angular_rps:.3f} rad/s)'
            )
        if outcome.plan.is_stop:
            self.command_deadman.mark_stopped()
        else:
            self.command_deadman.mark_command()

    def update_and_publish(self):
        if self.is_initialized and self.drive_enabled:
            # This is the adapter lease.  CORE expires it if the motor process
            # stops producing health updates, even though the topic is latched.
            # A no-motion node never offers it: CORE must not plan on motors
            # that cannot move.
            self.motor_ready_pub.publish(Bool(data=True))
        stop_result = self.command_deadman.attempt_stop(
            lambda: self.motor_controller.stop().accepted
        )
        if stop_result is True:
            self.get_logger().warn(
                "cmd_vel stream expired; driver forced both motors to zero RPM."
            )
        elif stop_result is False:
            self.get_logger().error(
                "cmd_vel stream expired but zero-RPM command failed; retrying."
            )

        current_time = self.get_clock().now()
        dt = (current_time - self.last_time).nanoseconds / 1e9
        if dt <= 0: return

        feedback = self.driver.get_feedback()
        if feedback[0] is None:
            self.get_logger().warn("Failed to read motor data. Skipping update cycle.")
            return
        rpm_l, rpm_r, encoder_l, encoder_r = feedback

        delta_l = wrapped_encoder_delta(encoder_l, self.last_encoder_l)
        delta_r = -wrapped_encoder_delta(encoder_r, self.last_encoder_r)
        
        self.last_encoder_l = encoder_l
        self.last_encoder_r = encoder_r

        dist_l = (delta_l / PULSE_PER_ROT) * self.circumference
        dist_r = (delta_r / PULSE_PER_ROT) * self.circumference

        delta_distance = (dist_r + dist_l) / 2.0
        delta_theta = (dist_r - dist_l) / self.wheel_separation
        
        self.theta += delta_theta
        self.x += delta_distance * math.cos(self.theta)
        self.y += delta_distance * math.sin(self.theta)
        
        v_x = delta_distance / dt if dt > 0 else 0.0
        vth = delta_theta / dt if dt > 0 else 0.0

        self._publish_tf(current_time)
        self._publish_odometry(current_time, v_x, vth)
        self._publish_joint_states(current_time, rpm_l, rpm_r)

        self.last_time = current_time

    def _publish_tf(self, current_time):
        t = TransformStamped()
        t.header.stamp = current_time.to_msg()
        t.header.frame_id = self.odom_frame_id
        t.child_frame_id = self.odom_child_frame_id
        t.transform.translation.x = self.x
        t.transform.translation.y = self.y
        q = quaternion_from_euler(0, 0, self.theta)
        t.transform.rotation.x, t.transform.rotation.y, t.transform.rotation.z, t.transform.rotation.w = q
        self.tf_broadcaster.sendTransform(t)

    def _publish_odometry(self, current_time, v_x, vth):
        odom_msg = Odometry()
        odom_msg.header.stamp = current_time.to_msg()
        odom_msg.header.frame_id = self.odom_frame_id
        odom_msg.child_frame_id = self.odom_child_frame_id
        odom_msg.pose.pose.position.x, odom_msg.pose.pose.position.y = self.x, self.y
        q = quaternion_from_euler(0, 0, self.theta)
        odom_msg.pose.pose.orientation.x, odom_msg.pose.pose.orientation.y, odom_msg.pose.pose.orientation.z, odom_msg.pose.pose.orientation.w = q
        odom_msg.twist.twist.linear.x, odom_msg.twist.twist.angular.z = v_x, vth
        self.odom_pub.publish(odom_msg)

    def _publish_joint_states(self, current_time, rpm_l, rpm_r):
        joint_msg = JointState()
        joint_msg.header.stamp = current_time.to_msg()
        joint_msg.name = [JOINT_NAME_WHEEL_L, JOINT_NAME_WHEEL_R]
        
        pos_l_rad = (self.last_encoder_l / PULSE_PER_ROT) * (2 * math.pi)
        pos_r_rad = (self.last_encoder_r / PULSE_PER_ROT) * (2 * math.pi)
        joint_msg.position = [pos_l_rad, pos_r_rad]
        joint_msg.velocity = [rpm_l * RPM2RAD, rpm_r * RPM2RAD]

        self.joint_pub.publish(joint_msg)

    def battery_voltage_callback(self, msg):
        self.current_voltage = msg.data
        
        if self.current_voltage is None:
            self.get_logger().warn("Battery voltage data has not been received yet.")
        elif self.current_voltage <= LOW_BATTERY_THRESHOLD:
            self.get_logger().warn(
                f"!!! LOW BATTERY WARNING !!! Voltage: {self.current_voltage:.2f}V. Please charge the robot."
            )


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = Rosy()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            if getattr(node, 'motor_ready_pub', None) is not None:
                node.motor_ready_pub.publish(Bool(data=False))
            node.driver.terminate()
            node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
