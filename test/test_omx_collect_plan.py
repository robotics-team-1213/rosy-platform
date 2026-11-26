"""cell_collect_plan: a plan moves nothing, a model only reorders or vetoes accepted items, a failure stays labelled (2026-11-21)."""
import copy
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _stop_proof_passes(monkeypatch):
    """D-1077: these drive runs are about collection; the stop proof itself is tested in test_omx_stop_proof.py."""
    import cell_stop_proof
    monkeypatch.setattr(cell_stop_proof, "session_proof", lambda *a, **k: {"ok": True, "code": None, "reason": None})

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_collect_plan as cp  # noqa: E402
import cell_auto_safety  # noqa: E402

SHA = "a" * 64
PLAN = {
    "schema": cp.SCHEMA, "plan_id": "s-first", "arm": "arm_s", "proposer": "decision-ai", "approver": "kim",
    "values_from": "sim_optimized", "policy_real_approved": True,
    "cell": {"config": "cell-s.json", "catalog": "catalog-s.json", "library": "chunks-s.json",
             "cell_calibration": "~/cal/follower.json", "roi": [0, 0, 640, 480]},
    "items": [
        {"item_id": "ik1", "from": "belt", "to": "tray", "executor": "ik_chunk"},
        {"item_id": "pol1", "from": "belt", "to": "tray", "executor": "act", "policy": {"root": "~/models/m1", "revision": SHA}},
    ],
}


def plan(**change):
    out = copy.deepcopy(PLAN)
    for key, value in change.items():
        out[key] = value
    return out


def test_a_good_plan_has_no_problems_and_each_item_names_its_origin():
    assert cp.problems(PLAN) == []
    assert [cp.source_kind(PLAN, i) for i in PLAN["items"]] == ["sim_optimized", "policy"]
    assert cp.source_kind(plan(values_from="taught"), PLAN["items"][0]) == "scripted_teacher"


@pytest.mark.parametrize("change,word", [
    ({"approver": "Decision-AI"}, "differ from proposer"),
    ({"policy_real_approved": False}, "policy_real_approved"),
    ({"schema": "x"}, "schema"),
    ({"arm": "arm_z"}, "arm"),
    ({"items": []}, "items"),
])
def test_refusals(change, word):
    assert any(word in p for p in cp.problems(plan(**change)))


def test_unknown_site_and_bad_policy_are_refused_not_substituted():
    assert any("unknown site" in p for p in cp.problems(PLAN, sites={"belt"}))
    bad = copy.deepcopy(PLAN)
    bad["items"][1]["policy"]["revision"] = "short"
    assert any("sha256" in p for p in cp.problems(bad))


def test_jobs_are_dry_runs_the_queue_accepts(tmp_path):
    for name in ("cell-s.json", "catalog-s.json", "chunks-s.json"):
        (tmp_path / name).write_text("{}")
    out = cp.jobs(PLAN, workdir=tmp_path)
    assert [j["job"] for j in out] == ["auto_pick_dry_run", "cell_policy_drive"]
    assert out[1]["params"]["dry_run"] is True and out[1]["params"]["operator"] == "kim"
    assert out[1]["source_kind"] == "policy"
    with pytest.raises(ValueError, match="approver"):
        cp.jobs(plan(approver="decision-ai"), workdir=tmp_path)


def test_a_model_only_reorders_or_vetoes():
    items = PLAN["items"]
    assert cp.propose(lambda *a: {"choice": 1, "reason": "policy"}, items, "g")["order"] == [1, 0]
    assert cp.propose(lambda *a: {"choice": -1, "reason": "none"}, items, "g")["order"] == []
    assert cp.propose(lambda *a: {"choice": 9, "reason": "?"}, items, "g")["order"] == [0, 1]
    assert cp.propose(None, items, "g")["by"] == "rule"

    def down(*a):
        raise OSError("refused")

    out = cp.propose(down, items, "g")
    assert out["order"] == [0, 1] and "unavailable" in out["reason"]


def test_verdict_is_rule_first_and_a_model_can_only_downgrade():
    ok = {"result": "released", "took_one": True}
    assert cp.verdict(ok)["outcome"] == "success"
    assert cp.verdict(ok, lambda *a: {"ok": False, "reason": "tilted"}) == {"outcome": "unknown", "by": "model", "reason": "tilted"}
    assert cp.verdict(ok, lambda *a: {"ok": True, "reason": ""})["outcome"] == "success"
    assert cp.verdict({"result": "contact"}, lambda *a: {"ok": True, "reason": ""})["outcome"] == "failure"
    assert cp.verdict({"result": "released", "took_one": False})["outcome"] == "failure"
    assert cp.verdict({"result": "released", "took_one": True, "parked": False})["outcome"] == "failure"
    assert cp.verdict({"result": "released"})["outcome"] == "unknown"
    assert cp.verdict({"result": "chunks_done"})["outcome"] == "unknown"


def test_seal_stamps_origin_and_only_downgrades_the_result(tmp_path):
    (tmp_path / "result.json").write_text(json.dumps({"kept": True, "outcome": "success"}))
    cp.seal(tmp_path, {"outcome": "success", "by": "rule", "reason": "r"}, "policy")
    res = json.loads((tmp_path / "result.json").read_text())
    assert res["outcome"] == "success" and res["kept"] is True
    assert json.loads((tmp_path / "verdict.json").read_text())["source_kind"] == "policy"
    cp.seal(tmp_path, {"outcome": "unknown", "by": "model", "reason": "r"}, "policy")
    downgraded = json.loads((tmp_path / "result.json").read_text())
    assert downgraded["outcome"] == "unknown" and downgraded["kept"] is False

    # Failed result from close_episode propagates to unknown when verdict is unknown, never kept=True
    unk = tmp_path / "unk"
    unk.mkdir()
    (unk / "result.json").write_text(json.dumps({"kept": False, "outcome": "failed"}))
    cp.seal(unk, {"outcome": "unknown", "by": "rule", "reason": "no proof"}, "policy")
    unk_res = json.loads((unk / "result.json").read_text())
    assert unk_res["outcome"] == "unknown" and unk_res["kept"] is False

    # Existing "no frames" failure in result.json must not be overwritten on seal()
    no_frames = tmp_path / "no_frames"
    no_frames.mkdir()
    (no_frames / "result.json").write_text(json.dumps({"kept": False, "outcome": "no frames"}))
    cp.seal(no_frames, {"outcome": "failure", "by": "rule", "reason": "r"}, "policy")
    assert json.loads((no_frames / "result.json").read_text())["outcome"] == "no frames"


