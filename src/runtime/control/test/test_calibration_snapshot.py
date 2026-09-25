"""A consumer must bind a complete record to its current working generation."""
import tempfile
import unittest
from pathlib import Path

from control.calibration_record import encode_record, MAX_BYTES
from control.calibration_snapshot import load_calibration_snapshot


class CalibrationSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.context = dict(robot_id='rosy_01', hardware_model='pinky_pro',
                            geometry_revision='g1', sensor_revision='s1', data_generation='d1')
        self.path = self.root / 'calibration/rosy_01/calibration.yaml'
        self.path.parent.mkdir(parents=True)
        self.document = {'/**/safety_node': {'ros__parameters': {'imu_roll0': 0.25}}}
        self.write()

    def write(self):
        self.path.write_text(encode_record(self.document, self.context, 'test'), encoding='utf-8')

    def load(self, **changes):
        args = dict(destination=str(self.path), expected_context=self.context,
                    active_generation='d1', data_root=str(self.root))
        args.update(changes)
        return load_calibration_snapshot(**args)

    def test_verified_snapshot_survives_file_and_returned_value_changes(self):
        snapshot = self.load()
        self.assertEqual(snapshot.revision, 1)
        self.assertEqual(len(snapshot.digest), 64)
        values = snapshot.node_parameters('safety_node')
        values['imu_roll0'] = 99.0
        self.path.write_text('broken', encoding='utf-8')
        self.assertEqual(snapshot.node_parameters('safety_node'), {'imu_roll0': 0.25})

    def test_context_generation_and_path_mismatch_are_rejected(self):
        for change in (dict(active_generation='d2'),
                       dict(expected_context={**self.context, 'sensor_revision': 's2'}),
                       dict(destination=str(self.root / 'other.yaml'))):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.load(**change)

    def test_corruption_unbound_and_oversized_records_are_rejected(self):
        original = self.path.read_text(encoding='utf-8')
        for content in (original.replace('0.25', '0.5'), 'safety_node: {}', 'x' * (MAX_BYTES + 1)):
            self.path.write_text(content, encoding='utf-8')
            with self.subTest(size=len(content)), self.assertRaises(ValueError):
                self.load()

    def test_global_defaults_and_specific_values_resolve_without_alias_ambiguity(self):
        self.document['/**'] = {'ros__parameters': {'imu_roll0': 0.0, 'imu_pitch0': 0.5}}
        self.write()
        self.assertEqual(self.load().node_parameters('safety_node'),
                         {'imu_roll0': 0.25, 'imu_pitch0': 0.5})
        with self.assertRaises(ValueError):
            self.load().node_parameters('unrelated_node')
        self.document['safety_node'] = {'ros__parameters': {'imu_roll0': 9.0}}
        self.write()
        with self.assertRaises(ValueError):
            self.load().node_parameters('safety_node')

    def test_missing_node_and_unsupported_selectors_do_not_claim_application(self):
        for selector in ('/rosy_02/safety_node', '/**/nested/safety_node'):
            self.document = {selector: {'ros__parameters': {'imu_roll0': 0.25}}}
            self.write()
            with self.subTest(selector=selector), self.assertRaises(ValueError):
                self.load()
