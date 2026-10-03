"""Calibration updates must preserve the last usable file on every failure."""
import tempfile
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from control.calibration_storage import merge_calibration, single_calibration_path, calibration_revision
from control.calibration_record import runtime_calibration_path


def node_method(name):
    path = Path(__file__).parents[1] / 'control/calib_node.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'CalibNode')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = {'String': SimpleNamespace, 'merge_calibration': merge_calibration, 'yaml': yaml,
                 'single_calibration_path': single_calibration_path}
    namespace['runtime_calibration_path'] = runtime_calibration_path
    namespace['calibration_revision'] = calibration_revision
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


class CalibrationStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'calibration.yaml'
        self.original = 'safety_node:\n  ros__parameters:\n    robot_radius: 0.08\n'
        self.update = 'safety_node:\n  ros__parameters:\n    imu_roll0: 1.0\n'

    def test_preserves_unmeasured_settings(self):
        self.path.write_text(self.original, encoding='utf-8')
        merge_calibration(str(self.path), self.update)
        parameters = yaml.safe_load(self.path.read_text())['/**/safety_node']['ros__parameters']
        self.assertEqual(parameters, {'robot_radius': 0.08, 'imu_roll0': 1.0})

    def test_unconfigured_destination_is_rejected(self):
        with self.assertRaises(ValueError):
            merge_calibration('', self.update)

    def test_legacy_update_merges_into_scoped_file(self):
        self.path.write_text(self.original.replace('safety_node:', '/**/safety_node:'), encoding='utf-8')
        merge_calibration(str(self.path), self.update)
        document = yaml.safe_load(self.path.read_text())
        self.assertEqual(list(document), ['/**/safety_node'])
        self.assertEqual(document['/**/safety_node']['ros__parameters'],
                         {'robot_radius': 0.08, 'imu_roll0': 1.0})

    def test_ambiguous_legacy_and_scoped_selectors_preserve_file(self):
        original = self.original + self.original.replace('safety_node:', '/**/safety_node:')
        self.path.write_text(original, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            merge_calibration(str(self.path), self.update)
        self.assertEqual(self.path.read_text(), original)

    def test_corrupt_existing_file_is_never_replaced(self):
        for original in ['[broken', '[]', 'safety_node: []', 'safety_node: {ros__parameters: []}']:
            with self.subTest(original=original):
                self.path.write_text(original, encoding='utf-8')
                with self.assertRaises((ValueError, yaml.YAMLError)):
                    merge_calibration(str(self.path), self.update)
                self.assertEqual(self.path.read_text(), original)

    def test_invalid_update_preserves_original(self):
        for update in ['null', '[]', 'safety_node: {}',
                       'safety_node: {ros__parameters: []}',
                       'safety_node: {ros__parameters: {imu_roll0: .nan}}']:
            with self.subTest(update=update):
                self.path.write_text(self.original, encoding='utf-8')
                with self.assertRaises(ValueError):
                    merge_calibration(str(self.path), update)
                self.assertEqual(self.path.read_text(), self.original)

    def test_replace_failure_preserves_file_and_removes_temporary(self):
        self.path.write_text(self.original, encoding='utf-8')
        with patch('control.calibration_storage.os.replace', side_effect=OSError('read only')):
            with self.assertRaises(OSError):
                merge_calibration(str(self.path), self.update)
        self.assertEqual(self.path.read_text(), self.original)
        self.assertEqual(set(self.path.parent.iterdir()), {self.path, self.path.with_suffix('.yaml.lock')})

    def test_separate_generation_paths_do_not_share_updates(self):
        previous = self.path.parent / 'previous' / 'calibration.yaml'
        previous.parent.mkdir()
        previous.write_text(self.original, encoding='utf-8')
        merge_calibration(str(self.path), self.update)
        self.assertEqual(previous.read_text(), self.original)

    def test_node_does_not_start_motion_without_both_destinations(self):
        for step in ['auto', 'start', 'lidar', 'scan']:
            for missing in ['save_path', 'sign_path']:
                calls = []
                node = SimpleNamespace(
                    get_parameter=lambda key: SimpleNamespace(value='' if key == missing else str(self.path)),
                    _status=lambda message: calls.append('status'),
                    _start_auto=lambda: calls.append('motion'),
                    _begin_nudge=lambda: calls.append('motion'),
                )
                node_method('on_step')(node, SimpleNamespace(data=step))
                self.assertEqual(calls, ['status'])

    def test_abort_remains_available_without_storage(self):
        calls = []
        node = SimpleNamespace(_abort=lambda reason: calls.append('abort'))
        node_method('on_step')(node, SimpleNamespace(data='abort'))
        self.assertEqual(calls, ['abort'])

    def test_split_destinations_cannot_start_motion(self):
        calls = []
        node = SimpleNamespace(
            get_parameter=lambda key: SimpleNamespace(value=str(self.path.parent / (key + '.yaml'))),
            _status=lambda message: calls.append('status'),
            _start_auto=lambda: calls.append('motion'))
        node_method('on_step')(node, SimpleNamespace(data='auto'))
        self.assertEqual(calls, ['status'])

    def test_bound_generation_mismatch_cannot_start_motion(self):
        calls = []
        node = SimpleNamespace(
            calibration_context=dict(robot_id='rosy_01', hardware_model='Pinky Pro',
                                     geometry_revision='g1', sensor_revision='s1', data_generation='new'),
            calibration_generation='previous',
            get_parameter=lambda key: SimpleNamespace(value=str(self.path)),
            _status=lambda message: calls.append('status'),
            _start_auto=lambda: calls.append('motion'))
        node_method('on_step')(node, SimpleNamespace(data='auto'))
        self.assertEqual(calls, ['status'])

    def test_trial_captures_revision_before_collecting_measurements(self):
        context = dict(robot_id='rosy_01', hardware_model='Pinky Pro', geometry_revision='g1',
                       sensor_revision='s1', data_generation='generation-1')
        merge_calibration(str(self.path), self.update, context=context, actor='first')
        calls = []
        node = SimpleNamespace(
            calibration_context=context,
            get_parameter=lambda key: SimpleNamespace(value=str(self.path)),
            _status=lambda message: calls.append('status'),
            _start_auto=lambda: calls.append('collecting'))
        node_method('on_step')(node, SimpleNamespace(data='auto'))
        self.assertEqual(calls, ['collecting'])
        self.assertEqual(node.calibration_expected_revision, 1)
        merge_calibration(str(self.path), self.update, context=context, actor='other')
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'revision'):
            merge_calibration(str(self.path), self.update, context=context, actor='first',
                              expected_revision=node.calibration_expected_revision)
        self.assertEqual(self.path.read_bytes(), original)

    def test_node_reports_failed_write_without_claiming_success(self):
        calls = []
        node = SimpleNamespace(_status=calls.append)
        self.assertFalse(node_method('_write')(node, '', self.update))
        self.assertTrue(calls[0].startswith('save fail'))
