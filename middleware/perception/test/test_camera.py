"""Camera proximity cues must distinguish visible walls from near obstacles."""
import unittest

import numpy as np

from control.sensing.perception.camera import classify_frame


class CameraNearObstacleTest(unittest.TestCase):
    def frame(self):
        # Neutral floor avoids conflating hue changes with void detection.
        return np.full((240, 320, 3), 100, dtype=np.uint8)

    def classify(self, frame):
        return classify_frame(frame, floor_hsv=(0., 0., 100.), obst_frac=.45)

    def test_distant_wall_with_clear_near_floor_is_not_blocked(self):
        frame = self.frame()
        frame[:108] = 240  # Wall occupies upper 45%; lower floor is clear.
        result = self.classify(frame)
        self.assertGreater(result['mid_cols'][1]['obst'], .45)
        self.assertFalse(result['blocked'])
        self.assertFalse(result['cliff'])

    def test_close_wall_extending_into_near_centre_is_blocked(self):
        frame = self.frame()
        frame[:205] = 240
        self.assertTrue(self.classify(frame)['blocked'])

    def test_low_near_obstacle_is_blocked_even_when_mid_view_is_clear(self):
        frame = self.frame()
        frame[175:230, 106:213] = 240
        result = self.classify(frame)
        self.assertLess(result['mid_cols'][1]['obst'], .1)
        self.assertTrue(result['blocked'])

    def test_corridor_side_walls_do_not_block_clear_centre(self):
        frame = self.frame()
        frame[:, :80] = frame[:, 240:] = 240
        self.assertFalse(self.classify(frame)['blocked'])

    def test_near_dark_area_is_reported_as_evidence_not_as_a_drop(self):
        # The camera cannot tell a dark wall from a dark hole at the same ground
        # line, so it publishes the darkness and draws no verdict. Floor IR owns
        # the cliff decision. See the comment above `cliff = False` in camera.py.
        frame = self.frame()
        frame[165:230, :100] = 5
        result = self.classify(frame)
        self.assertFalse(result['cliff'])
        self.assertGreater(result['cols'][0]['void'], .8)
        self.assertTrue(any(r['kind'] == 'dark_region' for r in result['regions']))

    def test_colored_side_tape_is_not_a_dark_drop(self):
        frame = self.frame()
        # Blue tape on the measured maze changes hue, but retains 80% of
        # floor brightness. Color alone cannot establish missing floor.
        frame[165:230, :100] = (80, 20, 20)
        result = self.classify(frame)
        self.assertFalse(result['cliff'])
        self.assertFalse(result['blocked'])
        self.assertGreater(result['cols'][0]['obst'], .8)

    def test_colored_near_centre_remains_an_obstacle_cue(self):
        frame = self.frame()
        frame[165:230, 106:213] = (80, 20, 20)
        result = self.classify(frame)
        self.assertFalse(result['cliff'])
        self.assertTrue(result['blocked'])

    def test_dark_colored_area_is_also_only_evidence(self):
        frame = self.frame()
        frame[165:230, :100] = (20, 5, 5)
        result = self.classify(frame)
        self.assertFalse(result['cliff'])
        self.assertGreater(result['cols'][0]['void'], .8)

    def test_gray_floor_does_not_depend_on_arbitrary_hue(self):
        result = classify_frame(self.frame(), floor_hsv=(90., 5., 100.),
                                allow_floor_update=False)
        self.assertFalse(result['blocked'])
        self.assertGreater(result['cols'][1]['floor'], .99)

    def test_tape_cannot_replace_trusted_gray_floor_over_time(self):
        frame = self.frame()
        frame[165:230, 48:272] = (100, 10, 10)
        reference = (0., 0., 100.)
        for _ in range(100):
            result = classify_frame(frame, floor_hsv=reference)
            reference = result['floor_hsv']
        self.assertEqual(reference, (0., 0., 100.))
        self.assertTrue(result['blocked'])

    def test_bright_wall_cannot_replace_trusted_floor(self):
        frame = np.full((240, 320, 3), 240, dtype=np.uint8)
        result = classify_frame(frame, floor_hsv=(0., 0., 100.))
        self.assertEqual(result['floor_hsv'], (0., 0., 100.))
        self.assertTrue(result['blocked'])

    def test_external_update_gate_freezes_reference(self):
        result = classify_frame(self.frame()+10, floor_hsv=(0., 0., 100.),
                                allow_floor_update=False)
        self.assertEqual(result['floor_hsv'], (0., 0., 100.))
        result = classify_frame(self.frame(), allow_floor_update=False)
        self.assertIsNone(result['floor_hsv'])

    def test_small_brightness_change_can_adapt_when_allowed(self):
        result = classify_frame(self.frame()+10, floor_hsv=(0., 0., 100.))
        self.assertGreater(result['floor_hsv'][2], 100.)

    def test_lights_off_is_unavailable_not_a_full_frame_obstacle(self):
        # A frozen daylight exposure produced a purple frame, gray p99=39.
        frame = np.full((240, 320, 3), (30, 15, 55), dtype=np.uint8)
        result = self.classify(frame)
        self.assertEqual(result['quality'], {'valid': False, 'reason': 'low_light'})
        self.assertEqual(result['regions'], [])
        self.assertFalse(result['blocked'])  # CameraPolicy owns the blindness hold.
        self.assertIsNone(result['floor_hsv'])

    def test_small_bright_lamp_does_not_make_dark_road_usable(self):
        frame = np.full((240, 320, 3), 30, dtype=np.uint8)
        frame[5:15, 5:15] = 255
        self.assertEqual(self.classify(frame)['quality']['reason'], 'low_light')

    def test_bright_ceiling_does_not_make_dark_road_usable(self):
        frame = np.full((240, 320, 3), 30, dtype=np.uint8)
        frame[:20, :100] = 255  # >1% of frame; road is still invisible.
        self.assertEqual(self.classify(frame)['quality']['reason'], 'low_light')

    def test_dim_road_with_visible_paint_is_not_discarded_as_blackout(self):
        frame = np.full((240, 320, 3), 35, dtype=np.uint8)
        frame[:, 60:75] = 100
        frame[:, 245:260] = 100
        self.assertTrue(self.classify(frame)['quality']['valid'])

    def test_local_dark_obstacle_on_lit_floor_remains_an_obstacle(self):
        frame = self.frame()
        frame[160:230, 110:210] = 30
        self.assertTrue(self.classify(frame)['quality']['valid'])
        self.assertTrue(self.classify(frame)['blocked'])

    def test_clipped_road_remains_invalid_with_dark_ceiling(self):
        frame = np.full((240, 320, 3), 255, dtype=np.uint8)
        frame[:70] = 80
        result = self.classify(frame)
        self.assertEqual(result['quality']['reason'], 'overexposed')
        self.assertFalse(result['quality']['valid'])
        self.assertEqual(result['regions'], [])

    def test_white_paint_and_small_glare_on_lit_road_remain_usable(self):
        frame = self.frame()
        frame[:, 60:75] = 255
        frame[:, 245:260] = 255
        frame[100:120, 130:150] = 255
        self.assertTrue(self.classify(frame)['quality']['valid'])

    def test_saturated_red_is_not_white_clipping(self):
        frame = np.full((240, 320, 3), (0, 0, 255), dtype=np.uint8)
        self.assertTrue(self.classify(frame)['quality']['valid'])
