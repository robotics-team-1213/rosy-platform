"""Check the rollout's camera and report contracts without MuJoCo or LeRobot."""
from contextlib import nullcontext, redirect_stderr
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import numpy as np

from tools.sim.omx_sim_policy_views import main, resolve_views, rollout_act


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

    def test_cli_writes_one_ik_video_per_seed(self):
        cameras = ("top", "side", "a_wrist", "b_wrist", "overview")
        layout = SimpleNamespace(choices={})
        world = Mock()
        world.model.ncam = len(cameras)
        world.model.camera.side_effect = lambda i: SimpleNamespace(name=cameras[i])
        world.render.return_value = np.zeros((480, 640, 3), dtype=np.uint8)
        step = {"id": "b1"}
        encode, close = Mock(), Mock()
        encoder = Mock(return_value=(encode, close))

        def make_teacher(world, *, seed, frame_hook):
            def run_single(here, step):
                frame_hook(seed, "settle")
                return {"result": "pass"}
            return SimpleNamespace(run_single=run_single)

        modules = {
            "omx_two_arm_sites": SimpleNamespace(Layout=Mock(return_value=layout), parse_choices=lambda _: {}),
            "omx_two_arm_tasks": SimpleNamespace(get_task=lambda *_: {"name": "rehandle", "steps": [step], "start": {}}),
            "omx_two_arm_teacher": SimpleNamespace(Teacher=make_teacher, FPS=15),
            "omx_two_arm_world": SimpleNamespace(World=Mock(return_value=world)),
            "omx_two_arm_teacher_stages": SimpleNamespace(open_rgb_video=encoder),
        }
        with TemporaryDirectory() as tmp, patch.dict(sys.modules, modules):
            out, video = Path(tmp) / "report.json", Path(tmp) / "videos"
            self.assertEqual(main(["--arm", "arm_b", "--model", "ik", "--out", str(out),
                                   "--video", str(video), "--episodes", "2", "--seed-base", "7"]), 0)
            self.assertTrue(video.is_dir())
            self.assertEqual([call.args for call in encoder.call_args_list],
                             [(video / f"ik-arm_b-{seed}.mp4", 2560, 480) for seed in (7, 8)])
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["passed"], 2)
        self.assertEqual(close.call_count, 2)
        self.assertEqual(encode.call_count, 2)
        self.assertEqual(encode.call_args.args[0].shape, (480, 2560, 3))
        self.assertEqual([call.args[1] for call in world.render.call_args_list],
                         ["top", "side", "b_wrist", "overview"] * 2)

    def test_act_row_records_pre_step_state_and_action_every_fifth_frame(self):
        teacher = Mock()
        teacher.world.layout.arms = ("arm_a",)
        teacher.world.pose.return_value = ([0, 0, 0], 0, 0)
        teacher.q_now.side_effect = ([frame] * 5 + [0] for frame in range(11))
        teacher.verdict.side_effect = lambda data, step, row, before: dict(row, result="fail")
        action = Mock()
        action.cpu.return_value.numpy.return_value = np.array([[9, 8, 7, 6, 5, 4]])
        torch = MagicMock()
        torch.inference_mode.side_effect = nullcontext
        rgb = np.zeros((2, 3, 3), dtype=np.uint8)
        teacher.world.render.return_value = rgb
        views = {"observation.images.rs": ("top", (2, 3))}
        record = Mock(side_effect=lambda _, frames: self.assertIs(frames[0], rgb))
        modules = {
            "torch": torch,
            "omx_two_arm_teacher": SimpleNamespace(FPS=11),
            "palletizing_gripper": SimpleNamespace(gap_m=lambda _: .03, angle_for_gap_clipped=lambda gap: gap),
            "cell_arm_cal": SimpleNamespace(default_profile=lambda _: {"held_30mm": 50, "gap_mm_per_unit": 1}),
            "cell_control_core": SimpleNamespace(rad_to_norm=float, norm_to_rad=float),
        }
        step = {"id": "a1", "arm": "arm_a", "container": "box", "from": "ship", "to": "temp"}
        with patch.dict(sys.modules, modules), patch.object(sys, "path", sys.path.copy()):
            row = rollout_act(teacher, {}, step, (Mock(), Mock(), Mock(return_value=action)), views, 1, "cpu", record)
        self.assertEqual(record.call_count, 11)
        self.assertEqual(teacher.world.render.call_count, 11)
        self.assertEqual(json.loads(json.dumps(row))["joint_trajectory"], [
            {"frame": frame, "state": [frame] * 5 + [50], "action": [9, 8, 7, 6, 5, 4]}
            for frame in (0, 5, 10)
        ])
