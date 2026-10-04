"""Exercise production parameter acknowledgement methods over isolated ROS."""
import ast
from pathlib import Path
import time
import unittest

try:
    import rclpy
except ImportError:
    rclpy = None

if rclpy is not None:
    from rclpy.node import Node
    from rclpy.clock import Clock, ClockType
    from rclpy.executors import SingleThreadedExecutor
    from rcl_interfaces.msg import Parameter, ParameterValue, ParameterType, SetParametersResult
    from rcl_interfaces.srv import SetParameters


@unittest.skipIf(rclpy is None, 'Requires isolated ROS Jazzy graph')
class CalibrationAckGraphTests(unittest.TestCase):
    def test_accepted_and_rejected_ros_responses_are_distinguished(self):
        source = Path(__file__).parents[1] / 'control/calib_node.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'CalibNode')
        methods = [m for m in cls.body if isinstance(m, ast.FunctionDef)
                   and m.name in ('_apply_safety', '_finish_apply')]
        scope = dict(globals())
        exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), 'exec'), scope)
        rclpy.init()
        executor = SingleThreadedExecutor()
        owner = Node('safety_node', namespace='rosy_01')
        owner.declare_parameter('imu_roll0', 0.)
        probe = Node('calib_probe', namespace='rosy_01')
        statuses = []
        probe._status = statuses.append
        for name in ('_apply_safety', '_finish_apply'):
            setattr(probe, name, scope[name].__get__(probe))
        executor.add_node(owner)
        executor.add_node(probe)
        try:
            for accepted in (True, False):
                if not accepted:
                    owner.add_on_set_parameters_callback(
                        lambda params: SetParametersResult(successful=False, reason='test rejection'))
                probe._apply_safety([('imu_roll0', 1. if accepted else 2.)])
                deadline = time.monotonic() + 5.
                while probe._pending_apply is not None and time.monotonic() < deadline:
                    executor.spin_once(timeout_sec=.05)
                self.assertIsNone(probe._pending_apply)
                self.assertIn('저장 확인' if accepted else '거절', statuses[-1])
                self.assertIn('운전 적용 미확인', statuses[-1])
                self.assertEqual(owner.get_parameter('imu_roll0').value, 1.)
        finally:
            executor.shutdown()
            probe.destroy_node()
            owner.destroy_node()
            rclpy.shutdown()


if __name__ == '__main__':
    unittest.main()
