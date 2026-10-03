"""D-423 §3.6: CORE keeps the robot's learned-model status, read-only, per task."""
import json

import pytest

from core_features.vision.models import MODEL_STATUS_TOPICS, ModelStatusStore


def status(revision="object-det-r1", error=None, **extra):
    return json.dumps({"schema": "rosy.perception.learned_status/1", "model_revision": revision,
                       "last_error": error, "frames_inferred": 12, "latency_ms_p50": 210.5,
                       "skip_ratio": 0.0, **extra})


def test_topics_name_each_task_and_its_slot():
    assert MODEL_STATUS_TOPICS == {
        "perception/learned/status": ("lane_seg", "shadow"),
        "perception/learned/object_det/status": ("object_det", "active"),
    }


def test_snapshot_reports_known_tasks_with_age_and_staleness():
    store = ModelStatusStore(stale_after_s=5.0)
    assert store.snapshot(now=0.0) == {"tasks": []}
    store.accept("perception/learned/object_det/status", status(), now=10.0)
    store.accept("perception/learned/status", status("lane-r3", error="no shadow model loaded"), now=11.0)
    snap = store.snapshot(now=14.0)
    by_task = {t["task"]: t for t in snap["tasks"]}
    assert by_task["object_det"] == {
        "task": "object_det", "slot": "active", "model_revision": "object-det-r1", "last_error": None,
        "frames_inferred": 12, "latency_ms_p50": 210.5, "signed": None, "age_s": 4.0, "stale": False}
    assert by_task["lane_seg"]["slot"] == "shadow" and by_task["lane_seg"]["last_error"] == "no shadow model loaded"
    later = {t["task"]: t["stale"] for t in store.snapshot(now=15.5)["tasks"]}
    assert later == {"object_det": True, "lane_seg": False}


@pytest.mark.parametrize("raw", ["not json", "[]", json.dumps({"schema": "other/1"}),
                                 status(revision=7), status(error={"x": 1})])
def test_malformed_status_is_dropped_not_stored(raw):
    store = ModelStatusStore()
    assert store.accept("perception/learned/object_det/status", raw, now=1.0) is False
    assert store.snapshot(now=1.0) == {"tasks": []}


def test_unknown_topic_and_overlong_text_are_dropped():
    store = ModelStatusStore()
    assert store.accept("perception/learned/other/status", status(), now=1.0) is False
    assert store.accept("perception/learned/status", status(error="x" * 5000), now=1.0) is False
    assert store.accept("perception/learned/status", status(error="x" * 1000), now=1.0) is True
    assert len(store.snapshot(now=1.0)["tasks"][0]["last_error"]) <= 200


def test_signed_passes_through_when_the_node_reports_it():
    """lane_seg is warn-only (2026-10-03): its status says signed false; absent stays None."""
    store = ModelStatusStore()
    store.accept("perception/learned/status", status("lane-r3", signed=False), now=1.0)
    store.accept("perception/learned/object_det/status", status(), now=1.0)
    by_task = {t["task"]: t for t in store.snapshot(now=1.0)["tasks"]}
    assert by_task["lane_seg"]["signed"] is False and by_task["object_det"]["signed"] is None
