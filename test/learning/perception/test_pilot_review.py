"""Pilot originals become portable, pending Learning inputs through the existing importer."""
import hashlib
import json
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

import bag_to_video
import fetch_http


@pytest.fixture
def recording(tmp_path):
    session = tmp_path / "raw" / "20261002T101500Z_rosy_01"
    (session / "bag").mkdir(parents=True)
    (session / "bag" / "bag_0.mcap").write_bytes(b"source bag fixture")
    meta = {"device": "rosy_01", "started_at": "2026-10-02T10:15:00Z"}
    (session / "session.json").write_text(json.dumps(meta))
    files = [{"path": p.relative_to(session).as_posix(), "bytes": p.stat().st_size,
              "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in [session / "session.json", session / "bag" / "bag_0.mcap"]]
    (session / "manifest.json").write_text(json.dumps(
        {"schema": fetch_http.MANIFEST_SCHEMA, "id": session.name, "files": files}))
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    video = video_dir / (bag_to_video.output_stem(session, meta) + ".mp4")
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 2, (32, 24))
    assert writer.isOpened(), "real MP4 codec is required"
    for value in (40, 90, 150, 220):
        writer.write(np.full((24, 32, 3), value, np.uint8))
    writer.release()
    rows = [{"index": i, "t": 10.0 + i * 0.5,
             "side": {"cmd_vel": {"linear": 0.1}, "teleop/intent": {"accepted": i != 1}}}
            for i in range(4)]
    sidecar = video.with_suffix(".jsonl")
    sidecar.write_text("".join(json.dumps(row) + "\n" for row in rows))
    video.with_suffix(".json").write_text(json.dumps(
        {"source": {"session": session.name}, "video": {"frames": 4}}))
    fetch_http._write_paired_receipt(session.parent, session.name, sidecar)
    classes = Path(__file__).resolve().parents[3] / "learning/curation/perception/classes/lane_lr6_drivable.yaml"
    return session, video_dir, tmp_path / "prepared", classes


def test_prepare_keeps_source_identity_exact_frames_and_class_binding(recording):
    import pilot_review
    session, videos, out, classes = recording
    catalog = pilot_review.prepare(session, videos, out, classes)
    rows = [json.loads(line) for line in catalog.read_text().splitlines()]
    assert [r["video_frame"] for r in rows] == [0, 2, 3]
    assert all(r["source_session"] == session.name for r in rows)
    assert all(r["capture_group"] == "pilot-" + session.name for r in rows)
    assert not any("mask" in r or "objects" in r for r in rows)
    assert (catalog.parent / "classes.yaml").read_bytes() == classes.read_bytes()
    for row in rows:
        assert hashlib.sha256((catalog.parent / row["image"]).read_bytes()).hexdigest() == row["image_sha256"]
    assert pilot_review.prepare(session, videos, out, classes) == catalog


def test_prepare_refuses_changed_raw_and_never_rewrites_prepared_inputs(recording):
    import pilot_review
    session, videos, out, classes = recording
    catalog = pilot_review.prepare(session, videos, out, classes)
    before = catalog.read_bytes()
    (session / "bag" / "bag_0.mcap").write_bytes(b"changed")
    with pytest.raises((ValueError, fetch_http.FetchError)):
        pilot_review.prepare(session, videos, out, classes)
    assert catalog.read_bytes() == before


def test_prepare_refuses_changed_sidecar_and_tampered_prepared_image(recording):
    import pilot_review
    session, videos, out, classes = recording
    catalog = pilot_review.prepare(session, videos, out, classes)
    row = json.loads(catalog.read_text().splitlines()[0])
    (catalog.parent / row["image"]).write_bytes(b"changed")
    with pytest.raises(ValueError):
        pilot_review.prepare(session, videos, out, classes)
    next(videos.glob("*.jsonl")).write_text("{}\n")
    with pytest.raises((ValueError, fetch_http.FetchError)):
        pilot_review.prepare(session, videos, out.parent / "another", classes)


def test_pipeline_import_is_pending_idempotent_and_preserves_human_reviews(recording, tmp_path):
    import pilot_review
    import review_masks
    from review_store import ReviewStore
    session, videos, out, classes = recording
    state = tmp_path / "review-state"
    store = ReviewStore(state, empty_training=True)
    args = ["--raw-root", str(session.parent), "--video-dir", str(videos), "--out", str(out),
            "--classes", str(classes), "--state", str(state)]
    assert pilot_review.main(args) == 0
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == 3
        assert {r[0] for r in db.execute("SELECT status FROM frames")} == {"pending"}
    mask = review_masks.get(store, 0)
    filled = review_masks.update(store, 0, dict(version=mask['version'], action='fill', label=0), ValueError)
    approved = review_masks.update(store, 0, dict(version=filled['version'], action='approve',
        complete_frame_review=True, background_reviewed=True), ValueError, actor='test-human')
    history = store.history(0)
    assert pilot_review.main(args) == 0
    assert review_masks.get(store, 0) == approved
    assert store.history(0) == history
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == 3


def test_pipeline_requires_an_existing_workspace_before_any_outputs(recording, tmp_path):
    import pilot_review
    session, videos, out, classes = recording
    assert pilot_review.main(["--raw-root", str(session.parent), "--video-dir", str(videos),
        "--out", str(out), "--classes", str(classes), "--state", str(tmp_path / "missing")]) != 0
    assert not out.exists()


@pytest.mark.skipif(not os.environ.get("ROSY_PILOT_RECORDING_ID"), reason="explicit model-PC recording required")
def test_existing_model_pc_recording_reaches_a_separate_pending_workspace(tmp_path):
    import pilot_review
    from review_store import ReviewStore
    session = Path(os.environ["ROSY_PILOT_RAW_ROOT"]) / os.environ["ROSY_PILOT_RECORDING_ID"]
    videos = Path(os.environ["ROSY_PILOT_VIDEO_ROOT"])
    evidence = Path(os.environ["ROSY_PILOT_EVIDENCE_ROOT"])
    assert not evidence.exists(), "a new evidence directory is required"
    evidence.mkdir(parents=True)
    state, out = evidence / "state", evidence / "prepared"
    store = ReviewStore(state, empty_training=True)
    classes = Path(__file__).resolve().parents[3] / "learning/curation/perception/classes/lane_lr6_drivable.yaml"
    args = ["--raw-root", str(session.parent), "--video-dir", str(videos), "--out", str(out),
            "--classes", str(classes), "--state", str(state), "--only", session.name]
    assert pilot_review.main(args) == 0
    catalog = out / session.name / "verified-inputs.jsonl"
    rows = [json.loads(line) for line in catalog.read_text().splitlines()]
    assert rows and all(row["source_session"] == session.name for row in rows)
    with store.connect() as db:
        count = db.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
        assert count == len(rows)
        assert {row[0] for row in db.execute("SELECT status FROM frames")} == {"pending"}
    assert pilot_review.main(args) == 0
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == count
    print(json.dumps({"real_recording": session.name, "prepared_frames": count,
                      "pending_workspace": str(state), "catalog_sha256": fetch_http._sha256(catalog)}))
