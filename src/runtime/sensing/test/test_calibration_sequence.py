"""Real-value tests for the ROS-free calibration_sequence mixin (D-171/C1).

The mixin moved out of startup_calibration_node.py and calib_node.py
(2026-09-22 split design, D-362 P0-2): these tests pin the moved decisions —
sensor-failure detail, stationary advisory substitution, atomic persistence,
and the calib floor/cliff/lidar helpers — on values, not source text.
"""
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from control.calibration_sequence import (
    CalibrationSequence,
    approach_heading,
    ir_valid,
    looks_cliff,
    looks_floor,
    snap_lidar_yaw,
)


def parameter(values):
    return lambda name: NS(value=values[name])


class SensorFailureDetailTest(unittest.TestCase):
    def test_failure_names_each_sensor_with_wall_and_transform_context(self):
        node = NS(baseline=NS(samples={'lidar': [], 'map_tf': [(9., (0., 0., 0.), False)]}),
                  wall_tracker=NS(diagnostic={'reason': 'Tracked wall missing or ambiguous'}),
                  map_tf_diagnostic={'valid': False, 'reason': 'stale'})
        message = CalibrationSequence.sensor_failure(node, 10.)
        self.assertIn('lidar: no sample', message)
        self.assertIn('wall=', message)
        self.assertIn('map_tf: valid=False', message)
        self.assertIn('transform=', message)


class StationaryReportTest(unittest.TestCase):
    def test_camera_stays_advisory_and_us_reads_live_health_when_agreement_not_required(self):
        node = NS(baseline=NS(
                      report=lambda now: {'camera': {'ok': False}, 'us': {'ok': True}},
                      samples={'us': [(10., (0.4,), True)]}),
                  us_source_valid=True,
                  get_parameter=parameter({'calibration_require_us_agreement': False}),
                  map_tf_diagnostic={})
        node.runtime_health = lambda now: CalibrationSequence.runtime_health(node, now)
        result = CalibrationSequence.stationary_report(node, 10.)
        self.assertTrue(result['camera']['eligible'])  # RGB quality never gates safety.
        # Live health keeps the US row eligible on a fresh valid echo even though
        # the stationary variance table said only ok=True.
        self.assertTrue(result['us']['eligible'])
        self.assertEqual(result['us']['samples'], 1)


class WriteJsonTest(unittest.TestCase):
    def test_write_json_replaces_atomically_and_leaves_no_temporary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'nested' / 'calibration.json'
            CalibrationSequence.write_json(path, {'forward_scale': 1.02, 'rows': [1, 2]})
            self.assertEqual(json.loads(path.read_text()), {'forward_scale': 1.02, 'rows': [1, 2]})
            self.assertEqual(list(path.parent.iterdir()), [path])


class CalibHelperTest(unittest.TestCase):
    def test_ir_valid_drops_saturation_and_open_circuit(self):
        # 4095 = ADC saturation, never a cliff edge; <50 is no return at all.
        self.assertEqual(ir_valid((4095, 2000, 60)), (2000, 60))
        self.assertEqual(ir_valid((40, 2000, 60)), (2000, 60))

    def test_floor_needs_two_valid_reads_above_desk_threshold(self):
        self.assertTrue(looks_floor((2400, 2500)))
        self.assertFalse(looks_floor((2400,)))       # one sensor is not agreement
        self.assertFalse(looks_floor((2400, 1400)))  # below 1500: not desk-center floor

    def test_cliff_threshold_follows_measured_floor_down_to_1100(self):
        floor_m = 5000.
        self.assertTrue(looks_cliff((900, 900, 900), floor_m))    # 0.40*floor = 2000 → 1100 cap
        self.assertFalse(looks_cliff((1150, 1150, 1150), floor_m))
        self.assertTrue(looks_cliff((950, 950, 950), 2500.))      # 0.40*floor = 1000 now applies
        self.assertFalse(looks_cliff((1050, 1050, 1050), 2500.))
        self.assertTrue(looks_cliff((4095, 900, 900), floor_m))   # saturation is dropped, the valid reads decide
        self.assertFalse(looks_cliff((4095, 4095, 4095), floor_m))  # no valid read left to agree

    def test_snap_lidar_yaw_pulls_near_axis_headings_to_exact_axes(self):
        self.assertEqual(snap_lidar_yaw(math.radians(30)), 0.0)
        self.assertEqual(snap_lidar_yaw(math.radians(-35)), 0.0)
        self.assertEqual(snap_lidar_yaw(math.radians(170)), math.pi)
        self.assertAlmostEqual(snap_lidar_yaw(math.radians(90)), math.pi / 2)

    def test_approach_heading_weights_only_closing_returns(self):
        amin, ainc = 0., math.pi / 2
        s0 = (amin, ainc, [1.0, 1.0, 1.0, 1.0], .05, 6.0)
        s1 = (amin, ainc, [.98, 1.0, 1.02, 1.0], .05, 6.0)
        self.assertEqual(approach_heading(s0, s1), 0.0)  # only the front bin closed
        s2 = (amin, ainc, [1.0, 1.0, 1.0, .98], .05, 6.0)
        self.assertAlmostEqual(approach_heading(s0, s2), -math.pi / 2)  # starboard bin closed
        # Tiny closures stay noise; none returns no heading at all.
        s3 = (amin, ainc, [1.0, 1.0, 1.0, 1.0], .05, 6.0)
        self.assertIsNone(approach_heading(s0, s3))
        self.assertIsNone(approach_heading(None, s0))
