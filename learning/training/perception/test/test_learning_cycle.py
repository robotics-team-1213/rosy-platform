"""Continuous training integrity, duplicate prevention and bounded retry."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))
import learning_cycle as cycle
from job_state import Rejected
from store import Store


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "store")
    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.json").write_text(json.dumps({"schema": "rosy.perception.dataset/1",
        "frames": [{"session": "a", "split": "train"}, {"session": "b", "split": "val"}]}))
    _, sha = store.put_dataset(source, "lanes")
    requests = tmp_path / "requests"
    requests.mkdir()
    (requests / "first.json").write_text(json.dumps({"dataset": "lanes@" + sha, "purpose": "research"}))
    config = {"trainer": {"store": str(store.root)}, "recipes": [{"base": 8}, {"base": 16}],
              "requests_dir": str(requests), "reviews_dir": str(tmp_path / "reviews"),
              "interval_s": 2, "max_attempts": 2}
    return config, tmp_path / "state", requests


def test_duplicate_request_and_restart_do_not_retrain_ready(setup):
    config, out, requests = setup
    calls = []
    fn = lambda cfg, path: calls.append(cfg) or {"revision": "candidate"}
    cycle.run_once(config, out, trainer_fn=fn)
    (requests / "copy.json").write_bytes((requests / "first.json").read_bytes())
    state = cycle.run_once(config, out, trainer_fn=fn)
    assert len(calls) == 2
    assert all(row["status"] == "ready" for row in state["cycles"].values())


def test_one_quality_rejection_does_not_stop_other_recipe_or_retry(setup):
    config, out, _ = setup
    calls = []
    def fn(cfg, path):
        calls.append(cfg["training"]["base"])
        if cfg["training"]["base"] == 8:
            raise Rejected("fixed eval regression")
        return {"revision": "passed"}
    cycle.run_once(config, out, trainer_fn=fn)
    state = cycle.run_once(config, out, trainer_fn=fn)
    assert calls == [8, 16]
    assert sorted(r["status"] for r in state["cycles"].values()) == ["ready", "rejected"]


def test_transient_retry_is_bounded_across_restart(setup):
    config, out, _ = setup
    calls = []
    def fn(cfg, path):
        calls.append(cfg)
        raise OSError("GPU unavailable")
    for _ in range(3):
        state = cycle.run_once(config, out, trainer_fn=fn)
    assert len(calls) == 4
    assert all(r["status"] == "gave_up" for r in state["cycles"].values())


def test_mutated_request_and_dataset_never_launch_gpu(setup):
    config, out, requests = setup
    cycle.run_once(config, out, trainer_fn=lambda cfg, path: {})
    (requests / "first.json").write_text('{"purpose":"research","dataset":"different"}')
    state = cycle.run_once(config, out, trainer_fn=lambda *args: pytest.fail("must not train"))
    assert state["requests"][str(requests / "first.json")]["status"] == "blocked"


def test_mutated_dataset_never_launches_gpu(setup):
    config, out, requests = setup
    request = json.loads((requests / "first.json").read_text())
    dataset = Store(config["trainer"]["store"]).dataset_path(*cycle.parse_dataset_ref(request["dataset"]))
    (dataset / "extra").write_text("changed bytes")
    state = cycle.run_once(config, out, trainer_fn=lambda *args: pytest.fail("must not train"))
    assert "content hash" in state["requests"][str(requests / "first.json")]["error"]


def test_any_fixed_eval_session_overlap_is_blocked(setup):
    config, out, requests = setup
    store = Store(config["trainer"]["store"])
    evaluation = store.evalsets_dir / "other" / ("a" * 64)
    evaluation.mkdir(parents=True)
    (evaluation / "manifest.json").write_text(json.dumps({"frames": [{"session": "b"}]}))
    evaluation.rename(evaluation.parent / cycle.content_sha(evaluation))
    state = cycle.run_once(config, out, trainer_fn=lambda *args: pytest.fail("must not train"))
    assert "fixed eval" in state["requests"][str(requests / "first.json")]["error"]


def test_reserved_eval_session_blocks_training_before_eval_version_exists(setup):
    config, out, requests = setup
    Store(config["trainer"]["store"]).reserve_eval_source("b", "group-b")
    state = cycle.run_once(config, out, trainer_fn=lambda *args: pytest.fail("must not train"))
    assert "reserved eval" in state["requests"][str(requests / "first.json")]["error"]


def test_reserved_eval_group_blocks_other_training_session(setup):
    config, out, requests = setup
    st = Store(config["trainer"]["store"])
    st.reserve_eval_source("heldout", "group-a")
    request = json.loads((requests / "first.json").read_text())
    source = st.dataset_path(*cycle.parse_dataset_ref(request["dataset"]))
    doc = json.loads((source / "manifest.json").read_text())
    doc["frames"][0]["capture_group"] = "group-a"
    doc["frames"][1]["capture_group"] = "group-b"
    candidate = out.parent / "group-source"
    candidate.mkdir()
    (candidate / "manifest.json").write_text(json.dumps(doc))
    _, digest = st.put_dataset(candidate, "lanes")
    request["dataset"] = "lanes@" + digest
    (requests / "first.json").write_text(json.dumps(request))
    state = cycle.run_once(config, out, trainer_fn=lambda *args: pytest.fail("must not train"))
    assert "reserved eval capture group" in state["requests"][str(requests / "first.json")]["error"]


def make_review(tmp_path, excluded=False):
    folder = tmp_path / "export"
    (folder / "inputs/images").mkdir(parents=True)
    image = folder / "inputs/images/000000.jpg"
    image.write_bytes(b"immutable source image")
    source = {"index": 0, "video": "session.mp4", "video_frame": 3, "image_sha256": cycle.sha(image)}
    human = dict(source, review_status="approved", complete_frame_review=True)
    if excluded:
        human["disposition"] = "excluded_by_user"
    (folder / "inputs/source.jsonl").write_text(json.dumps(source) + "\n")
    (folder / "inputs/human.jsonl").write_text(json.dumps(human) + "\n")
    doc = {"schema": "rosy.object-review-return/1", "exported_frames": 1,
           "source_sha256": cycle.sha(folder / "inputs/source.jsonl"),
           "human_sha256": cycle.sha(folder / "inputs/human.jsonl"), "files": []}
    for path in sorted((folder / "inputs").rglob("*")):
        if path.is_file():
            doc["files"].append({"path": path.relative_to(folder).as_posix(),
                                 "sha256": cycle.sha(path), "bytes": path.stat().st_size})
    (folder / "manifest.json").write_text(json.dumps(doc))
    (folder / "COMPLETE").write_text(cycle.sha(folder / "manifest.json"))
    return folder


def test_review_integrity_and_explicit_exclusion_cannot_qualify_training(tmp_path):
    folder = make_review(tmp_path)
    assert cycle.verified_export(folder)["training_dataset_qualified"] is False
    (folder / "inputs/images/000000.jpg").write_bytes(b"tampered source")
    with pytest.raises(cycle.JobError, match="integrity"):
        cycle.verified_export(folder)


def test_excluded_review_cannot_be_resurrected_as_approved(tmp_path):
    with pytest.raises(cycle.JobError, match="excluded"):
        cycle.verified_export(make_review(tmp_path, excluded=True))


def test_incomplete_export_is_not_counted(setup):
    config, out, _ = setup
    (Path(config["reviews_dir"]) / "partial").mkdir(parents=True)
    state = cycle.run_once(config, out, trainer_fn=lambda cfg, path: {})
    assert state["reviews"] == {}


def test_review_generations_do_not_resurrect_older_approval():
    identity = {"index": 0, "video": "original.mp4", "video_frame": 12,
                "image_sha256": "a" * 64}
    approved = dict(identity, review_status="approved", complete_frame_review=True, boxes=[])
    excluded = dict(identity, review_status="pending", complete_frame_review=False,
                    disposition="excluded_by_user", boxes=[])
    exports = [{"manifest_sha": "old", "frames": [approved]},
               {"manifest_sha": "new", "frames": [excluded]}]
    queue = cycle.review_queue(exports)
    assert len(queue) == 1
    assert queue[0]["status"] == "conflict"
    assert queue[0]["decision"] is None
    assert queue[0]["training_dataset_qualified"] is False
    assert cycle.review_queue(list(reversed(exports))) == queue


def test_identical_frame_decisions_deduplicate_across_export_local_indices():
    row = {"index": 0, "video": "original.mp4", "video_frame": 12,
           "image_sha256": "a" * 64, "review_status": "approved",
           "complete_frame_review": True, "boxes": []}
    queue = cycle.review_queue([{"manifest_sha": "a", "frames": [row]},
                                {"manifest_sha": "b", "frames": [dict(row, index=42)]}])
    assert len(queue) == 1 and queue[0]["status"] == "agreed"
    assert queue[0]["decision"]["review_status"] == "approved"
    assert queue[0]["exports"] == ["a", "b"]


def test_removed_export_cannot_remain_current_verified_progress(setup):
    import shutil
    config, out, _ = setup
    folder = make_review(Path(config["reviews_dir"]))
    first = cycle.run_once(config, out, trainer_fn=lambda cfg, path: {})
    assert first["review_queue"][0]["status"] == "agreed"
    shutil.rmtree(folder)
    second = cycle.run_once(config, out, trainer_fn=lambda cfg, path: {})
    assert second["review_queue"] == []
    assert second["reviews"][str(folder)]["status"] == "unavailable"
