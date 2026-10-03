"""D-442 U2: follow final cmd_vel publishers regardless of attribute names."""

import ast

import pytest

from test_safety_separation import (CMD_VEL_PUBLISHER, CMD_VEL_SCOPE_EXCLUDED,
                                    CMD_VEL_PARAMETER_ALLOWLIST, ROOT, _is_test_file, _tracked)


def test_no_other_attribute_publishes_cmd_vel():
    found = set()
    scanned = 0
    for path in _tracked():
        if not path.endswith(".py") or _is_test_file(path) or path.startswith(tuple(CMD_VEL_SCOPE_EXCLUDED)):
            continue
        scanned += 1
        text = (ROOT / path).read_text(encoding="utf-8-sig")
        for owner, function, publisher in _final_publishes(ast.parse(text), legacy_sensor_only=(
                path in CMD_VEL_PARAMETER_ALLOWLIST)):
            found.add((path, owner, function))
    assert scanned > 500
    assert found == {(CMD_VEL_PUBLISHER, "RosBridge", "_send_twist")}, found


@pytest.mark.parametrize("constructor", [
    'self._pub = node.create_publisher(Twist, "cmd_vel", 10)',
    'self._pub = node.create_publisher(Twist, "/cmd_vel", 10)',
    'self._pub = node.create_publisher(Twist, FINAL_TOPIC, 10)',
    'self.declare_parameter("output", "cmd_vel"); self._pub = node.create_publisher(Twist, self.get_parameter("output").value, 10)',
    'self.declare_parameter("output", "cmd_vel"); self.output = self.get_parameter("output").value; self._pub = node.create_publisher(Twist, self.output, 10)',
])
def test_alternate_attribute_and_default_parameter_cannot_hide_publishing(constructor):
    source = 'FINAL_TOPIC = "cmd_vel"\nclass Writer:\n    def __init__(self, node):\n        ' + constructor + '\n    def bypass(self, msg):\n        self._pub.publish(msg)\n'
    assert _final_publishes(ast.parse(source)) == {("Writer", "bypass", "self._pub")}


def test_publisher_alias_cannot_hide_publishing():
    source = 'class Writer:\n    def __init__(self, node):\n        self._pub = node.create_publisher(Twist, "cmd_vel", 10)\n    def bypass(self, msg):\n        alias = self._pub\n        alias.publish(msg)\n'
    assert _final_publishes(ast.parse(source)) == {("Writer", "bypass", "alias")}


def test_raw_candidate_is_separate_from_final_publisher():
    source = 'class Writer:\n    def __init__(self, node):\n        self._pub = node.create_publisher(Twist, "cmd_vel_raw", 10)\n    def candidate(self, msg):\n        self._pub.publish(msg)\n'
    assert _final_publishes(ast.parse(source)) == set()


def test_legacy_exception_requires_the_exact_sensor_only_conditional():
    source = 'class Writer:\n    def __init__(self, node):\n        self._pub = None if sensor_only else node.create_publisher(Twist, "cmd_vel", 10)\n    def bypass(self, msg):\n        self._pub.publish(msg)\n'
    assert _final_publishes(ast.parse(source), legacy_sensor_only=True) == set()
    assert _final_publishes(ast.parse(source)) == {("Writer", "bypass", "self._pub")}
    unconditional = source.replace('None if sensor_only else ', '')
    assert _final_publishes(ast.parse(unconditional), legacy_sensor_only=True) == {("Writer", "bypass", "self._pub")}