def test_yard_site_and_parity_guards(tmp_path):
    yard = copy.deepcopy(PLAN)
    yard["items"][1]["to"] = "yard:r3-s2-t1"
    assert cp.problems(yard) == []
    assert cp.jobs(yard)[1]["params"]["goal_site"] == "yard:r3-s2-t1"
    for name in ("cell-s.json", "catalog-s.json", "chunks-s.json"):
        (tmp_path / name).write_text("{}")
    assert cp.jobs(yard, workdir=tmp_path)[1]["params"]["goal_site"] == "yard:r3-s2-t1"

    bad_from = copy.deepcopy(PLAN)
    bad_from["items"][1]["from"] = "yard:r3-s2-t1"
    assert any("from must be a site name" in err for err in cp.problems(bad_from))
    bad_ik = copy.deepcopy(PLAN)
    bad_ik["items"][0]["to"] = "yard:r3-s2-t1"
    assert any("to must be a site name" in err for err in cp.problems(bad_ik))
    for bad_route in (bad_from, bad_ik):
        with pytest.raises(ValueError):
            cp.jobs(bad_route)

    unmapped = copy.deepcopy(PLAN)
    unmapped["items"][1]["to"] = "outbound"
    with pytest.raises(ValueError, match="goal slot"):
        cp.jobs(unmapped)

    bad_roi = plan()
    bad_roi["cell"]["roi"] = [0, 0, 1281, 10]
    assert any("cell.roi" in err for err in cp.problems(bad_roi))
    null_roi = copy.deepcopy(PLAN)
    null_roi["cell"]["roi"] = None
    assert any("cell.roi" in err for err in cp.problems(null_roi))
    with pytest.raises(ValueError, match="cell.roi"):
        cp.jobs(null_roi)
    bad_chunks = plan()
    bad_chunks["cell"]["max_chunks"] = 7
    assert any("max_chunks" in err for err in cp.problems(bad_chunks))
    null_chunks = copy.deepcopy(PLAN)
    null_chunks["cell"]["max_chunks"] = None
    assert any("max_chunks" in err for err in cp.problems(null_chunks))
    with pytest.raises(ValueError, match="max_chunks"):
        cp.jobs(null_chunks)
    bad_lib = plan()
    bad_lib["cell"]["library"] = "../secret.json"
    assert any("cell.library" in err for err in cp.problems(bad_lib))
    bad_cal = plan()
    bad_cal["cell"]["cell_calibration"] = "~/../cal.json"
    assert any("cell_calibration" in err for err in cp.problems(bad_cal))
    bad_root = copy.deepcopy(PLAN)
    bad_root["items"][1]["policy"]["root"] = "~/models/../secret"
    assert any("safe root" in err for err in cp.problems(bad_root))

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "deploy/robot/omx"))
    import omx_autoupdate_host

    assert "contracts/learning/src" in omx_autoupdate_host.DEFAULT_PATHS
    example = json.loads((root / "deploy/robot/omx/omx-devices-autoupdate.json.example").read_text(encoding="utf-8"))
    assert "contracts/learning/src" in example["paths"] and "contracts/learning/src" in example["smoke"]


def test_open_episode_stamps_the_source_kind(tmp_path):
    class Cell:
        def act(self, command):
            if command.startswith("episode start "):
                return {"ok": True, "command": command, "episode": command.split(" ", 2)[2]}
            return {"ok": True}

    config = {"episodes": {"root": str(tmp_path), "cameras": {}, "source_kind": "policy"}}
    cell_auto_safety.open_episode(Cell(), config, "belt", "tray", "policy-drive")
    task = json.loads(next(tmp_path.glob("*/task.json")).read_text())
    assert task["source_kind"] == "policy"


def test_jobs_include_roi_and_source_kind_and_reject_bad_roi(tmp_path):
    for name in ("cell-s.json", "catalog-s.json", "chunks-s.json"):
        (tmp_path / name).write_text("{}")
    out = cp.jobs(PLAN, workdir=tmp_path)
    p = out[1]["params"]
    assert p["roi"] == [0, 0, 640, 480] and p["source_kind"] == "policy"
    bad_roi = plan()
    bad_roi["cell"]["roi"] = [0, 0, 0, 10]
    assert any("cell.roi" in err for err in cp.problems(bad_roi))


@pytest.mark.parametrize("before,after,expected_took,expected_outcome,expected_kept", [
    (2, 1, True, "success", True),
    (2, 0, False, "failure", False),
    (1, 1, False, "failure", False),
])
def test_policy_drive_took_one_exact_drop_and_seal_integration(tmp_path, monkeypatch, before, after, expected_took, expected_outcome, expected_kept):
    import cell_auto_pick_plan
    import cell_pipeline
    import cell_policy_drive as drive
    import cell_policy_handoff

    cal = tmp_path / "cal.json"
    names = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
    cal.write_text(json.dumps({n: {"id": i, "drive_mode": 0, "homing_offset": 0, "range_min": 0, "range_max": 4095}
                               for i, n in enumerate(names)}))
    lib = tmp_path / "chunks-s.json"
    lib.write_text(json.dumps({"fps": 30, "gripper_closed": 46.6, "chunks": {"home": [[0] * 6] * 2}}))
    cat = tmp_path / "catalog-s.json"
    cat.write_text("{}")
    ep_root = tmp_path / "episodes"
    cfg = tmp_path / "cell-s.json"
    cfg.write_text(json.dumps({"arm_id": "arm_s", "io": str(tmp_path / "io"), "cameras": {},
                               "calibration_path": str(cal), "episodes": {"root": str(ep_root), "cameras": {}}}))

    class FakeCell:
        def act(self, command):
            if command.startswith("episode start "):
                return {"ok": True, "command": command, "episode": command.split(" ", 2)[2]}
            if command.startswith("episode save"):
                folder.joinpath("result.json").write_text(json.dumps({"kept": True, "outcome": "success"}))
            elif command.startswith("episode fail"):
                folder.joinpath("result.json").write_text(json.dumps({"kept": False, "outcome": "failed"}))
            return {"ok": True}

    folder = None
    real_open = cell_auto_safety.open_episode

    def fake_open(cell, config, source, dest, object_id):
        nonlocal folder
        ep = real_open(cell, config, source, dest, object_id)
        folder = ep.folder
        return ep

    counts = iter([before, after])
    monkeypatch.setattr(cell_auto_pick_plan, "observe", lambda *a, **kw: (None, None, [object()] * next(counts), None))
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *a: FakeCell())
    monkeypatch.setattr(cell_policy_handoff, "validate_taught_goal", lambda *a: None)
    monkeypatch.setattr(cell_auto_safety, "open_episode", fake_open)
    monkeypatch.setattr(cell_policy_handoff, "run_taught", lambda *a, **kw: {"result": "released"})

    rc = drive.main(["--config", str(cfg), "--library", str(lib), "--mode", "taught", "--goal-site", "tray",
                     "--operator", "op", "--person-at-switch", "--catalog", str(cat),
                     "--roi", "0", "0", "640", "480", "--site", "belt", "--source-kind", "sim_optimized"])
    assert rc == 0 and folder is not None
    verdict_doc = json.loads((folder / "verdict.json").read_text(encoding="utf-8"))
    result_doc = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    task_doc = json.loads((folder / "task.json").read_text(encoding="utf-8"))
    assert verdict_doc["outcome"] == expected_outcome and verdict_doc["source_kind"] == "sim_optimized"
    assert task_doc["source_kind"] == "sim_optimized"
    assert result_doc["kept"] is expected_kept


def test_policy_drive_closes_and_seals_episode_on_exception(tmp_path, monkeypatch):
    import cell_pipeline
    import cell_policy_drive as drive
    import cell_policy_handoff

    cal = tmp_path / "cal.json"
    names = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
    cal.write_text(json.dumps({n: {"id": i, "drive_mode": 0, "homing_offset": 0, "range_min": 0, "range_max": 4095}
                               for i, n in enumerate(names)}))
    lib = tmp_path / "chunks-s.json"
    lib.write_text(json.dumps({"fps": 30, "gripper_closed": 46.6, "chunks": {"home": [[0] * 6] * 2}}))
    ep_root = tmp_path / "episodes"
    cfg = tmp_path / "cell-s.json"
    cfg.write_text(json.dumps({"arm_id": "arm_s", "io": str(tmp_path / "io"), "cameras": {},
                               "calibration_path": str(cal), "episodes": {"root": str(ep_root), "cameras": {}}}))

    closed_calls = []

    class FakeCell:
        def act(self, command):
            if command.startswith("episode start "):
                return {"ok": True, "command": command, "episode": command.split(" ", 2)[2]}
            if command.startswith("episode fail"):
                closed_calls.append(command)
            return {"ok": True}

    folder = None
    real_open = cell_auto_safety.open_episode

    def fake_open(cell, config, source, dest, object_id):
        nonlocal folder
        ep = real_open(cell, config, source, dest, object_id)
        folder = ep.folder
        return ep

    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *a: FakeCell())
    monkeypatch.setattr(cell_policy_handoff, "validate_taught_goal", lambda *a: None)
    monkeypatch.setattr(cell_auto_safety, "open_episode", fake_open)

    def boom(*a, **kw):
        raise RuntimeError("runner crashed")

    monkeypatch.setattr(cell_policy_handoff, "run_taught", boom)
    with pytest.raises(RuntimeError, match="runner crashed"):
        drive.main(["--config", str(cfg), "--library", str(lib), "--mode", "taught", "--goal-site", "tray",
                    "--operator", "op", "--person-at-switch", "--source-kind", "scripted_teacher"])
    assert closed_calls and folder is not None
    assert json.loads((folder / "verdict.json").read_text(encoding="utf-8"))["outcome"] == "failure"


