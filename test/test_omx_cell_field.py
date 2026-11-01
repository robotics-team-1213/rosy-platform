"""cell_field: the field tool ranks clear pushes away from the neighbour, summarises a carry's attempt rows, and
shows a dark scene brightened side by side."""
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_field as cf  # noqa: E402


def test_clear_pushes_rank_away_from_the_neighbour_then_shorter():
    cands = [{"px": (1, 1), "dir": (-1, 0), "half_mm": 15, "mm": 15, "blocked": []},
             {"px": (1, 1), "dir": (1, 1), "half_mm": 15, "mm": 25, "blocked": []},
             {"px": (1, 1), "dir": (1, 1), "half_mm": 15, "mm": 15, "blocked": []},
             {"px": (1, 1), "dir": (1, 0), "half_mm": 15, "mm": 15, "blocked": [["behind", "off the surface"]]}]
    ranked = cf.rank_pushes(cands, (1, 1))
    assert [(c["dir"], c["mm"]) for c in ranked] == [((1, 1), 15), ((1, 1), 25), ((-1, 0), 15)]


def test_a_carry_summary_keeps_what_decided_it():
    row = {"attempt_id": "a1", "from": "floor", "to": "pinky", "outcome": "failed", "fail_class": "contact at run descend_place",
           "plan": {"pick": {"x": 0.1}}, "wrist": {"looks": [{"box_minus_tcp_mm": [9.4, 3.4]}, {"box_minus_tcp_mm": [2.5, 2.2]}]},
           "transfer": {"result": "contact", "at": "run descend_place", "steps": [
               {"command": "goto above_pick"}, {"command": "wrist", "verdict": "pass"},
               {"command": "run grasp_pick", "holding": True}, {"command": "run descend_place", "contact": True}]}}
    (s,) = cf.summarize([row])
    assert s["looks"] == [[9.4, 3.4], [2.5, 2.2]] and s["at"] == "run descend_place"
    assert [st["command"] for st in s["steps"]] == ["wrist", "run grasp_pick", "run descend_place"]


def test_a_dark_scene_is_brightened_side_by_side():
    dark = np.full((48, 64, 3), 30, np.uint8)
    pic = cf.side_by_side(dark, dark)
    assert pic.shape == (48, 128, 3) and pic[40, 30].mean() > 80  # 30 -> about 90 for a person to see


@pytest.fixture
def marking_cell(tmp_path, monkeypatch):
    from cell_envelope import digest
    import cell_pipeline_io as transport
    import cell_pivot
    import cell_robot_profile as profiles

    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"schema": profiles.SCHEMA, "device_id": "fixture-arm-a",
        "instance_id": "arm-a", "robot_config_sha256": "a" * 64,
        "operating_envelope_path": "review.json", "work_dir": "arm-a"}))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"io": str(tmp_path), "cameras": {}, "work_dir": str(tmp_path / "wrong"),
        "operating_profile_path": str(profile), "_operating_profile_binding": {"forged": True},
        "_commissioning": {"person_at_switch": True}}))
    library = tmp_path / "library.json"
    library.write_text("{}")
    field = cf.Field(config, tmp_path / "catalog.json")
    binding = profiles.load(profile)["binding"]
    state = {"ok": True, "t": time.time(), "library_sha256": "b" * 64, "state": [0] * 6,
        "operating_context": {"scope": "simulation", "session_id": "fixture-session", "sha256": "c" * 64,
                              "operating_profile": binding}}
    sent, queries, reject = [], [], []
    def write(fd, data):
        command = data.decode().strip()
        sent.append(command)
        raw = command.split(" ", 3)[-1] if command.startswith("checked ") else command
        accepted = not any(raw.startswith(r) for r in reject)
        if accepted:
            if raw.startswith("load "):
                state["library_sha256"] = digest(json.loads(Path(raw.split(" ", 1)[1]).read_text()))
            if raw.startswith("grip "):
                state["state"][5] = float(raw.split()[1])
        with (tmp_path / "chunk-status.jsonl").open("a") as stream:
            stream.write(json.dumps({"command": raw, "ok": accepted}) + "\n")
        return len(data)
    monkeypatch.setattr(transport, "os", SimpleNamespace(O_WRONLY=os.O_WRONLY, O_NONBLOCK=os.O_NONBLOCK,
        open=lambda path, flags: 123, write=write, close=lambda fd: None))
    actual_act = field.cell.act
    def act(command):
        if command == "state":
            queries.append(command)
            return state
        return actual_act(command)
    monkeypatch.setattr(field.cell, "act", act)
    monkeypatch.setattr(cell_pivot, "settled_frame", lambda *a, **kw: np.zeros((8, 8, 3), np.uint8))
    monkeypatch.setattr(cell_pivot, "jaw_blobs", lambda *a: [])
    return SimpleNamespace(field=field, binding=binding, state=state, sent=sent, queries=queries,
                           reject=reject, library=str(library), config=config)


def test_field_binds_the_selected_profile_and_its_evidence_directory(marking_cell):
    case = marking_cell
    assert case.field.cell.operating_profile == case.binding
    assert case.field.work == case.config.parent / "arm-a"


