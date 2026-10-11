"""edge_capture.distinct: one sample per second, kept only when the view changed."""
import numpy as np

import edge_capture


def _thumb(level):
    return np.full((30, 40), level, np.uint8)


def test_one_sample_per_gap_and_only_changed_views():
    items = [(0.0, 0), (0.5, 100), (1.0, 5), (2.0, 50), (2.4, 200), (3.1, 60), (4.2, 120)]
    kept = [t for t, _ in edge_capture.distinct(items, thumb_of=_thumb)]
    # 0.5 and 2.4 fall inside the 1 s gap; 1.0 (diff 5) and 3.1 (diff 10) are the same view.
    assert kept == [0.0, 2.0, 4.2]


def test_gap_counts_from_the_last_sample_not_the_last_kept():
    items = [(0.0, 0), (1.0, 0), (1.5, 255), (2.0, 255)]
    # 1.0 is sampled (same view, dropped), so 1.5 is inside the gap; 2.0 is the new view.
    assert [t for t, _ in edge_capture.distinct(items, thumb_of=_thumb)] == [0.0, 2.0]


def test_undecodable_frames_are_skipped():
    items = [(0.0, None), (1.0, 7)]
    out = list(edge_capture.distinct(items, thumb_of=lambda p: None if p is None else _thumb(p)))
    assert out == [(1.0, 7)]


def test_thumb_decodes_a_jpeg_to_40x30_grey():
    import cv2
    jpg = cv2.imencode(".jpg", np.full((240, 320, 3), 128, np.uint8))[1].tobytes()
    assert edge_capture.thumb(jpg).shape == (30, 40)
    assert edge_capture.thumb(b"not a jpeg") is None