def test_open_episode_cleans_up_on_camera_startup_failure(tmp_path, monkeypatch):
    import cell_attempts
    import episode_recorder

    calls = []

    class FakeCell:
        def act(self, command):
            calls.append(command)
            if command.startswith("episode start "):
                return {"ok": True, "command": command, "episode": command.split(" ", 2)[2]}
            return {"ok": True}

    cell_attempts.RUN.update({"run_id": "r-partial", "n": 0, "episode": None})
    try:
        monkeypatch.setattr(episode_recorder, "CameraSession", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("cam init fail")))
        cfg = {"episodes": {"root": str(tmp_path), "cameras": {"top": "http://cam"}, "source_kind": "policy"}}
        with pytest.raises(RuntimeError, match="cam init fail"):
            cell_auto_safety.open_episode(FakeCell(), cfg, "belt", "tray", "policy-drive")
        assert len(calls) == 2 and calls[0].startswith("episode start ") and calls[1].startswith("episode fail ")
        assert cell_attempts.RUN["episode"] is None
    finally:
        cell_attempts.RUN.update({"run_id": None, "episode": None})


def test_policy_drive_handles_failed_close_ack_and_seal_failure_without_double_close(tmp_path, monkeypatch):
    import cell_auto_pick_plan
    import cell_pipeline
    import cell_policy_drive as drive
    import cell_policy_handoff

    cal = tmp_path / "cal.json"
    names = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
    cal.write_text(json.dumps({n: {"id": i, "drive_mode": 0, "homing_offset": 0, "range_min": 0, "range_max": 4095}
                               for i, n in enumerate(names)}))
    lib = tmp_path / "chunks-s.json"
    lib.write_text(json.dumps({"fps": 30, "gripper_closed": 46.6, "chunks": {"home": [[0] * 6] * 2}}))
    cat = tmp_path / "catalog-s.json"
    cat.write_text("{}")
    ep_root = tmp_path / "episodes"
    cfg = tmp_path / "cell-s.json"
    cfg.write_text(json.dumps({"arm_id": "arm_s", "io": str(tmp_path / "io"), "cameras": {},
                               "calibration_path": str(cal), "episodes": {"root": str(ep_root), "cameras": {}}}))

    sent = []

    class RefusingSaveCell:
        def act(self, command):
            sent.append(command)
            if command.startswith("episode start "):
                return {"ok": True, "command": command, "episode": command.split(" ", 2)[2]}
            if command == "episode save":
                return {"ok": False, "error": "busy"}
            return {"ok": True}

    folder = None
    real_open = cell_auto_safety.open_episode

    def fake_open(cell, config, source, dest, object_id):
        nonlocal folder
        ep = real_open(cell, config, source, dest, object_id)
        folder = ep.folder
        return ep

    counts = iter([2, 1])
    monkeypatch.setattr(cell_auto_pick_plan, "observe", lambda *a, **kw: (None, None, [object()] * next(counts), None))
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *a: RefusingSaveCell())
    monkeypatch.setattr(cell_policy_handoff, "validate_taught_goal", lambda *a: None)
    monkeypatch.setattr(cell_auto_safety, "open_episode", fake_open)
    monkeypatch.setattr(cell_policy_handoff, "run_taught", lambda *a, **kw: {"result": "released"})

    with pytest.raises(RuntimeError, match="episode close refused: busy"):
        drive.main(["--config", str(cfg), "--library", str(lib), "--mode", "taught", "--goal-site", "tray",
                    "--operator", "op", "--person-at-switch", "--catalog", str(cat),
                    "--roi", "0", "0", "640", "480", "--site", "belt", "--source-kind", "scripted_teacher"])
    assert any(c == "episode save" for c in sent) and any(c.startswith("episode fail ") for c in sent)
    assert json.loads((folder / "verdict.json").read_text(encoding="utf-8"))["outcome"] == "failure"

    close_calls = []

    class TrackingEpisode:
        def __init__(self, f):
            self.folder = f

        def finish(self):
            close_calls.append("finish")

    class OkCell:
        def act(self, command):
            close_calls.append(command)
            return {"ok": True}

    real_seal = cp.seal
    monkeypatch.setattr(cell_auto_pick_plan, "observe", lambda *a, **kw: (None, None, [object()], None))
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *a: OkCell())
    monkeypatch.setattr(cell_auto_safety, "open_episode", lambda *a: TrackingEpisode(tmp_path / "seal-fail"))
    monkeypatch.setattr(cp, "seal", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        drive.main(["--config", str(cfg), "--library", str(lib), "--mode", "taught", "--goal-site", "tray",
                    "--operator", "op", "--person-at-switch", "--catalog", str(cat),
                    "--roi", "0", "0", "640", "480", "--site", "belt", "--source-kind", "scripted_teacher"])
    assert close_calls.count("finish") == 1

    fifo_cmds = []
    finish_dir = tmp_path / "finish-fail"
    finish_dir.mkdir()

    class FailingFinishEpisode:
        def __init__(self, f):
            self.folder = f

        def finish(self):
            raise OSError("write failed")

    class CountingCell:
        def act(self, command):
            if command.startswith("episode "):
                fifo_cmds.append(command)
            return {"ok": True}

    monkeypatch.setattr(cp, "seal", real_seal)
    counts_ok = iter([2, 1])
    monkeypatch.setattr(cell_auto_pick_plan, "observe", lambda *a, **kw: (None, None, [object()] * next(counts_ok), None))
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *a: CountingCell())
    monkeypatch.setattr(cell_auto_safety, "open_episode", lambda *a: FailingFinishEpisode(finish_dir))
    with pytest.raises(OSError, match="write failed"):
        drive.main(["--config", str(cfg), "--library", str(lib), "--mode", "taught", "--goal-site", "tray",
                    "--operator", "op", "--person-at-switch", "--catalog", str(cat),
                    "--roi", "0", "0", "640", "480", "--site", "belt", "--source-kind", "scripted_teacher"])
    assert fifo_cmds == ["episode save"]
    assert json.loads((finish_dir / "verdict.json").read_text(encoding="utf-8"))["outcome"] == "failure"


def test_chunk_runner_allows_episode_close_while_human_hold_latched(tmp_path):
    import chunk_runner

    class DummyRobot:
        def __init__(self):
            self.pos = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]

        def send_action(self, action):
            pass

        def get_observation(self):
            return dict(zip(chunk_runner.NAMES, self.pos))

    lib = {"schema": chunk_runner.SCHEMA, "names": chunk_runner.NAMES, "gripper_closed": 46.6,
           "chunks": {"home": [[0.0, -60.0, 50.0, 45.0, 10.0, 46.6]] * 2}}
    status = []
    r = chunk_runner.Runner(DummyRobot(), lib, fps=30, status=status.append)
    r.target = list(lib["chunks"]["home"][0])
    ep = tmp_path / "ep0"
    ep.mkdir()
    (ep / "task.json").write_text(json.dumps({"task": "t", "cameras": {}}))
    r.command(f"episode start {ep}")
    assert r.recorder.active is True
    r.recorder.tick([0.0] * 6, [0.0] * 6)
    r.command("human-hold")
    r.tick()
    assert r.human_hold_latched is True
    other = tmp_path / "ep1"
    other.mkdir()
    (other / "task.json").write_text(json.dumps({"task": "t", "cameras": {}}))
    r.command(f"episode start {other}")
    assert status[-1]["ok"] is False and "human hold latched" in status[-1]["error"]
    r.command("episode fail policy refused")
    assert status[-1]["ok"] is True and r.recorder.active is False and r.human_hold_latched is True
    assert (ep / "ticks.jsonl").read_text(encoding="utf-8").strip()
    res = json.loads((ep / "result.json").read_text(encoding="utf-8"))
    assert res["outcome"] == "failed" and res["kept"] is False


