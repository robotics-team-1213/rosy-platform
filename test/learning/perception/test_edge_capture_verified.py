"""edge_capture.verified_row / match_video_frames: the review_ingest row of one edge frame."""
import hashlib

import pytest

import edge_capture


def test_row_binds_image_mask_and_classes_by_sha256(tmp_path):
    png, mask = b"png-bytes", b"mask-bytes"
    row = edge_capture.verified_row(
        session="S", capture_group="edge-spin-S", collection="c", video_name="v.mp4",
        video_sha256="a" * 64, video_frame=7, video_time_s=0.875, width=320, height=240,
        image_path=tmp_path / "S__vf000007.png", png=png, mask_rel="drafts/000003.png", mask=mask,
        classes_sha256="b" * 64)
    assert row["image_sha256"] == hashlib.sha256(png).hexdigest()
    assert row["mask"] == {"indexed_png": "drafts/000003.png", "sha256": hashlib.sha256(mask).hexdigest(),
                           "classes_sha256": "b" * 64}
    # review_ingest needs exactly these keys for an indexed draft.
    assert set(row["mask"]) == {"indexed_png", "sha256", "classes_sha256"}
    assert row["image"] == str(tmp_path / "S__vf000007.png") and row["video_frame"] == 7
    assert row["timestamp_basis"] == "camera_header_stamp"


def test_video_frames_match_by_exact_log_time():
    side = [{"index": 0, "log_ns": 10}, {"index": 1, "log_ns": 20}, {"index": 2, "log_ns": 30}]
    edges = [{"index": 0, "log_ns": 10}, {"index": 1, "log_ns": 30}]
    assert edge_capture.match_video_frames(side, edges) == {0: edges[0], 2: edges[1]}
    with pytest.raises(ValueError):
        edge_capture.match_video_frames(side, [{"index": 0, "log_ns": 11}])
