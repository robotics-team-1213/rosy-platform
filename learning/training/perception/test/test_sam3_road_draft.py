"""sam3_road_draft host-side logic: row/keypoint checks and tracking segments (no SAM, no GPU)."""
import json
import types

import numpy as np
import pytest

import sam3_road_draft as srd

SHA = "a" * 64


def test_select_rows_skips_other_videos_and_out_of_range_frames():
    rows = [{"source_video_sha256": SHA, "video_frame": 0},
            {"source_video_sha256": "b" * 64, "video_frame": 1},
            {"source_video_sha256": SHA, "video_frame": 10},
            {"source_video_sha256": SHA, "video_frame": 9}]
    kept, skipped = srd.select_rows(rows, SHA, 10)
    assert [i for i, _ in kept] == [0, 3]
    assert [s["row"] for s in skipped] == [1, 2] and skipped[0]["reason"] == "other video"


def test_load_keypoints_refuses_other_spacing_or_video(tmp_path):
    p = tmp_path / "k.jsonl"
    p.write_text(json.dumps({"frame": 0, "every": 15, "video_sha256": SHA, "drivable": [[1, 2]]}) + "\n")
    assert srd.load_keypoints(p, 15, SHA) == {0: [[1, 2]]}
    with pytest.raises(SystemExit):
        srd.load_keypoints(p, 10, SHA)
    with pytest.raises(SystemExit):
        srd.load_keypoints(p, 15, "b" * 64)


class FakeTracker:
    """Records seeds; propagate yields k..k+max inclusive, as SAM 3 2345a4ad does."""

    def __init__(self, n):
        self.n, self.calls, self.cleared = n, [], 0

    def init_state(self, video_path, offload_video_to_cpu):
        return {}

    def clear_all_points_in_video(self, state):
        self.cleared += 1

    def add_new_points_or_box(self, inference_state, frame_idx, obj_id, points, labels):
        self.calls.append((frame_idx, len(points)))

    def propagate_in_video(self, state, start_frame_idx, max_frame_num_to_track, reverse, propagate_preflight):
        for fi in range(start_frame_idx, min(self.n, start_frame_idx + max_frame_num_to_track + 1)):
            m = np.zeros((1, 1, 24, 32), np.float32)
            m[0, 0, 12:, :] = start_frame_idx + 1        # tag each frame with the segment that wrote it
            yield fi, [1], None, m, None


FAKE_TORCH = types.SimpleNamespace(tensor=lambda v, dtype=None: v, ones=lambda n, dtype=None: [1] * n,
                                   float32=None, int32=None)


def test_track_carpet_covers_every_frame_once_with_reseed_each_keyframe():
    n, every = 10, 4
    rgb = {k: np.full((24, 32, 3), 90, np.uint8) for k in range(0, n, every)}
    lane = np.zeros((n, 24, 32), bool)
    tracker = FakeTracker(n)
    carpet, seeds = srd.track_carpet(tracker, "frames", rgb, lane, {0: [[5, 20]], 4: [], 8: [[40, 20]]}, every, FAKE_TORCH)
    assert [k for k, _ in tracker.calls] == [0, 4, 8] and tracker.cleared == 3
    assert tracker.calls[0][1] == 2 and tracker.calls[1][1] == 1   # footprint (+ gated Qwen point)
    assert [s["qwen"] for s in seeds] == [1, 0, 1] and [s["kept"] for s in seeds] == [2, 1, 1]  # x=40 is off-image
    assert carpet[:, 12:, :].all() and not carpet[:, :12, :].any()