def test_human_hold_ack_is_not_mistaken_for_episode_close_and_refused_open_aborts(tmp_path, monkeypatch, capsys):
    import cell_auto_pick_plan
    import cell_pipeline
    import cell_policy_drive as drive
    import cell_policy_handoff
    import chunk_runner

    class DummyRobot:
        def __init__(self):
            self.pos = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]

        def send_action(self, action):
            pass

        def get_observation(self):
            return dict(zip(chunk_runner.NAMES, self.pos))

    cal = tmp_path / "cal.json"
    names = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
    cal.write_text(json.dumps({n: {"id": i, "drive_mode": 0, "homing_offset": 0, "range_min": 0, "range_max": 4095}
                               for i, n in enumerate(names)}))
    lib_doc = {"schema": chunk_runner.SCHEMA, "names": chunk_runner.NAMES, "fps": 30, "gripper_closed": 46.6,
               "chunks": {"home": [[0.0, -60.0, 50.0, 45.0, 10.0, 46.6]] * 2}}
    lib = tmp_path / "chunks-s.json"
    lib.write_text(json.dumps(lib_doc))
    cat = tmp_path / "catalog-s.json"
    cat.write_text("{}")
    ep_root = tmp_path / "episodes"
    cfg = tmp_path / "cell-s.json"
    cfg.write_text(json.dumps({"arm_id": "arm_s", "io": str(tmp_path / "io"), "cameras": {},
                               "calibration_path": str(cal), "episodes": {"root": str(ep_root), "cameras": {}}}))

    status = []
    r = chunk_runner.Runner(DummyRobot(), lib_doc, fps=30, status=status.append)
    r.target = list(lib_doc["chunks"]["home"][0])
    sent = []

    class InterleavingCell:
        def act(self, command):
            sent.append(command)
            if command.startswith("episode start "):
                r.command(command)
                r.recorder.tick([0.0] * 6, [0.0] * 6)
                return status[-1]
            if command == "episode save":
                # Simulate same-batch human-hold preempting episode save so FifoCell sees human-hold row.
                r.command("human-hold")
                r.tick()
                return status[-1]
            r.command(command)
            return status[-1]

    counts = iter([2, 1])
    monkeypatch.setattr(cell_auto_pick_plan, "observe", lambda *a, **kw: (None, None, [object()] * next(counts), None))
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *a: InterleavingCell())
    monkeypatch.setattr(cell_policy_handoff, "validate_taught_goal", lambda *a: None)
    monkeypatch.setattr(cell_policy_handoff, "run_taught", lambda *a, **kw: {"result": "released"})

    with pytest.raises(RuntimeError, match="episode close refused"):
        drive.main(["--config", str(cfg), "--library", str(lib), "--mode", "taught", "--goal-site", "tray",
                    "--operator", "op", "--person-at-switch", "--catalog", str(cat),
                    "--roi", "0", "0", "640", "480", "--site", "belt", "--source-kind", "scripted_teacher"])
    assert any(c.startswith("episode fail ") for c in sent)
    assert r.recorder.active is False and r.human_hold_latched is True
    ep_dir = next(ep_root.iterdir())
    assert (ep_dir / "ticks.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads((ep_dir / "result.json").read_text(encoding="utf-8"))["outcome"] == "failed"
    assert json.loads((ep_dir / "verdict.json").read_text(encoding="utf-8"))["outcome"] == "failure"

    # Refused open_episode aborts before any motion when episodes is configured.
    called = []
    monkeypatch.setattr(cell_auto_pick_plan, "observe", lambda *a, **kw: (None, None, [object()], None))
    monkeypatch.setattr(cell_auto_safety, "open_episode", lambda *a: None)
    monkeypatch.setattr(cell_policy_handoff, "run_taught", lambda *a, **kw: called.append(True) or {"result": "released"})
    capsys.readouterr()
    rc = drive.main(["--config", str(cfg), "--library", str(lib), "--mode", "taught", "--goal-site", "tray",
                     "--operator", "op", "--person-at-switch", "--catalog", str(cat),
                     "--roi", "0", "0", "640", "480", "--site", "belt"])
    assert rc == 1 and not called and json.loads(capsys.readouterr().out)["result"] == "refused"

    # Conflicting mode vs source_kind overrides are refused before motion.
    with pytest.raises(SystemExit) as bad_cli:
        drive.main(["--config", str(cfg), "--library", str(lib), "--mode", "act", "--policy-root", str(tmp_path),
                    "--policy-revision", SHA, "--cell-calibration", str(cal), "--goal-site", "tray",
                    "--operator", "op", "--person-at-switch", "--source-kind", "scripted_teacher"])
    assert bad_cli.value.code == 2
    bad_cfg = tmp_path / "cell-bad-sk.json"
    bad_cfg.write_text(json.dumps({"arm_id": "arm_s", "io": str(tmp_path / "io"), "cameras": {},
                                   "calibration_path": str(cal),
                                   "episodes": {"root": str(ep_root), "cameras": {}, "source_kind": "scripted_teacher"}}))
    with pytest.raises(SystemExit) as bad_ep_cfg:
        drive.main(["--config", str(bad_cfg), "--library", str(lib), "--mode", "act", "--policy-root", str(tmp_path),
                    "--policy-revision", SHA, "--cell-calibration", str(cal), "--goal-site", "tray",
                    "--operator", "op", "--person-at-switch"])
    assert bad_ep_cfg.value.code == 2
    with pytest.raises(SystemExit) as bad_taught:
        drive.main(["--config", str(cfg), "--library", str(lib), "--mode", "taught", "--goal-site", "tray",
                    "--operator", "op", "--person-at-switch", "--source-kind", "policy"])
    assert bad_taught.value.code == 2


def test_episode_recorder_convert_handles_failure_label_and_provenance(tmp_path, monkeypatch):
    import types
    import episode_recorder as er
    import numpy as np

    saved_frames = []

    class FakeDS:
        def add_frame(self, f):
            saved_frames.append(f)

        def save_episode(self):
            pass

        def finalize(self):
            pass

    fake_cv2 = types.SimpleNamespace(
        IMREAD_COLOR=1, COLOR_BGR2RGB=1,
        imread=lambda p: np.zeros((4, 4, 3), dtype=np.uint8),
        cvtColor=lambda img, code: img,
    )
    fake_ld = types.SimpleNamespace(create=lambda *a, **kw: FakeDS())
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    monkeypatch.setitem(sys.modules, "lerobot", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "lerobot.datasets", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "lerobot.datasets.lerobot_dataset", types.SimpleNamespace(LeRobotDataset=fake_ld))

    eps = tmp_path / "eps"
    ep = eps / "ep0"
    (ep / "top").mkdir(parents=True)
    (ep / "task.json").write_text(json.dumps({"task": "t", "cameras": {"top": "u"}, "source_kind": "policy"}))
    (ep / "ticks.jsonl").write_text(json.dumps({"t": 1.0, "state": [0.0] * 6, "action": [0.0] * 6}) + "\n")
    (ep / "top.jsonl").write_text(json.dumps({"seq": 0, "t": 0.9}) + "\n")
    (ep / "top" / "000000.jpg").write_bytes(b"jpg")
    (ep / "result.json").write_text(json.dumps({"kept": False, "outcome": "failed", "frames": {"top": 1}}))

    out = tmp_path / "ds"
    out.mkdir()
    assert er.convert(eps, out, "local/fail", 30, {"top": "top"}, outcome="failure") == 1
    prov = json.loads((out / "rosy_provenance.json").read_text(encoding="utf-8"))
    assert prov == {"episodes": [{"episode": 0, "folder": "ep0", "source_kind": "policy"}]}

    (ep / "result.json").write_text(json.dumps({"kept": False, "outcome": "failed", "frames": {"top": 1}}))
    cp.seal(ep, {"outcome": "unknown", "by": "rule", "reason": "no proof"}, "policy")
    out_unk = tmp_path / "ds_unk"
    out_unk.mkdir()
    assert er.convert(eps, out_unk, "local/unk", 30, {"top": "top"}, outcome="unknown") == 1
    out_none = tmp_path / "ds_none"
    out_none.mkdir()
    assert er.convert(eps, out_none, "local/none", 30, {"top": "top"}, outcome="failure") == 0


def test_shared_contract_draft_and_8768_learning_center_http(tmp_path):
    import socket
    import threading
    import urllib.error
    import urllib.request

    root = Path(__file__).resolve().parents[1]
    for rel in ("contracts/learning/src", "learning/curation/perception", "learning/registry/perception", "learning/training/omx"):
        p = str(root / rel)
        if p not in sys.path:
            sys.path.insert(0, p)

    from rosy.contracts.learning import omx_collect_plan as contract
    from experiment_collect_plans import CollectPlans
    from review_app import ReviewStore, make_server

    draft = copy.deepcopy(PLAN)
    draft.pop("approver")
    draft["policy_real_approved"] = False
    assert contract.problems(draft, draft=True) == []
    assert contract.problems(plan(approver="alice", policy_real_approved=False), draft=True)
    assert contract.problems(plan(approver=None, policy_real_approved=False), draft=True)
    assert contract.problems(plan(approver="", policy_real_approved=False), draft=True)
    bad_id_plan = copy.deepcopy(draft)
    bad_id_plan["items"][0]["item_id"] = ["unhashable"]
    assert any("item_id" in err for err in contract.problems(bad_id_plan, draft=True))
    assert contract.problems(plan(policy_real_approved=1), draft=True)
    assert contract.problems(plan(policy_real_approved=True), draft=True)
    assert contract.problems(draft, draft=False)  # real cell execution refuses unapproved drafts

    lock = threading.RLock()
    plans = CollectPlans(tmp_path / "center", lock)
    alice_plan = copy.deepcopy(draft)
    alice_plan["plan_id"] = "s-alice"
    alice_rec = plans.create(alice_plan, principal={"user_id": "Alice.Kim"})
    assert alice_rec["proposer"] == "Alice.Kim" and "approver" not in alice_rec["plan"]

    fake_center = type("Center", (), {
        "bind_workspace": lambda self, proj: None,
        "profiles": type("P", (), {"list": lambda self: []})(),
        "snapshot": lambda self: {"datasets": [], "runs": [], "methods": {}},
        "collect_plans": plans,
    })()

    store = ReviewStore(tmp_path / "review", empty_training=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = make_server(store, port, omx_center=fake_center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/api/learning") as r:
            token = json.loads(r.read())["token"]

        def req(path, body=None, tok=None):
            data = None if body is None else json.dumps(body).encode("utf-8")
            hdrs = {"Content-Type": "application/json"}
            if tok:
                hdrs["X-Pinky-Token"] = tok
            r_obj = urllib.request.Request(base + path, data=data, headers=hdrs, method="POST" if data is not None else "GET")
            try:
                with urllib.request.urlopen(r_obj) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as err:
                return err.code, json.loads(err.read())

        assert req("/api/learning/omx/center/collect-plan", draft)[0] == 403  # CSRF token required
        bad_code, _ = req("/api/learning/omx/center/collect-plan", plan(policy_real_approved=True), token)
        assert bad_code == 400
        bad_app, _ = req("/api/learning/omx/center/collect-plan", plan(approver="kim", policy_real_approved=False), token)
        assert bad_app == 400
        mixed = copy.deepcopy(draft)
        mixed["proposer"] = "Alice.Kim"
        code, created = req("/api/learning/omx/center/collect-plan", mixed, token)
        assert code == 200 and created["ok"] is True and created["policy_real_approved"] is False
        assert "approver" not in created["plan"]
        assert created["approval_owner"] == "fleet_policy_approval_and_cell_gate"
        assert req("/api/learning/omx/center/collect-plan", mixed, token)[0] == 400  # immutable plan_id
        list_code, listing = req("/api/learning/omx/center/collect-plans")
        assert list_code == 200 and listing["configured"] is True
        assert {row["plan_id"] for row in listing["plans"]} == {draft["plan_id"], "s-alice"}
    finally:
        server.shutdown()
        server.server_close()


HOLD_ACK = {"command": "human-hold", "ok": True, "hold": True, "fault": "human hold", "human_hold_latched": True}


def _policy_drive_fixture(tmp_path):
    cal = tmp_path / "cal.json"
    names = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
    cal.write_text(json.dumps({n: {"id": i, "drive_mode": 0, "homing_offset": 0, "range_min": 0, "range_max": 4095}
                               for i, n in enumerate(names)}))
    lib = tmp_path / "chunks-s.json"
    lib.write_text(json.dumps({
        "fps": 30, "gripper_closed": 46.6,
        "chunks": {"home": [[0.2 * i, -60.0, 50.0, 45.0, 10.0, 46.6 + i] for i in range(16)]},
    }))
    cat = tmp_path / "catalog-s.json"
    cat.write_text("{}")
    ep_root = tmp_path / "episodes"
    cfg = tmp_path / "cell-s.json"
    cfg.write_text(json.dumps({"arm_id": "arm_s", "io": str(tmp_path / "io"), "cameras": {},
                               "calibration_path": str(cal), "episodes": {"root": str(ep_root), "cameras": {}}}))
    return cal, lib, cat, ep_root, cfg


def test_human_hold_masking_episode_start_cleans_up_and_aborts_before_motion(tmp_path, monkeypatch, capsys):
    import cell_auto_pick_plan
    import cell_pipeline
    import cell_policy_drive as drive
    import cell_policy_handoff
    import episode_recorder

    _cal, lib, cat, ep_root, cfg = _policy_drive_fixture(tmp_path)
    motion_called = []

    class HoldStartCell:
        def act(self, command):
            if command.startswith("episode start "):
                return dict(HOLD_ACK)
            motion_called.append(command)
            return {"ok": True}

    monkeypatch.setattr(cell_auto_pick_plan, "observe", lambda *a, **kw: (None, None, [object()], None))
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *a: HoldStartCell())
    monkeypatch.setattr(cell_policy_handoff, "validate_taught_goal", lambda *a: None)
    monkeypatch.setattr(cell_policy_handoff, "run_taught", lambda *a, **kw: motion_called.append("run_taught") or {})
    monkeypatch.setattr(episode_recorder, "CameraSession", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("CameraSession started")))

    capsys.readouterr()
    rc = drive.main(["--config", str(cfg), "--library", str(lib), "--mode", "taught", "--goal-site", "tray",
                     "--operator", "op", "--person-at-switch", "--catalog", str(cat),
                     "--roi", "0", "0", "640", "480", "--site", "belt"])
    assert rc == 1
    assert json.loads(capsys.readouterr().out)["result"] == "refused"
    assert not motion_called
    assert not ep_root.exists() or list(ep_root.iterdir()) == []


def test_human_hold_masking_park_marks_parked_false_and_fails_episode(tmp_path, monkeypatch):
    import types
    import cell_auto_pick_plan
    import cell_lerobot_shadow as lrs
    import cell_pipeline
    import cell_policy_drive as drive
    import cell_policy_handoff

    cal, lib, cat, ep_root, cfg = _policy_drive_fixture(tmp_path)
    pose = [0.0, -60.0, 50.0, 45.0, 10.0, 60.0]
    sent = []

    class HoldParkCell:
        def act(self, command):
            sent.append(command)
            if command.startswith("episode start "):
                return {"ok": True, "command": command, "episode": command.split(" ", 2)[2]}
            if command.endswith("park"):
                return dict(HOLD_ACK)
            if command == "run policy":
                return {"ok": True, "command": "run policy", "holding": True, "settled": True, "state": pose}
            if command.startswith("episode fail "):
                ep_dir = next(ep_root.iterdir())
                (ep_dir / "result.json").write_text(json.dumps({"kept": False, "outcome": "failed"}))
                return {"ok": True, "command": command, "kept": False, "outcome": "failed"}
            if command == "episode save":
                raise AssertionError("episode save must not run when park is preempted by human-hold")
            if command == "human-hold":
                return {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True, "state": pose}
            return {"ok": True, "state": pose, "target": pose}

        def frame(self, _view):
            import numpy as np
            return np.zeros((4, 4, 3), np.uint8)

    shadow = types.SimpleNamespace(
        sim_rule=None, goal_size=None, chunk_size=20, n_action_steps=4, image_views=(), files={}, arm_id=None,
        inputs=lambda *_a, **_kw: ({}, {}),
        infer=lambda _obs, **_kw: types.SimpleNamespace(chunk=[pose] * 20),
    )
    counts = iter([2, 1])
    monkeypatch.setattr(lrs, "LeRobotShadow", lambda *a, **kw: shadow)
    monkeypatch.setattr(drive, "demonstrated_range", lambda *_a: None)
    monkeypatch.setattr(cell_policy_handoff, "Authorization", lambda _cfg: None)
    monkeypatch.setattr(cell_auto_pick_plan, "observe", lambda *a, **kw: (None, None, [object()] * next(counts), None))
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *a: HoldParkCell())

    rc = drive.main(["--config", str(cfg), "--library", str(lib), "--mode", "act", "--policy-root", str(tmp_path),
                     "--policy-revision", SHA, "--model-calibration", str(cal), "--cell-calibration", str(cal),
                     "--max-chunks", "1", "--operator", "op", "--person-at-switch", "--catalog", str(cat),
                     "--roi", "0", "0", "640", "480", "--site", "belt"])
    assert rc == 1
    ep_dir = next(ep_root.iterdir())
    verdict_doc = json.loads((ep_dir / "verdict.json").read_text(encoding="utf-8"))
    result_doc = json.loads((ep_dir / "result.json").read_text(encoding="utf-8"))
    assert verdict_doc["outcome"] == "failure"
    assert result_doc["kept"] is False
    assert any(c.startswith("episode fail ") for c in sent) and "episode save" not in sent

    # Legacy ACT path (without chunk_size) also rejects HOLD-masked park.
    legacy_shadow = types.SimpleNamespace(
        sim_rule=None, arm_id=None, image_views=(),
        inputs=lambda *_a, **_kw: ({}, {}),
        infer=lambda _obs, **_kw: types.SimpleNamespace(chunk=[pose] * 4),
    )
    legacy_res = drive.run_episode(
        HoldParkCell(), legacy_shadow, lib, tmp_path, offset=[0.0] * 6, max_chunks=2, dry_run=False, log=lambda _: None
    )
    assert legacy_res["result"] == "released" and legacy_res["parked"] is False
    assert cp.verdict({**legacy_res, "took_one": True})["outcome"] == "failure"


