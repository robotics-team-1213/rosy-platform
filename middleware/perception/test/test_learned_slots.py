"""D-423 §3.1: per-task model slots on the robot."""
import ast
from pathlib import Path

import pytest

from control.sensing.perception.learned.manifest import TASKS
from control.sensing.perception.learned.slots import MODELS_ROOT, SLOTS, slot_pointer, task_root

PKG = Path(__file__).resolve().parents[1]


def test_layout():
    assert MODELS_ROOT == '/var/lib/rosy/models'
    assert SLOTS == ('shadow', 'active', 'previous')
    assert task_root('object_det') == '/var/lib/rosy/models/object_det'
    assert slot_pointer('object_det', 'active') == '/var/lib/rosy/models/object_det/active'
    assert slot_pointer('object_det', 'previous', root='/srv/m') == '/srv/m/object_det/previous'


def test_lane_seg_keeps_the_flat_d373_root_for_the_transition():
    """The robots' lane shadow pointer stays where D-373 put it until a migration release."""
    assert task_root('lane_seg') == MODELS_ROOT
    assert slot_pointer('lane_seg', 'shadow') == '/var/lib/rosy/models/shadow'


@pytest.mark.parametrize('task,slot', [('nope', 'shadow'), ('object_det', 'shadow.tmp'), ('object_det', '')])
def test_unknown_task_or_slot_is_refused(task, slot):
    with pytest.raises(ValueError):
        slot_pointer(task, slot)


def test_every_task_has_a_root():
    assert all(task_root(t) for t in TASKS)


def _defaults(path):
    out = {}
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'DeclareLaunchArgument':
            value = {k.arg: k.value for k in node.keywords}.get('default_value')
            if isinstance(value, ast.Constant):
                out[ast.literal_eval(node.args[0])] = value.value
    return out


def test_launch_and_node_defaults_are_the_slot_paths():
    launch = _defaults(PKG / 'launch' / 'camera_preview.launch.py')
    assert launch['object_det_pointer'] == slot_pointer('object_det', 'active')
    assert launch['shadow_pointer'] == slot_pointer('lane_seg', 'shadow')
    node = (PKG / 'control' / 'object_detector_node.py').read_text(encoding='utf-8')
    assert "slot_pointer('object_det', 'active')" in node
