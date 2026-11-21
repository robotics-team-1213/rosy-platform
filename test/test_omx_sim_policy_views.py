"""The checkpoint's camera contract can be checked without MuJoCo or LeRobot."""
from contextlib import redirect_stderr
from io import StringIO
import json
import unittest
from unittest.mock import patch

from tools.sim.omx_sim_policy_views import main, resolve_views


def features(*names):
    return {
        "observation.state": {"shape": [6]},
        **{f"observation.images.{name}": {"shape": [3, 480, 640]} for name in names},
    }


class ViewMapTests(unittest.TestCase):
    def test_default_and_purple_sy_views(self):
        self.assertEqual(resolve_views(features("top", "wrist"), "arm_b"), {
            "observation.images.top": ("top", (480, 640)),
            "observation.images.wrist": ("b_wrist", (480, 640)),
        })
        self.assertEqual(
            resolve_views(features("top"), "arm_b", "top=side")["observation.images.top"],
            ("side", (480, 640)),
        )
        self.assertEqual(resolve_views(features("rs", "wrist"), "arm_a", "rs=top,wrist=wrist"), {
            "observation.images.rs": ("top", (480, 640)),
            "observation.images.wrist": ("a_wrist", (480, 640)),
        })

    def test_explicit_map_must_cover_every_model_view(self):
        for mapping in (None, "wrist=wrist"):
            with self.subTest(mapping=mapping), self.assertRaisesRegex(ValueError, "unmapped.*rs"):
                resolve_views(features("rs", "wrist"), "arm_a", mapping)

    def test_invalid_mapping(self):
        for mapping in ("top", "top=", "top=side,", "top=side,top=top", "top=absent", "rs=top,top=side"):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                resolve_views(features("top"), "arm_b", mapping)

    def test_uses_each_view_shape_and_rejects_non_rgb(self):
        config = features("top", "wrist")
        config["observation.images.wrist"]["shape"] = [3, 240, 320]
        self.assertEqual(resolve_views(config, "arm_a")["observation.images.wrist"], ("a_wrist", (240, 320)))
        config["observation.images.wrist"]["shape"] = [1, 240, 320]
        with self.assertRaisesRegex(ValueError, "RGB"):
            resolve_views(config, "arm_a")

    def test_cli_refuses_missing_view_from_checkpoint_before_loading_model(self):
        config = {"type": "act", "input_features": features("rs", "wrist"),
                  "output_features": {"action": {"shape": [6]}}}
        stderr = StringIO()
        with patch("pathlib.Path.read_text", return_value=json.dumps(config)), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as failure:
                main(["--arm", "arm_a", "--model", "checkpoint", "--out", "unused.json"])
        self.assertEqual(failure.exception.code, 2)
        self.assertIn("unmapped checkpoint camera views: rs", stderr.getvalue())