def test_open_episode_allocates_unique_folder_per_attempt_with_fixed_clock(tmp_path, monkeypatch):
    import episode_recorder

    ep_root = tmp_path / "episodes"
    recorder = episode_recorder.Recorder()

    class RecorderCell:
        def act(self, command):
            try:
                return {"ok": True, "command": command, **recorder.command(command.split()[1:])}
            except ValueError as exc:
                return {"ok": False, "command": command, "error": str(exc)}

    cell = RecorderCell()
    monkeypatch.setattr(cell_auto_safety.time, "strftime", lambda *_a: "20261122-120000")
    cfg1 = {"episodes": {"root": str(ep_root), "cameras": {}, "source_kind": "policy"}}
    cfg2 = {"episodes": {"root": str(ep_root), "cameras": {}, "source_kind": "scripted_teacher"}}

    ep1 = cell_auto_safety.open_episode(cell, cfg1, "belt", "tray", "policy-drive")
    assert ep1 is not None and ep1.folder.name == "20261122-120000-belt-to-tray"
    orig_task = (ep1.folder / "task.json").read_text(encoding="utf-8")
    recorder.tick([0.0] * 6, [1.0] * 6)

    # While first episode is open, a same-second refused start neither overwrites task.json nor leaves an orphan folder.
    assert cell_auto_safety.open_episode(cell, cfg2, "belt", "tray", "policy-drive") is None
    assert sorted(p.name for p in ep_root.iterdir()) == ["20261122-120000-belt-to-tray"]
    assert (ep1.folder / "task.json").read_text(encoding="utf-8") == orig_task

    cell_auto_safety.close_episode(cell, ep1, True, "done")
    orig_ticks = (ep1.folder / "ticks.jsonl").read_text(encoding="utf-8")

    # After closing, a third same-second same-route attempt allocates a distinct suffix folder and never appends to ticks.jsonl.
    ep3 = cell_auto_safety.open_episode(cell, cfg2, "belt", "tray", "policy-drive")
    assert ep3 is not None and ep3.folder.name == "20261122-120000-belt-to-tray-01"
    recorder.tick([2.0] * 6, [3.0] * 6)
    cell_auto_safety.close_episode(cell, ep3, True, "done")
    assert (ep1.folder / "ticks.jsonl").read_text(encoding="utf-8") == orig_ticks
    assert json.loads((ep3.folder / "task.json").read_text(encoding="utf-8"))["source_kind"] == "scripted_teacher"


