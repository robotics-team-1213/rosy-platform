"""qwen_points writes one keypoints row per K-th frame and never overwrites."""
import json

import cv2
import numpy as np
import pytest

import qwen_points


def _video(path, n=7):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 8, (32, 24))
    if not w.isOpened():
        pytest.skip("no MJPG writer in this OpenCV build")
    for i in range(n):
        w.write(np.full((24, 32, 3), i * 20, np.uint8))
    w.release()


def test_every_kth_frame_gets_points(tmp_path, monkeypatch):
    video = tmp_path / "s.avi"; _video(video)
    asked = []
    monkeypatch.setattr(qwen_points, "ask", lambda img, url, model: asked.append(img.shape) or '[{"point_2d": [500, 500]}]')
    monkeypatch.setattr(qwen_points, "unload", lambda url, model: None)
    out = tmp_path / "keypoints.jsonl"
    qwen_points.main(["--video", str(video), "--every", "3", "--out", str(out)])
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert [r["frame"] for r in rows] == [0, 3, 6]
    assert rows[0]["drivable"] == [[16, 12]] and rows[0]["prompt_id"] == qwen_points.PROMPT_ID
    assert asked[0] == (24, 32, 3)


def test_refuses_existing_output(tmp_path):
    out = tmp_path / "keypoints.jsonl"; out.write_text("")
    with pytest.raises(SystemExit):
        qwen_points.main(["--video", str(tmp_path / "x.avi"), "--out", str(out)])
