import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


def node_method(name, **bindings):
    path = Path(__file__).parents[1] / 'calibration/startup_calibration_node.py'
    cls = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, ast.ClassDef))
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = dict(bindings)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


class LiveStatusTest(unittest.TestCase):
    def test_failed_trial_reports_recovered_sensor_without_claiming_ready(self):
        current = {'lidar': {'ok': True, 'status': 'ok'}}
        calls = []
        node = SimpleNamespace(phase='failed', sensing_only=False, existing_settings=False,
            sensors={'lidar': {'ok': False, 'status': 'invalid'}}, runtime_ready=False,
            read_tf=lambda: None, runtime_health=lambda now: current,
            last_report=0., publish=lambda: calls.append('publish'))
        node_method('tick', time=SimpleNamespace(monotonic=lambda: 10.))(node)
        self.assertEqual(node.sensors, current)
        self.assertEqual(node.phase, 'failed')
        self.assertFalse(node.runtime_ready)
        self.assertEqual(calls, ['publish'])