TIMEOUT_PARK = {"command": "run park", "ok": True, "settled": False, "fault": None, "state": [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]}


def test_runner_fault_refuses_episode_start_cleanly_and_blocks_save_under_hold(tmp_path):
    import chunk_runner

    class DummyRobot:
        def __init__(self):
            self.pos = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]

        def send_action(self, action):
            pass

        def get_observation(self):
            return dict(zip(chunk_runner.NAMES, self.pos))

    lib_doc = {"schema": chunk_runner.SCHEMA, "names": chunk_runner.NAMES, "gripper_closed": 46.6,
               "chunks": {"home": [[0.0, -60.0, 50.0, 45.0, 10.0, 46.6]] * 2}}
    status = []
    r = chunk_runner.Runner(DummyRobot(), lib_doc, fps=30, status=status.append)
    r.target = list(lib_doc["chunks"]["home"][0])

    class RunnerCell:
        def act(self, command):
            r.command(command)
            return status[-1]

    ep_root = tmp_path / "episodes"
    cfg = {"episodes": {"root": str(ep_root), "cameras": {}, "source_kind": "policy"}}
    cell = RunnerCell()
    r.fault = "following error"
    assert cell_auto_safety.open_episode(cell, cfg, "belt", "tray", "policy-drive") is None
    assert r.recorder.active is False
    assert not ep_root.exists() or list(ep_root.iterdir()) == []

    r.fault = None
    ep = cell_auto_safety.open_episode(cell, cfg, "belt", "tray", "policy-drive")
    assert ep is not None and r.recorder.active is True
    r.recorder.tick([0.0] * 6, [0.0] * 6)
    r.command("human-hold")
    r.tick()
    assert r.human_hold_latched is True
    r.command("episode save")
    assert status[-1]["ok"] is False and "human hold latched" in status[-1]["error"] and r.recorder.active is True
    r.command("episode fail latched")
    assert status[-1]["ok"] is True and r.recorder.active is False


