"""One calibration trial must have one durable commit before any application."""
import ast
import math
from pathlib import Path
import statistics
from types import SimpleNamespace as NS
from unittest.mock import Mock

import yaml
from control.calibration_storage import single_calibration_path


def fixture(sign_path='calibration.yaml', save_path='calibration.yaml'):
    source = Path(__file__).parents[1] / 'control/calib_node.py'
    cls = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
               if isinstance(n, ast.ClassDef) and n.name == 'CalibNode')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'compute')
    scope = dict(math=math, statistics=statistics, yaml=yaml, Path=Path,
                 single_calibration_path=single_calibration_path,
                 ir_valid=lambda values: tuple(values))
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), scope)
    node = NS(sets={'floor': [(2000, 2100, 2200)] * 30, 'cliff': [(200, 220, 240)] * 30},
              linear_sign=1., imu_buf=[(.01, .02)], lidar_yaw=0.,
              _write=Mock(return_value=True), _status=Mock(), _apply_safety=Mock(),
              get_parameter=lambda name: NS(value=save_path if name == 'save_path' else sign_path))
    return node, scope['compute']


def test_trial_commits_all_measured_values_once():
    node, compute = fixture()
    compute(node)
    node._write.assert_called_once()
    document = yaml.safe_load(node._write.call_args.args[1])
    values = next(iter(document.values()))['ros__parameters']
    assert values['cliff_mode'] == 'low'
    assert values['cmd_linear_sign'] == 1.
    assert values['lidar_yaw_offset'] == 0.
    assert values == dict(node._apply_safety.call_args.args[0])


def test_distinct_legacy_files_are_rejected_before_any_write():
    node, compute = fixture(sign_path='drive.yaml', save_path='cliff.yaml')
    compute(node)
    node._write.assert_not_called()
    node._apply_safety.assert_not_called()


def test_failed_single_commit_never_applies_values():
    node, compute = fixture()
    node._write.return_value = False
    compute(node)
    node._write.assert_called_once()
    node._apply_safety.assert_not_called()
