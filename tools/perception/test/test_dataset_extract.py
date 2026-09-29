import json

import cv2
import numpy as np
import pytest

import extract
from frames import FrameSelector


def _img(x):
    im = np.zeros((48, 64, 3), np.uint8)
    im[:, x:x + 8] = 255
    return im


def test_selector_rules():
    s = FrameSelector(min_interval_s=0.5, max_hamming=4)
    assert s.accept(0.0, _img(5))
    assert not s.accept(0.1, _img(40))
    assert not s.accept(1.0, _img(5))
    assert s.accept(1.0, _img(40))


def test_extract_video(tmp_path):
    vid = tmp_path / "v.avi"
    w = cv2.VideoWriter(str(vid), cv2.VideoWriter_fourcc(*"MJPG"), 8.0, (64, 48))
    assert w.isOpened()
    for i in range(24):
        w.write(_img(i * 2))
    w.release()
    out = tmp_path / "out"
    assert extract.main([str(vid), "--out", str(out)]) == 0
    rows = [json.loads(l) for l in (out / "frames.jsonl").read_text().splitlines()]
    assert 1 <= len(rows) <= 7
    for r in rows:
        assert (out / "frames" / f"{r['index']:06d}.jpg").is_file()
        assert {"index", "t", "source", "session", "side"} <= set(r)


def test_image_to_bgr_encodings():
    rgb = np.array([[[10, 20, 30]]], np.uint8)
    got = extract.image_to_bgr("rgb8", 1, 1, 3, rgb.tobytes())
    assert got[0, 0].tolist() == [30, 20, 10]
    got = extract.image_to_bgr("bgr8", 1, 1, 3, rgb.tobytes())
    assert got[0, 0].tolist() == [10, 20, 30]
    # mono8 with row padding (step 4, width 2)
    got = extract.image_to_bgr("mono8", 2, 2, 4, bytes([1, 2, 0, 0, 3, 4, 0, 0]))
    assert got.shape == (2, 2, 3) and got[1, 1].tolist() == [4, 4, 4]
    with pytest.raises(ValueError):
        extract.image_to_bgr("16UC1", 1, 1, 2, b"\0\0")
