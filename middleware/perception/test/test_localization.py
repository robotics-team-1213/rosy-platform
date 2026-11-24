"""Localization confidence must not be inferred from covariance alone."""
import unittest
import math
from pathlib import Path
import numpy as np

from control.sensing.localization import MapAgreement, Confidence, lease_ready, planar_yaw


class LocalizationTests(unittest.TestCase):
    def test_angle_helpers_keep_signed_pi_endpoints(self):
        from control.sensing.localization import wrap
        for angle, expected in ((0., 0.), (math.pi, math.pi), (-math.pi, -math.pi),
                                (3 * math.pi, math.pi)):
            self.assertAlmostEqual(wrap(angle), expected)
            self.assertAlmostEqual(planar_yaw(0., 0., math.sin(angle / 2), math.cos(angle / 2)), expected)

    def test_recorded_gazebo_corner_is_not_lost_between_coarse_candidates(self):
        d = np.load(Path(__file__).parent / 'fixtures/gazebo_localization_corner.npz')
        m = MapAgreement(d['grid'], float(d['resolution']), d['origin'])
        result = m.global_match(d['ranges'], d['angles'], .105)
        self.assertTrue(result['unique'], result)
        self.assertLess(math.dist(result['pose'][:2], d['truth'][:2]), .02)
        self.assertTrue(m.footprint_clear(*result['pose'][:2], .105))
    def test_invalid_or_tilted_rotation_cannot_authorize_planar_pose(self):
        self.assertAlmostEqual(planar_yaw(0., 0., math.sin(.2), math.cos(.2)), .4)
        for values in ((0., 0., 0., 0.), (0., 0., 0., 2.), (math.nan, 0., 0., 1.),
                       (1., 0., 0., 0.)):
            with self.assertRaises(ValueError):
                planar_yaw(*values)

    def test_footprint_clearance_checks_edges_and_unknown(self):
        grid = np.zeros((50, 50), dtype=np.int8)
        grid[:, 40] = 100
        m = MapAgreement(grid, .02, (0., 0.))
        self.assertTrue(m.footprint_clear(.5, .5, .1))
        self.assertFalse(m.footprint_clear(.75, .5, .1))
        self.assertFalse(m.footprint_clear(.01, .5, .1))
        grid[25, 25] = -1
        self.assertFalse(MapAgreement(grid, .02, (0., 0.)).footprint_clear(.5, .5, .1))
    def test_lease_is_stamped_and_expires(self):
        self.assertTrue(lease_ready({'ready': True, 'stamp_ns': 1000000000}, 1.2))
        for value in (None, {}, {'ready': True}, {'ready': 'true', 'stamp_ns': 1000000000},
                      {'ready': True, 'stamp_ns': 3000000000}):
            self.assertFalse(lease_ready(value, 1.2))
        self.assertFalse(lease_ready({'ready': True, 'stamp_ns': 1000000000}, 2.))

    def test_confidence_requires_distinct_good_scans_and_revokes_immediately(self):
        c = Confidence(stable_scans=3)
        for t in (1., 1., 1.1):
            self.assertFalse(c.observe(t, True))
        self.assertTrue(c.observe(1.2, True))
        self.assertFalse(c.observe(1.3, False))
        self.assertFalse(c.observe(1.4, True))
        self.assertFalse(c.observe(.1, True))  # Time rewind cannot renew a lease.

    def test_scan_fit_uses_sensor_pose_and_rejects_unknown_and_wrong_pose(self):
        grid = np.zeros((50, 50), dtype=np.int8)
        grid[:, 40] = 100
        m = MapAgreement(grid, .02, (0., 0.))
        angles = np.linspace(-.4, .4, 60)
        ranges = .4 / np.cos(angles)
        self.assertGreater(m.score((.4, .5, 0.), ranges, angles), .95)
        self.assertLess(m.score((.2, .5, 0.), ranges, angles), .1)
        self.assertLess(m.score((.4, .5, 3.14), ranges, angles), .1)
        self.assertEqual(m.score((.4, .5, 0.), [], []), 0.)
        grid[:, 40] = -1
        self.assertEqual(MapAgreement(grid, .02, (0., 0.)).score((.4, .5, 0.), ranges, angles), 0.)

    def test_endpoints_behind_a_wall_are_not_a_valid_match(self):
        grid = np.zeros((50, 50), dtype=np.int8)
        grid[:, 30] = grid[:, 40] = 100
        m = MapAgreement(grid, .02, (0., 0.))
        angles = np.linspace(-.4, .4, 60)
        self.assertLess(m.score((.4, .5, 0.), .4 / np.cos(angles), angles), .1)

    def test_global_match_rejects_rotationally_symmetric_room(self):
        grid = np.zeros((51, 51), dtype=np.int8)
        grid[[0, -1], :] = 100
        grid[:, [0, -1]] = 100
        angles = np.linspace(-math.pi, math.pi, 72, endpoint=False)
        ranges = .5 / np.maximum(np.abs(np.cos(angles)), np.abs(np.sin(angles)))
        result = MapAgreement(grid, .02, (0., 0.)).global_match(ranges, angles, .08)
        self.assertFalse(result['unique'])

    def test_global_match_finds_unknown_pose_in_asymmetric_map(self):
        grid = np.zeros((80, 100), dtype=np.int8)
        grid[[0, -1], :] = 100
        grid[:, [0, -1]] = 100
        grid[40:43, 40:90] = 100
        grid[12:20, 12:17] = 100
        angles = np.linspace(-math.pi, math.pi, 180, endpoint=False)
        truth = (.7, .5, .37)
        ranges = []
        for a in angles + truth[2]:
            for r in np.arange(.01, 3., .005):
                x, y = int((truth[0]+r*math.cos(a))/.02), int((truth[1]+r*math.sin(a))/.02)
                if not (0 <= x < 100 and 0 <= y < 80) or grid[y, x] >= 65:
                    ranges.append(r)
                    break
        result = MapAgreement(grid, .02, (0., 0.)).global_match(ranges, angles, .08)
        self.assertTrue(result['unique'], result)
        self.assertLess(math.dist(result['pose'][:2], truth[:2]), .03)
        self.assertLess(abs(math.atan2(math.sin(result['pose'][2]-.37), math.cos(result['pose'][2]-.37))), .03)

    def test_coarse_5cm_grid_keeps_one_cell_wall_tolerance_and_rejects_intervening_walls(self):
        point_grid = np.zeros((40, 40), dtype=np.int8)
        point_grid[20, 20] = 100
        point_map = MapAgreement(point_grid, .05, (0., 0.))
        self.assertTrue(point_map.near[19:22, 19:22].all())
        self.assertFalse(point_map.near[18, 20] or point_map.near[22, 20])
        self.assertFalse(point_map.near[20, 18] or point_map.near[20, 22])
        self.assertAlmostEqual(point_map._ray_margin, .10)

        wall_grid = np.zeros((40, 40), dtype=np.int8)
        wall_grid[:, 20] = 100
        wall_map = MapAgreement(wall_grid, .05, (0., 0.))
        angles = np.linspace(-.4, .4, 60)
        self.assertGreater(wall_map.score((.40, 1.00, 0.), (.99 - .40) / np.cos(angles), angles), .90)
        self.assertLess(wall_map.score((.25, 1.00, 0.), (.99 - .40) / np.cos(angles), angles), .1)

        wall_grid[:, 15] = 100
        blocked_map = MapAgreement(wall_grid, .05, (0., 0.))
        self.assertLess(blocked_map.score((.40, 1.00, 0.), (1.02 - .40) / np.cos(angles), angles), .1)

    def test_2cm_grid_keeps_legacy_tolerance_and_ray_margin(self):
        grid = np.zeros((30, 30), dtype=np.int8)
        grid[10, 10] = 100
        m = MapAgreement(grid, .02, (0., 0.), tolerance=.04)
        self.assertTrue(m.near[10, 12])
        self.assertFalse(m.near[12, 12])
        self.assertFalse(m.near[10, 13])
        self.assertAlmostEqual(m._ray_margin, .06)
        self.assertAlmostEqual(m.likelihood[10, 11], math.exp(-(.02**2) / (2 * .025**2)))

    def test_robust_score_recovers_y8xs_occlusion_and_enforces_adversarial_safety_gates(self):
        # 5x5 m closed room (2cm cells -> 250x250), robot at (1.5, 1.5, 0.0)
        grid = np.zeros((250, 250), dtype=np.int8)
        grid[25:225, 25] = 100
        grid[25:225, 224] = 100
        grid[25, 25:225] = 100
        grid[224, 25:225] = 100
        # Open unknown (-1) doorway on left wall covering 130..162 deg from (1.5, 1.5)
        grid[88:139, :26] = -1
        m = MapAgreement(grid, .02, (0., 0.), tolerance=.04)
        truth = (1.5, 1.5, 0.0)
        angles = np.linspace(-math.pi, math.pi, 180, endpoint=False)
        wall_ranges = []
        for a in angles:
            dx, dy = math.cos(a), math.sin(a)
            dists = []
            if dx > 1e-6:
                dists.append((224 * .02 - truth[0]) / dx)
            elif dx < -1e-6:
                dists.append((25 * .02 - truth[0]) / dx)
            if dy > 1e-6:
                dists.append((224 * .02 - truth[1]) / dy)
            elif dy < -1e-6:
                dists.append((25 * .02 - truth[1]) / dy)
            wall_ranges.append(min(dists) + .01)
        wall_ranges = np.array(wall_ranges, dtype=float)

        # Profile matching live y8xs: ~17% contiguous foreground cluster + ~9% unknown rays
        y8xs_ranges = wall_ranges.copy()
        fg_mask = (angles >= math.radians(45)) & (angles < math.radians(107))  # ~31 beams (~17%)
        y8xs_ranges[fg_mask] = 0.55
        unk_mask = (angles >= math.radians(130)) & (angles < math.radians(162))  # ends outside/unknown
        y8xs_ranges[unk_mask] = 6.0  # shoots out of bounds -> unknown_open
        b = m.explain(truth, y8xs_ranges, angles)
        self.assertLess(m.score(truth, y8xs_ranges, angles), 0.80)
        self.assertIsNone(b.rejected_reason)
        self.assertGreaterEqual(b.robust_score, 0.90)
        results, reason = m.global_results(y8xs_ranges, angles, .105, use_robust=True)
        self.assertIsNone(reason)
        self.assertLess(math.dist(results[0][2][:2], truth[:2]), .05)

        # 1) >3% wall-piercing rejection (beams extend past wall through >=65 cells)
        pierced = wall_ranges.copy()
        pierced[:15] = 4.2
        self.assertEqual(m.explain(truth, pierced, angles).rejected_reason, "wall-piercing")
        self.assertEqual(m.robust_score(truth, pierced, angles), 0.0)

        # 2) <4 hit sectors rejection
        sparse_idx = np.arange(0, 36)  # ~72 deg arc -> <= 2 sectors
        self.assertEqual(m.explain(truth, wall_ranges[sparse_idx], angles[sparse_idx]).rejected_reason, "sparse-sectors")

        # 3) >30% foreground / low raw (<0.55) corner trap rejection
        heavy_fg = wall_ranges.copy()
        heavy_fg[:70] = 0.55
        heavy_b = m.explain(truth, heavy_fg, angles)
        self.assertIn(heavy_b.rejected_reason, ("low-raw-fit", "excess-foreground"))
        self.assertEqual(heavy_b.robust_score, 0.0)

        # 4) Isolated non-clustered short beams (<3 contiguous) are NOT discounted
        iso = wall_ranges.copy()
        iso[::10][:8] = 0.60  # spaced every 20 deg -> isolated singletons
        iso_b = m.explain(truth, iso, angles)
        self.assertEqual(iso_b.miss_foreground, 0)
        self.assertEqual(iso_b.fg_cluster_count, 0)
