"""VLM mask feedback must stay outside review and training authority."""
import hashlib
import json
import sqlite3

import cv2
import numpy as np
import pytest

from vlm_mask_feedback import analyze, read_current_feedback, publish_feedback


def _workspace(tmp_path, mask_path="mask.png"):
    state = tmp_path / "state"
    state.mkdir()
    image = np.full((8, 8, 3), 90, np.uint8)
    mask = np.full((8, 8), 5, np.uint8)
    mask[0, 0] = 255
    photo_bytes = cv2.imencode(".png", image)[1].tobytes()
    mask_bytes = cv2.imencode(".png", mask)[1].tobytes()
    (state / "photo.png").write_bytes(photo_bytes)
    (state / "mask.png").write_bytes(mask_bytes)
    source = {"image": "photo.png", "image_sha256": hashlib.sha256(photo_bytes).hexdigest(),
              "width": 8, "height": 8}
    classes = {"classes": [{"index": 0, "role": "background", "color": [0, 0, 0]},
                            {"index": 5, "role": "drivable", "color": [0, 255, 0]}]}
    db = sqlite3.connect(state / "reviews.sqlite3")
    db.executescript("CREATE TABLE frames (id INTEGER, source TEXT);"
                     "CREATE TABLE masks (frame INTEGER, status TEXT, path TEXT, sha256 TEXT);"
                     "CREATE TABLE metadata (key TEXT, value TEXT);")
    db.execute("INSERT INTO frames VALUES (0, ?)", (json.dumps(source),))
    db.execute("INSERT INTO masks VALUES (0, 'pending', ?, ?)",
               (mask_path, hashlib.sha256(mask_bytes).hexdigest()))
    db.executemany("INSERT INTO metadata VALUES (?, ?)",
                   [("workspace_id", "v13-test"), ("generation", "7"),
                    ("pixel_classes", json.dumps(classes))])
    db.commit()
    db.close()
    return state


def test_feedback_reports_unknown_pixels_without_changing_review(tmp_path):
    state = _workspace(tmp_path)
    before = (state / "reviews.sqlite3").read_bytes()
    seen = []

    def ask(original, overlay):
        seen.append((original, overlay))
        return {"verdict": "concern", "issue": "missed_visible_road",
                "note": "Visible floor may be missing"}

    report = analyze(state, ask, model_digest="model-sha")
    assert report["schema"] == "rosy.v13-vlm-feedback/1"
    assert report["workspace_id"] == "v13-test"
    assert report["generation"] == "7"
    assert report["frames"][0]["unknown_pixels"] == 1
    assert report["frames"][0]["review_blocked"] is True
    assert report["frames"][0]["feedback"]["verdict"] == "concern"
    assert seen and len(seen[0]) == 2
    assert (state / "reviews.sqlite3").read_bytes() == before


def test_feedback_refuses_mask_outside_workspace(tmp_path):
    state = _workspace(tmp_path, "../outside.png")
    with pytest.raises(ValueError, match="outside workspace"):
        analyze(state, lambda *_: {}, model_digest="model-sha")


def test_model_failure_abstains_and_keeps_review_pending(tmp_path):
    state = _workspace(tmp_path)

    def fail(*_):
        raise TimeoutError("model unavailable")

    report = analyze(state, fail, model_digest="model-sha")
    assert report["frames"][0]["feedback"]["verdict"] == "abstain"
    db = sqlite3.connect(state / "reviews.sqlite3")
    assert db.execute("SELECT status FROM masks").fetchone() == ("pending",)
    db.close()


def test_review_feedback_is_visible_only_for_current_mask(tmp_path):
    state = _workspace(tmp_path)
    report = analyze(state, lambda *_: {"verdict": "uncertain", "issue": "uncertain_visibility",
                                            "note": "Check the road edge"}, model_digest="model-sha")
    publish_feedback(state, report)
    current = read_current_feedback(state, 0)
    assert current["available"] is True
    assert current["current"] is True
    assert current["feedback"]["note"] == "Check the road edge"
    db = sqlite3.connect(state / "reviews.sqlite3")
    db.execute("UPDATE metadata SET value='8' WHERE key='generation'")
    db.commit()
    db.close()
    assert read_current_feedback(state, 0)["current"] is True
    db = sqlite3.connect(state / "reviews.sqlite3")
    db.execute("UPDATE masks SET sha256=? WHERE frame=0", ("0" * 64,))
    db.commit()
    db.close()
    assert read_current_feedback(state, 0)["current"] is False


def test_stale_report_cannot_replace_visible_feedback(tmp_path):
    state = _workspace(tmp_path)
    report = analyze(state, lambda *_: {"verdict": "uncertain", "issue": "none", "note": "check"},
                     model_digest="model-sha")
    report["stale"] = True
    with pytest.raises(ValueError, match="stale"):
        publish_feedback(state, report)
    assert not (state / "vlm-feedback.json").exists()


def test_review_app_serves_advisory_feedback_without_approval(tmp_path):
    import threading
    import urllib.request

    from review_app import ReviewStore, make_server
    import review_evidence
    import review_masks
    from test_review_return import fixture_inputs

    source, human, images = fixture_inputs(tmp_path)
    store = ReviewStore(tmp_path / "review", source, human, images)
    with store.connect() as db:
        db.execute("INSERT INTO masks(frame,version,status,complete,background) "
                   "VALUES (0,0,'pending',0,0)")
    frame = store.get(0)
    mask = review_masks.get(store, 0)
    report = {"schema": "rosy.v13-vlm-feedback/1", "advisory_only": True,
              "training_admission": False, "model": "qwen3-vl:8b-instruct", "model_digest": "abc",
              "workspace_id": review_evidence.metadata(store, "workspace_id"),
              "generation": review_evidence.metadata(store, "generation"),
              "stale": False, "eligible_frames_at_snapshot": 1,
              "frames": [{"frame": 0, "image_sha256": frame["source"]["image_sha256"],
                          "mask_sha256": mask["sha256"], "unknown_pixels": 5,
                          "review_blocked": True,
                          "feedback": {"verdict": "concern", "issue": "uncertain_visibility",
                                       "note": "Inspect boundary"}}]}
    (store.state / "vlm-feedback.json").write_text(json.dumps(report), encoding="utf-8")
    server = make_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/vlm-feedback/0"
        response = json.load(urllib.request.urlopen(url))
        assert response["available"] is True
        assert response["current"] is True
        assert response["feedback"]["note"] == "Inspect boundary"
        assert review_masks.get(store, 0)["status"] == mask["status"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