def test_unsettled_act_park_rejects_verdict_and_exits_nonzero(tmp_path, monkeypatch):
    import types
    import cell_auto_pick_plan
    import cell_lerobot_shadow as lrs
    import cell_pipeline
    import cell_policy_drive as drive
    import cell_policy_handoff

    cal, lib, cat, ep_root, cfg = _policy_drive_fixture(tmp_path)
    pose = [0.0, -60.0, 50.0, 45.0, 10.0, 60.0]
    sent = []

    class TimeoutParkCell:
        def act(self, command):
            sent.append(command)
            if command.startswith("episode start "):
                return {"ok": True, "command": command, "episode": command.split(" ", 2)[2]}
            if command.endswith("park"):
                return dict(TIMEOUT_PARK)
            if command == "run policy":
                return {"ok": True, "command": "run policy", "holding": True, "settled": True, "state": pose}
            if command.startswith("episode fail "):
                ep_dir = next(ep_root.iterdir())
                (ep_dir / "result.json").write_text(json.dumps({"kept": False, "outcome": "failed"}))
                return {"ok": True, "command": command, "kept": False, "outcome": "failed"}
            if command == "episode save":
                raise AssertionError("episode save must not run when park is unsettled")
            if command == "human-hold":
                return {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True, "state": pose}
            return {"ok": True, "state": pose, "target": pose}

        def frame(self, _view):
            import numpy as np
            return np.zeros((4, 4, 3), np.uint8)

    shadow = types.SimpleNamespace(
        sim_rule=None, goal_size=None, chunk_size=20, n_action_steps=4, image_views=(), files={}, arm_id=None,
        inputs=lambda *_a, **_kw: ({}, {}),
        infer=lambda _obs, **_kw: types.SimpleNamespace(chunk=[pose] * 20),
    )
    counts = iter([2, 1])
    monkeypatch.setattr(lrs, "LeRobotShadow", lambda *a, **kw: shadow)
    monkeypatch.setattr(drive, "demonstrated_range", lambda *_a: None)
    monkeypatch.setattr(cell_policy_handoff, "Authorization", lambda _cfg: None)
    monkeypatch.setattr(cell_auto_pick_plan, "observe", lambda *a, **kw: (None, None, [object()] * next(counts), None))
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *a: TimeoutParkCell())

    rc = drive.main(["--config", str(cfg), "--library", str(lib), "--mode", "act", "--policy-root", str(tmp_path),
                     "--policy-revision", SHA, "--model-calibration", str(cal), "--cell-calibration", str(cal),
                     "--max-chunks", "1", "--operator", "op", "--person-at-switch", "--catalog", str(cat),
                     "--roi", "0", "0", "640", "480", "--site", "belt"])
    assert rc == 1
    ep_dir = next(ep_root.iterdir())
    assert json.loads((ep_dir / "verdict.json").read_text(encoding="utf-8"))["outcome"] == "failure"
    assert json.loads((ep_dir / "result.json").read_text(encoding="utf-8"))["kept"] is False
    assert "episode save" not in sent and any(c.startswith("episode fail ") for c in sent)

    legacy_shadow = types.SimpleNamespace(
        sim_rule=None, arm_id=None, image_views=(), inputs=lambda *_a, **_kw: ({}, {}),
        infer=lambda _obs, **_kw: types.SimpleNamespace(chunk=[pose] * 4),
    )
    legacy_res = drive.run_episode(
        TimeoutParkCell(), legacy_shadow, lib, tmp_path, offset=[0.0] * 6, max_chunks=2, dry_run=False, log=lambda _: None
    )
    assert legacy_res["result"] == "released" and legacy_res["parked"] is False


@pytest.mark.parametrize("bad_park", [HOLD_ACK, TIMEOUT_PARK])
def test_taught_and_hybrid_carries_reject_masked_or_unsettled_final_park(tmp_path, monkeypatch, bad_park):
    import cell_auto_pick_plan
    import cell_pipeline
    import cell_policy_drive as drive
    import cell_policy_handoff
    import cell_transfer

    cal, lib, cat, ep_root, cfg = _policy_drive_fixture(tmp_path)

    class CarryCell:
        def __init__(self):
            self.sent = []
            self.released = False

        def act(self, command):
            self.sent.append(command)
            if command.startswith("episode start "):
                return {"ok": True, "command": command, "episode": command.split(" ", 2)[2]}
            if command.startswith("episode fail "):
                ep_dir = next(ep_root.iterdir())
                (ep_dir / "result.json").write_text(json.dumps({"kept": False, "outcome": "failed"}))
                return {"ok": True, "command": command, "kept": False, "outcome": "failed"}
            if command == "episode save":
                raise AssertionError("episode save must not run when final park fails")
            if command == "run release_place":
                self.released = True
            if command == "park":
                if self.released:
                    return dict(bad_park)
                return {"ok": True, "command": "run park", "settled": True, "holding": True, "state": [0.0] * 5 + [52.6]}
            if command == "human-hold":
                return {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}
            if command in ("run grasp_pick", "run lift_pick", "goto above_place", "run descend_place"):
                return {"command": command, "ok": True, "holding": True, "settled": True, "state": [0.0] * 5 + [52.6]}
            return {"command": command, "ok": True, "holding": False, "settled": True, "state": [0.0] * 5 + [46.6]}

    taught_cell = CarryCell()
    counts = iter([2, 1])
    monkeypatch.setattr(cell_auto_pick_plan, "observe", lambda *a, **kw: (None, None, [object()] * next(counts), None))
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *a: taught_cell)
    monkeypatch.setattr(cell_policy_handoff, "Authorization", lambda _cfg: None)
    monkeypatch.setattr(cell_policy_handoff, "validate_taught_goal", lambda *a: None)

    rc = drive.main(["--config", str(cfg), "--library", str(lib), "--mode", "taught", "--goal-site", "tray",
                     "--operator", "op", "--person-at-switch", "--catalog", str(cat),
                     "--roi", "0", "0", "640", "480", "--site", "belt"])
    assert rc == 1
    ep_dir = next(ep_root.iterdir())
    assert json.loads((ep_dir / "verdict.json").read_text(encoding="utf-8"))["outcome"] == "failure"
    assert json.loads((ep_dir / "result.json").read_text(encoding="utf-8"))["kept"] is False
    assert "episode save" not in taught_cell.sent and any(c.startswith("episode fail ") for c in taught_cell.sent)

    hybrid_cell = CarryCell()
    hybrid_res = cell_policy_handoff._carry(
        hybrid_cell, lib, cell_transfer.FOLDED[-len(cell_transfer.RETURN_HELD) - 1:], None, lambda _: None
    )
    assert hybrid_res["result"] in ("fault", "refused") and hybrid_res["at"] == "park"
    assert cp.verdict({**hybrid_res, "took_one": True})["outcome"] == "failure"


def test_policy_drive_plain_run_skips_cell_collect_plan_import(tmp_path, monkeypatch):
    import cell_policy_drive as drive
    import cell_policy_handoff

    cal, lib, _cat, _ep_root, _cfg = _policy_drive_fixture(tmp_path)
    cfg = tmp_path / "cell-plain.json"
    cfg.write_text(json.dumps({"arm_id": "arm_s", "io": str(tmp_path / "io"), "cameras": {}, "calibration_path": str(cal)}))
    monkeypatch.setitem(sys.modules, "cell_collect_plan", None)
    monkeypatch.setattr(cell_policy_handoff, "validate_taught_goal", lambda *a: None)
    rc = drive.main(["--config", str(cfg), "--library", str(lib), "--mode", "taught", "--goal-site", "tray",
                     "--operator", "op", "--dry-run"])
    assert rc == 0


