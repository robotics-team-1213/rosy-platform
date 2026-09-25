"""Default robot endpoints must follow the namespace chosen by ROS launch."""
import ast
from pathlib import Path
import unittest

import yaml


PACKAGE = Path(__file__).parents[1]
ENDPOINTS = {'create_publisher', 'create_subscription', 'create_client', 'create_service'}


def endpoint_parameter(name):
    return isinstance(name, str) and ('topic' in name or name in ('cmd_in', 'cmd_out'))


class EndpointDefaultsTests(unittest.TestCase):
    def test_node_endpoint_literals_and_parameter_defaults_are_relative(self):
        failures = []
        for path in (PACKAGE / 'control').rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if len(node.args) < 2:
                    continue
                method = node.func.attr
                name, value = node.args[:2]
                selected = method in ENDPOINTS or (
                    method == 'declare_parameter' and isinstance(name, ast.Constant)
                    and endpoint_parameter(name.value))
                if selected and isinstance(value, ast.Constant) and isinstance(value.value, str):
                    if value.value.startswith('/'):
                        failures.append(f'{path.name}:{node.lineno}: {value.value}')
        self.assertEqual(failures, [])

    def test_config_cannot_restore_absolute_endpoint_defaults(self):
        failures = []

        def visit(value, path):
            if isinstance(value, dict):
                for name, child in value.items():
                    if endpoint_parameter(name) and isinstance(child, str) and child.startswith('/'):
                        failures.append(f'{path.name}: {name}={child}')
                    visit(child, path)
            elif isinstance(value, list):
                for child in value:
                    visit(child, path)

        for path in (PACKAGE / 'config').glob('*.yaml'):
            visit(yaml.safe_load(path.read_text(encoding='utf-8')), path)
        self.assertEqual(failures, [])
