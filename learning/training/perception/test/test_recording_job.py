"""Recording provenance, held-out refusal, and interrupted curation recovery."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))
from recording_job import prepare, validate_config  # noqa: E402
from job_state import JobError, Rejected  # noqa: E402
from store import content_sha  # noqa: E402


def config(tmp_path):
    recordings = []
    for session in ("train-a", "train-b"):
        video = tmp_path / f"{session}.mp4"
        video.write_bytes(b"video fixture; not decoded")
        video.with_suffix(".jsonl").write_text('{}\n')
        video.with_suffix(".json").write_text(json.dumps({
            "schema": "rosy.teleop.video/1", "source": {"session": session},
            "session": {"device": "fixture", "camera_profile_revision": None}}))
        recordings.append({"session": session, "video": str(video), "pitch_deg": 11.5})
    evaluation = tmp_path / "eval"
    evaluation.mkdir()
    (evaluation / "manifest.json").write_text(json.dumps({
        "purpose": "eval", "frames": [{"session": "heldout", "split": "eval"}]}))
    final = evaluation.with_name(content_sha(evaluation))
    evaluation.rename(final)
    gate = tmp_path / "gate.yaml"
    gate.write_text('require_eval: true\neval_set: ' + final.as_posix() + '\n')
    return {"store": str(tmp_path / "store"), "name": "recording-test",
            "recordings": recordings, "harvest": [],
            "label": {"min_interval": 1.0, "max_frames": 5, "lidar_yaw_deg": 180.0},
            "trainer": {"gate": str(gate), "replay_root": str(tmp_path),
                        "intake_out": str(tmp_path / "intake"), "camera_profile": "unused.json",
                        "training": {"seed": 1, "epochs": 1, "lr": 0.001,
                                     "batch_size": 1, "base": 8, "recipe": "enhanced"}}}


def fake_labels(argv, log):
    target = Path(argv[argv.index("--out") + 1])
    target.mkdir(parents=True)
    (target / "meta.json").write_text('{}')
    (target / "labels.jsonl").write_text('{}\n')
    return 0


def fake_build(dirs, store, name, **kwargs):
    folder = Path(store) / "datasets" / name / "candidate"
    folder.mkdir(parents=True)
    doc = {"frames": [{"session": "train-a", "split": "train"},
                      {"session": "train-b", "split": "val"}]}
    (folder / "manifest.json").write_text(json.dumps(doc))
    final = folder.with_name(content_sha(folder))
    folder.rename(final)
    return doc, final


def test_interrupted_label_retry_skips_completed_sources(tmp_path):
    cfg = config(tmp_path)
    calls = []

    def interrupted(argv, log):
        calls.append(argv)
        if len(calls) == 2:
            raise OSError("interrupted labelling")
        return fake_labels(argv, log)

    out = tmp_path / "job"
    with pytest.raises(OSError, match="interrupted"):
        prepare(cfg, out, runner=interrupted, builder=fake_build)
    result = prepare(cfg, out, runner=interrupted, builder=fake_build)
    assert len(calls) == 3
    assert result["dataset"].startswith("recording-test@")
    before = (out / "state.json").read_bytes()
    assert prepare(cfg, out, runner=interrupted, builder=fake_build) == result
    assert len(calls) == 3
    assert before == (out / "state.json").read_bytes()
    rows = [json.loads(row) for row in Path(result["catalog"]).read_text().splitlines()]
    assert {r["session"] for r in rows} == {"train-a", "train-b"}
    assert all(r["raw"] is None and r["driver"] is None for r in rows)
    assert all(r["derived"]["datasets"][0]["version"] in result["dataset"] for r in rows)


def test_raw_or_label_tamper_is_refused_before_build(tmp_path):
    cfg = config(tmp_path)
    out = tmp_path / "job"
    result = prepare(cfg, out, runner=fake_labels, builder=fake_build)
    Path(cfg["recordings"][0]["video"]).write_bytes(b"changed")
    with pytest.raises(JobError, match="changed"):
        prepare(cfg, out, runner=fake_labels, builder=fake_build)
    assert Path(result["catalog"]).exists()


def test_heldout_and_identity_mismatch_refused_before_labelling(tmp_path):
    cfg = config(tmp_path)
    cfg["recordings"][0]["session"] = "heldout"
    with pytest.raises(JobError, match="heldout"):
        prepare(cfg, tmp_path / "job", runner=lambda *_: pytest.fail("must not label"))
    cfg["recordings"][0]["session"] = "different"
    with pytest.raises(JobError, match="identity"):
        prepare(cfg, tmp_path / "job2", runner=lambda *_: pytest.fail("must not label"))


def test_harvest_never_allows_assume_idle_or_arbitrary_arguments(tmp_path):
    cfg = config(tmp_path)
    cfg["harvest"] = [{"host": "robot.local", "assume_idle": True}]
    with pytest.raises(JobError, match="harvest"):
        validate_config(cfg)
    cfg["harvest"] = [{"host": "robot.local", "core_token_file": "private/token",
                       "identity": "private/key", "known_hosts": "private/hosts",
                       "dest": "raw", "host_key_alias": "robot-id"}]
    validate_config(cfg)


def test_harvested_recording_reference_flows_into_autolabel_without_manual_raw_path(tmp_path):
    cfg = config(tmp_path)
    dest = tmp_path / "pi-harvest"
    cfg["recordings"][0] = {"session": "train-a", "harvest": 0}
    cfg["harvest"] = [{"host": "robot.local", "core_token_file": "private/token",
                       "identity": "private/key", "known_hosts": "private/hosts",
                       "dest": str(dest), "host_key_alias": "robot-id"}]
    raw = dest / "rosy-pinky-9dfk" / "train-a"
    label_inputs = []

    def runner(argv, log):
        if str(argv[0]).endswith("harvest.py"):
            (raw / "bag").mkdir(parents=True)
            (raw / "session.json").write_text(json.dumps({"ended_at": "2026-10-05T00:00:00Z"}))
            (raw / "bag" / "0.mcap").write_bytes(b"verified mcap fixture")
            return 0
        if argv[1] != "--video":
            label_inputs.append(Path(argv[1]))
        return fake_labels(argv, log)

    prepare(cfg, tmp_path / "job", runner=runner, builder=fake_build)

    assert label_inputs == [raw]


def test_harvested_recording_reference_requires_valid_harvest_index(tmp_path):
    cfg = config(tmp_path)
    cfg["recordings"][0] = {"session": "train-a", "harvest": 0}
    with pytest.raises(JobError, match="harvest index"):
        validate_config(cfg)


def test_harvested_recording_reference_rejects_non_list_harvest_config(tmp_path):
    cfg = config(tmp_path)
    cfg["recordings"][0] = {"session": "train-a", "harvest": 0}
    cfg["harvest"] = None
    with pytest.raises(JobError, match="harvest must be a list"):
        validate_config(cfg)


@pytest.mark.parametrize("devices", [[], ["rosy-pinky-9dfk", "rosy-pinky-8kcn"]])
def test_harvested_recording_reference_refuses_missing_or_ambiguous_session(tmp_path, devices):
    from recording_job import resolve_recordings

    cfg = config(tmp_path)
    dest = tmp_path / "pi-harvest"
    cfg["recordings"][0] = {"session": "train-a", "harvest": 0}
    cfg["harvest"] = [{"dest": str(dest)}]
    for device in devices:
        (dest / device / "train-a").mkdir(parents=True)
    with pytest.raises(JobError, match="expected one"):
        resolve_recordings(cfg)


def test_changed_pipeline_configuration_needs_new_job(tmp_path):
    cfg = config(tmp_path)
    out = tmp_path / "job"
    prepare(cfg, out, runner=fake_labels, builder=fake_build)
    cfg["label"]["max_frames"] += 1
    with pytest.raises(JobError, match="inputs changed"):
        prepare(cfg, out, runner=fake_labels, builder=fake_build)


def test_harvest_failure_stops_pipeline_and_resume_uses_positional_host(tmp_path):
    cfg = config(tmp_path)
    dest = tmp_path / "raw"
    dest.mkdir()
    (dest / "verified-source").write_bytes(b"downloaded source")
    cfg["harvest"] = [{"host": "robot.local", "core_token_file": "private/token",
                       "identity": "private/key", "known_hosts": "private/hosts",
                       "dest": str(dest), "host_key_alias": "robot-id"}]
    calls = []

    def worker(argv, log):
        calls.append(argv)
        if str(argv[0]).endswith("harvest.py"):
            assert argv[1] == "robot.local" and "--host" not in argv
            assert "--core-token-file" in argv and "--assume-idle" not in argv
            if len(calls) == 1:
                raise JobError("CORE not idle")
            return 0
        return fake_labels(argv, log)

    with pytest.raises(JobError, match="CORE not idle"):
        prepare(cfg, tmp_path / "job", runner=worker, builder=fake_build)
    assert len(calls) == 1
    prepare(cfg, tmp_path / "job", runner=worker, builder=fake_build)
    assert len(calls) == 4


def test_actual_video_labeller_and_store_builder_roundtrip(tmp_path):
    import cv2
    import numpy as np
    cfg = config(tmp_path)
    cfg["label"]["min_interval"] = 0.1
    cfg["label"]["max_frames"] = 20
    original = {}
    for record in cfg["recordings"]:
        video = Path(record["video"])
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
        assert writer.isOpened()
        rows = []
        for i in range(30):
            pixels = np.full((240, 320, 3), 80, dtype=np.uint8)
            cv2.line(pixels, (155, 240), (155, 115), (230, 230, 230), 5)
            writer.write(pixels)
            rows.append({"t": i / 10, "dt": {"odom": 0.0},
                         "side": {"odom": {"x": i / 20, "y": 0.0, "yaw": 0.0}}})
        writer.release()
        video.with_suffix(".jsonl").write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
        original[str(video)] = video.read_bytes()
    out = tmp_path / "actual-job"
    result = prepare(cfg, out)
    dataset = Path(cfg["store"]) / "datasets" / cfg["name"] / result["dataset"].split('@')[1]
    manifest = json.loads((dataset / "manifest.json").read_text())
    assert manifest["frames"]
    assert {f["split"] for f in manifest["frames"]} == {"train", "val"}
    assert all(f["session"] != "heldout" for f in manifest["frames"])
    assert content_sha(dataset) == dataset.name
    assert all(cv2.imread(str(dataset / f["mask"]), cv2.IMREAD_UNCHANGED).shape == (240, 320)
               for f in manifest["frames"])
    assert prepare(cfg, out) == result
    assert all(Path(p).read_bytes() == value for p, value in original.items())


def test_source_changed_during_labelling_cannot_reach_build(tmp_path):
    cfg = config(tmp_path)

    def mutate_source(argv, log):
        code = fake_labels(argv, log)
        Path(cfg["recordings"][0]["video"]).write_bytes(b"changed mid-run")
        return code

    with pytest.raises(JobError, match="changed"):
        prepare(cfg, tmp_path / "job", runner=mutate_source,
                builder=lambda *_a, **_k: pytest.fail("changed source must not be built"))


def test_parent_job_records_trainer_retry_and_ready(monkeypatch, tmp_path):
    import recording_job
    import train_job
    cfg = config(tmp_path)
    out = tmp_path / "job"
    prepared = prepare(cfg, out, runner=fake_labels, builder=fake_build)
    monkeypatch.setattr(recording_job, "prepare", lambda *_: prepared)
    calls = []

    def train(config, folder):
        calls.append(config)
        assert config["dataset"] == prepared["dataset"]
        if len(calls) == 1:
            raise JobError("GPU busy")
        return {"revision": "model-test", "location": "inbox/test"}

    monkeypatch.setattr(train_job, "run", train)
    with pytest.raises(JobError, match="GPU busy"):
        recording_job.run(cfg, out)
    recording_job.run(cfg, out)
    state = json.loads((out / "state.json").read_text())
    assert state["outcome"] == "ready"
    assert state["steps"]["model"]["attempts"] == 2
    recording_job.run(cfg, out)
    state = json.loads((out / "state.json").read_text())
    assert state["steps"]["model"]["attempts"] == 2
    assert len(calls) == 3  # child verifies current source/output on a cached parent resume


def test_child_quality_reject_is_terminal_in_parent(monkeypatch, tmp_path):
    import recording_job
    import train_job
    cfg = config(tmp_path)
    out = tmp_path / "job"
    prepared = prepare(cfg, out, runner=fake_labels, builder=fake_build)
    monkeypatch.setattr(recording_job, "prepare", lambda *_: prepared)
    calls = []

    def reject(*args):
        calls.append(args)
        raise Rejected("fixed evaluation below threshold")

    monkeypatch.setattr(train_job, "run", reject)
    with pytest.raises(Rejected):
        recording_job.run(cfg, out)
    assert json.loads((out / "state.json").read_text())["outcome"] == "rejected"
    with pytest.raises(Rejected):
        recording_job.run(cfg, out)
    assert len(calls) == 1