def _final_publishes(tree, *, legacy_sensor_only=False):
    """Static topics/defaults and publisher aliases; dynamic ROS remaps remain review-only.

    The existing D-208 standalone node is outside the operational graph in sensor_only
    mode. Its exception applies only to a literal None-if-sensor_only creation guard;
    an unconditional publisher in that same file still appears as a violation.
    """
    topics = {"cmd_vel", "/cmd_vel"}
    constants = {target.id: node.value.value for node in tree.body
                 if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                 for target in node.targets if isinstance(target, ast.Name)}
    found = set()
    owners = [("<module>", tree.body)] + [(node.name, node.body) for node in ast.walk(tree)
                                        if isinstance(node, ast.ClassDef)]
    for owner, body in owners:
        functions = [node for node in body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        defaults = {}
        for function in functions:
            for node in ast.walk(function):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "declare_parameter" and len(node.args) >= 2
                        and isinstance(node.args[0], ast.Constant) and isinstance(node.args[1], ast.Constant)):
                    defaults[node.args[0].value] = node.args[1].value

        def topic_value(node, values):
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.Name):
                return values.get(node.id, constants.get(node.id))
            if isinstance(node, ast.Attribute) and node.attr == "value" and isinstance(node.value, ast.Call):
                call = node.value
                if (isinstance(call.func, ast.Attribute) and call.func.attr == "get_parameter"
                        and call.args and isinstance(call.args[0], ast.Constant)):
                    return defaults.get(call.args[0].value)
            return values.get(ast.unparse(node))

        attributes = {}
        # Constructor attributes are visible in every method. Resolve bounded aliases to a fixed point.
        for _ in range(3):
            for function in functions:
                values = dict(attributes)
                for node in ast.walk(function):
                    if isinstance(node, ast.Assign):
                        value = topic_value(node.value, values)
                        for target in node.targets:
                            key = ast.unparse(target)
                            values[key] = value
                            if isinstance(target, ast.Attribute):
                                attributes[key] = value
        publishers = set()
        for _ in range(3):
            for function in functions:
                aliases = set(publishers)
                values = dict(attributes)
                for node in ast.walk(function):
                    if not isinstance(node, ast.Assign):
                        continue
                    value = node.value
                    if isinstance(value, ast.IfExp):
                        guarded = (legacy_sensor_only and isinstance(value.test, ast.Name)
                                   and value.test.id == "sensor_only" and isinstance(value.body, ast.Constant)
                                   and value.body.value is None)
                        if guarded:
                            continue
                    for target in node.targets:
                        values[ast.unparse(target)] = topic_value(value, values)
                    branches = (value.body, value.orelse) if isinstance(value, ast.IfExp) else (value,)
                    is_final = any(ast.unparse(branch) in aliases for branch in branches)
                    for branch in branches:
                        if (isinstance(branch, ast.Call) and isinstance(branch.func, ast.Attribute)
                                and branch.func.attr == "create_publisher"):
                            topic = branch.args[1] if len(branch.args) > 1 else next(
                                (kw.value for kw in branch.keywords if kw.arg == "topic"), None)
                            is_final |= topic is not None and topic_value(topic, values) in topics
                    if is_final:
                        for target in node.targets:
                            key = ast.unparse(target)
                            aliases.add(key)
                            if isinstance(target, ast.Attribute):
                                publishers.add(key)
                for node in ast.walk(function):
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "publish" and ast.unparse(node.func.value) in aliases):
                        found.add((owner, function.name, ast.unparse(node.func.value)))
    return found


def test_inverse_sensor_only_guard_is_never_exempt():
    source = 'class Writer:\n    def __init__(self, node):\n        self.declare_parameter("output", "cmd_vel")\n        self._pub = node.create_publisher(Twist, self.get_parameter("output").value, 10) if sensor_only else None\n    def bypass(self, msg):\n        self._pub.publish(msg)\n'
    assert _final_publishes(ast.parse(source), legacy_sensor_only=True) == {("Writer", "bypass", "self._pub")}


def test_local_topic_variable_is_resolved():
    source = 'class Writer:\n    def __init__(self, node):\n        self.declare_parameter("output", "cmd_vel")\n        topic = self.get_parameter("output").value\n        self._pub = node.create_publisher(Twist, topic, 10)\n    def bypass(self, msg):\n        self._pub.publish(msg)\n'
    assert _final_publishes(ast.parse(source)) == {("Writer", "bypass", "self._pub")}