@pytest.mark.parametrize("commissioning,person", [(False, False), (True, False), (False, True)])
def test_marks_require_both_live_supervision_flags_before_even_cleanup(marking_cell, commissioning, person):
    case = marking_cell
    out = case.field.marks(case.library, "goto above_pick", commissioning=commissioning, person_at_switch=person)
    assert case.sent == [] and case.queries == []
    assert out["result"].startswith("held:")


def test_a_stored_binding_cannot_enable_unprofiled_marks(marking_cell):
    case = marking_cell
    config = json.loads(case.config.read_text())
    config.pop("operating_profile_path")
    case.config.write_text(json.dumps(config))
    field = cf.Field(case.config, Path("unused-catalog.json"))
    calls = []
    field.cell.act = lambda command: calls.append(command) or {"ok": False}
    out = field.marks(case.library, "goto above_pick", commissioning=True, person_at_switch=True)
    assert field.cell.operating_profile is None and calls == []
    assert out["result"].startswith("held:")


@pytest.mark.parametrize("wrong", ["profile", "stale"])
def test_marks_reject_wrong_or_stale_follower_before_motion_or_cleanup(marking_cell, wrong):
    case = marking_cell
    if wrong == "profile":
        case.state["operating_context"]["operating_profile"] = {**case.binding, "instance_id": "arm-b"}
    else:
        case.state["t"] -= 3600
    out = case.field.marks(case.library, "goto above_pick", commissioning=True, person_at_switch=True)
    assert case.sent == [] and case.queries
    assert out["result"].startswith("refused")


@pytest.mark.parametrize("failure", [None, "load ", "grip ", "frame"])
def test_supervised_marks_use_checked_commands_and_keep_park_recovery(marking_cell, monkeypatch, failure):
    from cell_envelope import digest
    import cell_pivot

    case = marking_cell
    if failure == "frame":
        def broken_frame(*a, **kw):
            raise RuntimeError("fixture frame failure")
        monkeypatch.setattr(cell_pivot, "settled_frame", broken_frame)
        with pytest.raises(RuntimeError, match="fixture frame failure"):
            case.field.marks(case.library, "goto above_pick", commissioning=True, person_at_switch=True)
    else:
        case.reject[:] = [failure] if failure else []
        out = case.field.marks(case.library, "goto above_pick", commissioning=True, person_at_switch=True)
        if failure:
            assert out["result"].startswith("refused")
    assert all(c.startswith("checked fixture-session ") for c in case.sent)
    revision = digest(json.loads(Path(case.library).read_text()))
    assert [c.split(" ")[2] for c in case.sent] == (
        [revision, "b" * 64] if failure == "load " else [revision] * len(case.sent))
    raw = [c.split(" ", 3)[-1] for c in case.sent]
    assert raw[-1] == "park"
    assert sum(c.startswith("grip ") for c in raw) == (0 if failure == "load " else 1 if failure else 6)


@pytest.mark.parametrize("flags", [[], ["--commissioning"], ["--person-at-switch"]])
def test_marks_cli_rejects_missing_supervision_before_constructing_field(monkeypatch, flags):
    def untouched(*a, **kw):
        pytest.fail("unsupervised CLI must not construct a field")
    monkeypatch.setattr(cf, "Field", untouched)
    with pytest.raises(SystemExit) as caught:
        cf.main(["--config", "unused.json", "--catalog", "unused.json", "marks", "--library", "unused.json", *flags])
    assert caught.value.code == 2


def test_marks_cli_passes_explicit_supervision_to_the_guarded_method(monkeypatch, capsys):
    calls = []
    def marks(library, goto, *, commissioning, person_at_switch):
        calls.append((library, goto, commissioning, person_at_switch))
        return {"result": "fixture"}
    monkeypatch.setattr(cf, "Field", lambda *a: SimpleNamespace(marks=marks))
    assert cf.main(["--config", "unused.json", "--catalog", "unused.json", "marks", "--library", "fixture.json",
                    "--commissioning", "--person-at-switch"]) == 0
    assert calls == [("fixture.json", "goto above_pick", True, True)]
    assert json.loads(capsys.readouterr().out) == {"result": "fixture"}


def test_a_field_push_is_held_without_a_person_at_the_switch_and_passes_the_flags_with_one(marking_cell):
    """2026-10-31: cell_push moves outside the D-911 gate, so it now refuses to move without the supervised flags."""
    field, runs = marking_cell.field, []
    field.run = lambda script, argv: runs.append((script, argv)) or (0, {"result": "pushed"}, "")
    field.push_search = lambda *a: [{"px": (1, 1), "dir": (0, 1), "mm": 15, "half_mm": 15, "blocked": []}]
    field.snapshot = lambda name: (None, None)
    assert field.push("floor", (1, 1), (0, 1), [0, 0, 9, 9])["result"].startswith("held:") and runs == []
    field.push("floor", (1, 1), (0, 1), [0, 0, 9, 9], person_at_switch=True)
    assert runs[-1][0] == "cell_push.py" and runs[-1][1][-2:] == ["--commissioning", "--person-at-switch"]