def test_episode_start_rolls_back_recorder_on_encoder_or_report_fault(tmp_path, monkeypatch):
    import chunk_runner

    class FlakyRobot:
        def __init__(self):
            self.pos = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
            self.fail_obs = False

        def send_action(self, action):
            pass

        def get_observation(self):
            if self.fail_obs:
                raise RuntimeError("bus timeout")
            return dict(zip(chunk_runner.NAMES, self.pos))

    lib_doc = {"schema": chunk_runner.SCHEMA, "names": chunk_runner.NAMES, "gripper_closed": 46.6,
               "chunks": {"home": [[0.0, -60.0, 50.0, 45.0, 10.0, 46.6]] * 2}}
    status = []
    fail_on_start = [False]
    robot = FlakyRobot()

    def sink(row):
        if fail_on_start[0] and str(row.get("command", "")).startswith("episode start "):
            raise OSError("disk full")
        status.append(row)

    r = chunk_runner.Runner(robot, lib_doc, fps=30, status=sink)
    r.target = list(lib_doc["chunks"]["home"][0])

    class RunnerCell:
        def act(self, command):
            r.command(command)
            return status[-1]

    ep_root = tmp_path / "episodes"
    cfg = {"episodes": {"root": str(ep_root), "cameras": {}, "source_kind": "policy"}}
    cell = RunnerCell()

    # 1. Encoder read failure while holding latches HOLD before opening the recorder.
    r.holding = True
    robot.fail_obs = True
    assert cell_auto_safety.open_episode(cell, cfg, "belt", "tray", "policy-drive") is None
    assert r.human_hold_latched is True and r.recorder.active is False
    assert not ep_root.exists() or list(ep_root.iterdir()) == []

    # 2. Absorbed status OSError while holding: report() returns normally after latching HOLD, then rollback drops recorder.
    robot.fail_obs = False
    r.human_hold_latched = False
    r.fault = None
    r.holding = True
    orig_report = r.report
    report_returned = []

    def tracked_report(*args, **kwargs):
        out = orig_report(*args, **kwargs)
        if str(kwargs.get("command", "")).startswith("episode start "):
            report_returned.append(True)
        return out

    monkeypatch.setattr(r, "report", tracked_report)
    fail_on_start[0] = True
    assert cell_auto_safety.open_episode(cell, cfg, "belt", "tray", "policy-drive") is None
    assert report_returned == [True] and r.human_hold_latched is True and r.recorder.active is False
    assert list(ep_root.iterdir()) == []

    # 3. Unabsorbed status OSError while idle rolls back via except BaseException and clears recorder.
    fail_on_start[0] = False
    r.human_hold_latched = False
    r.fault = None
    r.holding = False
    ep_ok = cell_auto_safety.open_episode(cell, cfg, "belt", "tray", "policy-drive")
    assert ep_ok is not None and r.recorder.active is True
    r.command("episode drop")
    assert r.recorder.active is False

    fail_on_start[0] = True
    assert cell_auto_safety.open_episode(cell, cfg, "belt", "tray", "policy-drive") is None
    assert r.human_hold_latched is True and r.recorder.active is False
    assert list(ep_root.iterdir()) == []

    # 4. FIFO status append succeeds then stdout fails: status file commits ack and recorder stays open.
    status_path = tmp_path / "chunk-status.jsonl"

    class BrokenStdout:
        def write(self, _text):
            raise OSError("broken stdout pipe")

        def flush(self):
            raise OSError("broken stdout pipe")

    r_out = chunk_runner.Runner(
        FlakyRobot(), lib_doc, fps=30,
        status=lambda row: chunk_runner.write_status_row(status_path, row, protect=False),
    )
    r_out.target = list(lib_doc["chunks"]["home"][0])

    class StatusFileCell:
        def act(self, command):
            r_out.command(command)
            return json.loads(status_path.read_text(encoding="utf-8").splitlines()[-1])

    monkeypatch.setattr(sys, "stdout", BrokenStdout())
    ep_stdout = cell_auto_safety.open_episode(StatusFileCell(), cfg, "belt", "tray", "policy-drive")
    assert ep_stdout is not None and r_out.recorder.active is True and r_out.human_hold_latched is False
    assert json.loads(status_path.read_text(encoding="utf-8").splitlines()[-1])["ok"] is True
    r_out.command("episode drop")


def test_convert_skips_camera_startup_failed_episode_and_exports_valid_failed_episode(tmp_path, monkeypatch):
    import types
    import episode_recorder

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")

    eps = tmp_path / "episodes"
    rec = episode_recorder.Recorder()

    class RecCell:
        def act(self, command):
            return {"ok": True, "command": command, **rec.command(command.split()[1:])}

    cell = RecCell()
    monkeypatch.setattr(episode_recorder, "CameraSession", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("cam init fail")))
    with pytest.raises(RuntimeError, match="cam init fail"):
        cell_auto_safety.open_episode(cell, {"episodes": {"root": str(eps), "cameras": {"top": "http://cam"}, "source_kind": "policy"}}, "belt", "tray", "policy-drive")
    bad_dir = next(eps.iterdir())
    assert json.loads((bad_dir / "result.json").read_text(encoding="utf-8"))["frames"] == {}

    unaligned_dir = eps / "20261122-120000-belt-to-tray"
    (unaligned_dir / "top").mkdir(parents=True)
    with (unaligned_dir / "top.jsonl").open("w", encoding="utf-8") as f:
        for seq in range(2):
            img = np.zeros((16, 16, 3), np.uint8)
            (unaligned_dir / "top" / f"{seq:06d}.jpg").write_bytes(cv2.imencode(".jpg", img)[1].tobytes())
            f.write(json.dumps({"seq": seq, "t": 200.0 + seq / 30}) + "\n")
    (unaligned_dir / "task.json").write_text(json.dumps({"task": "carry", "cameras": {"top": "u"}, "source_kind": "policy"}), encoding="utf-8")
    (unaligned_dir / "ticks.jsonl").write_text(
        "".join(json.dumps({"t": 100.0 + k / 30, "state": [0.0] * 6, "action": [0.1] * 6}) + "\n" for k in range(2)),
        encoding="utf-8",
    )
    (unaligned_dir / "result.json").write_text(json.dumps({"kept": False, "outcome": "failed", "frames": {"top": 2}}), encoding="utf-8")

    good_dir = eps / "20261122-120001-belt-to-tray"
    (good_dir / "top").mkdir(parents=True)
    with (good_dir / "top.jsonl").open("w", encoding="utf-8") as f:
        for seq in range(2):
            img = np.zeros((16, 16, 3), np.uint8)
            (good_dir / "top" / f"{seq:06d}.jpg").write_bytes(cv2.imencode(".jpg", img)[1].tobytes())
            f.write(json.dumps({"seq": seq, "t": 100.0 + seq / 30}) + "\n")
    (good_dir / "task.json").write_text(json.dumps({"task": "carry", "cameras": {"top": "u"}, "source_kind": "policy"}), encoding="utf-8")
    (good_dir / "ticks.jsonl").write_text(
        "".join(json.dumps({"t": 100.0 + k / 30 + 0.001, "state": [0.0] * 6, "action": [0.1] * 6}) + "\n" for k in range(2)),
        encoding="utf-8",
    )
    (good_dir / "result.json").write_text(json.dumps({"kept": False, "outcome": "failed", "frames": {"top": 2}}), encoding="utf-8")

    saved = []

    class FakeDataset:
        def __init__(self):
            self.buf = []

        @classmethod
        def create(cls, *_a, **_kw):
            return cls()

        def add_frame(self, frame):
            self.buf.append(frame)

        def save_episode(self):
            if not self.buf:
                raise ValueError("empty episode buffer")
            saved.append(len(self.buf))
            self.buf.clear()

        def finalize(self):
            pass

    monkeypatch.setitem(sys.modules, "lerobot", types.ModuleType("lerobot"))
    monkeypatch.setitem(sys.modules, "lerobot.datasets", types.ModuleType("lerobot.datasets"))
    lr_mod = types.ModuleType("lerobot.datasets.lerobot_dataset")
    lr_mod.LeRobotDataset = FakeDataset
    monkeypatch.setitem(sys.modules, "lerobot.datasets.lerobot_dataset", lr_mod)

    out_root = tmp_path / "ds"
    out_root.mkdir()
    count = episode_recorder.convert(eps, out_root, "local/fail-test", 30, {"top": "top"}, outcome="failed")
    assert count == 1 and saved == [2]
    prov = json.loads((out_root / "rosy_provenance.json").read_text(encoding="utf-8"))
    assert prov["episodes"] == [{"episode": 0, "folder": good_dir.name, "source_kind": "policy"}]
