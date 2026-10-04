"""Actual CORE publish method and DDS output in a network-isolated ROS test."""
import ast
from pathlib import Path
from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock, patch

try:
    import rclpy
except ImportError:
    rclpy = None

if rclpy is not None:
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from geometry_msgs.msg import Twist
    from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
    from core_features.command.manager import CommandManager, Twist as CoreTwist
    from core_features.safety.manager import SafetyManager, SpeedLimits, BatteryPolicy, SafetyDecision


@unittest.skipIf(rclpy is None, 'Requires network-isolated ROS Jazzy')
class OutputGraphTests(unittest.TestCase):
    def test_invalid_worker_command_is_published_as_zero(self):
        self.exercise(float('nan'), False, None, (0., 0.))

    def test_required_missing_policy_publishes_zero(self):
        self.exercise(.1, True, None, (0., 0.))

    def test_policy_limit_reaches_actual_publisher(self):
        def limit(request):
            return SafetyDecision(request.command_id, request.source, request.calibration_revision,
                                  request.now, request.now + .1, .04, .06, 'limit')
        self.exercise(.1, True, limit, (.04, .06))

    def test_control_obstacle_gate_reaches_motor_topic(self):
        self.exercise(.1, True, None, (0., 0.), control_obstacle=True)

    def test_control_allows_explicit_reverse_past_front_obstacle(self):
        self.exercise(-.1, True, None, (-.1, .1), control_obstacle=True)

    def test_current_slow_straight_candidate_uses_translation_geometry(self):
        self.exercise(.01, True, None, (.01, 0.), control_geometry=True, angular=0.)

    def test_current_fast_candidate_cannot_reuse_slow_geometry_permission(self):
        self.exercise(.1, True, None, (0., 0.), control_geometry=True, angular=0.)

    def test_tracked_static_obstacle_reaches_actual_zero_output(self):
        self.exercise(.1, True, None, (0., 0.), control_tracking=True, angular=0.)

    def test_calibrated_swept_candidate_reaches_simulation_motor_topic(self):
        with patch.dict('os.environ', {'ROSY_SIMULATION_ACTUATION': '1'}):
            self.exercise(.01, True, None, (-.0125, 0.), control_actuation=True, angular=0.)

    def test_bounded_arc_reaches_motor_topic_without_full_spin_permission(self):
        with patch.dict('os.environ', {'ROSY_SIMULATION_ACTUATION': '1'}):
            self.exercise(.005, True, None, (-.005, .05), control_actuation=True, angular=.05)

    def exercise(self, linear, required, provider, expected, control_obstacle=False,
                 control_geometry=False, control_tracking=False, control_actuation=False, angular=.1):
        path = Path(__file__).parents[1] / 'core/bridge/ros_bridge.py'
        cls = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body
                   if isinstance(n, ast.ClassDef) and n.name == 'RosBridge')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_publish_cmd_vel')
        scope = dict(Twist=Twist)
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), scope)
        modes = ModeMachine()
        modes.transition(Mode.NAVIGATION)
        safety = SafetyManager(SpeedLimits(), BatteryPolicy(), policy_required=required)
        if provider is not None:
            safety.bind_policy(provider, 'calibration-1')
        command = CommandManager(SourceRegistry(), modes, safety)
        rclpy.init()
        node = Node('output_probe', namespace='rosy_01', parameter_overrides=(
            [Parameter('use_sim_time', value=True)] if control_actuation else []))
        observed = []
        node.create_subscription(Twist, 'cmd_vel', lambda msg: observed.append(msg), 10)
        bridge = SimpleNamespace(_svc=SimpleNamespace(command=command, power=Mock()),
                                 _readiness=None,
                                 cmd_vel_pub=node.create_publisher(Twist, 'cmd_vel', 10))
        try:
            if control_obstacle or control_geometry or control_tracking or control_actuation:
                from control.control.command_gate import CommandPolicy, GateInputs, GateSnapshot
                from control.control.lidar_guard import TranslationEvidence
                from control.control.actuation import SimulationActuation
                policy = CommandPolicy('applied-revision')
                safety.bind_control_policy(policy)
                now = time.monotonic()
                translation = (TranslationEvidence(now, now, True, True, (-.017, 0.), (.02, .02), .076,
                    (.2,) * 6, True, True, True, True, (1., 1.)) if control_geometry else None)
                tracking = None
                if control_tracking:
                    from control.control.obstacle_risk import TrackedEvidence
                    tracking = TrackedEvidence.capture({'stamp': 100., 'frame': 'odom', 'tracks': [
                        dict(position=[.2, 0.], velocity=[0., 0.], radius=.02, age=0., observed=True,
                             state='stationary')]}, {'stamp': 100., 'blocked': False},
                        (0., 0., 0.), 100., source_now=100., received_at=now, radius=.076, margin=.02)
                self.assertTrue(policy.update(GateSnapshot(policy.session, 1, policy.revision,
                    now, now + .5, GateInputs(obstacle=control_obstacle, bounded_motion=control_actuation,
                                              can_rotate=not control_actuation), translation, tracking)))
                if control_actuation:
                    safety.bind_simulation_actuation(SimulationActuation(policy.revision, now, now+.2,
                        (1.25, .75), (1., 1.), -1., ((.5, 0.), (0., .5), (-.5, 0.), (0., -.5)),
                        (0., 0.), .003, .076, now, now, True),
                        simulation_clock_enabled=lambda: node.get_parameter('use_sim_time').value)
            command.set_nav_twist(CoreTwist(linear, angular))
            deadline = time.monotonic() + 5.
            while not observed and time.monotonic() < deadline:
                scope['_publish_cmd_vel'](bridge)
                rclpy.spin_once(node, timeout_sec=.05)
            self.assertTrue(observed)
            self.assertEqual((observed[-1].linear.x, observed[-1].angular.z), expected,
                             f'policy_reason={safety.policy_reason}; estop={safety.estop}')
            if control_obstacle or control_geometry or control_tracking or control_actuation:
                self.assertFalse(safety.estop)
            if expected == (0., 0.):
                bridge._svc.power.on_activity.assert_not_called()
        finally:
            node.destroy_node()
            rclpy.shutdown()


if __name__ == '__main__':
    unittest.main()
