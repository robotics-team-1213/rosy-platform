import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_bound_home_placement as placement


def status(holding):
    return {"ok": True, "holding": holding, "state": [0.] * 5 + [50. if holding else 60.],
            "human_hold_latched": False, "t": time.time(),
            "operating_context": {"session_id": "session", "sha256": "1" * 64, "scope": "hardware"},
            "target": [0.] * 5 + [42. if holding else 60.]}


@pytest.mark.parametrize(("holding", "pending", "age", "cargo", "after", "reason"), [
    (False, False, 61, None, False, None),
    (False, True, 61, None, False, "PLACEMENT_VERIFICATION_PENDING"),
    (False, False, 61, {"task": 1}, False, "PLACEMENT_UNVERIFIED"),
    (None, False, 61, {}, False, "PLACEMENT_REQUIRED_BEFORE_HOME"),
    (True, False, 61, None, False, "PLACEMENT_CARGO_CONTEXT_UNKNOWN"),
    (True, False, 59, {"task": 1}, False, "PLACEMENT_IDLE_INTERVAL_PENDING"),
    (True, False, 61, {"task": 1}, False, "placed"),
    (True, False, 61, {"task": 1}, True, "POST_PLACEMENT_EMPTY_UNCONFIRMED"),
])
def test_bound_placement_before_home(tmp_path, monkeypatch, holding, pending, age, cargo, after, reason):
    args = SimpleNamespace(arm="arm_s", stage="full", expected_incident_id="a" * 32, config=tmp_path / "cell.json",
                           safety_fence="fence", expires_at=101., stop_generation=0)
    args.config.write_text("{}")
    monkeypatch.setattr(placement.time, "time", lambda: 100.)
    replies = iter([status(holding), status(after)])
    calls = []
    journal = SimpleNamespace(pending=lambda: pending, confirmed=lambda _: False)
    cell = SimpleNamespace(act=lambda command: next(replies) if command == "state" else pytest.fail(command))

    def build_backend(a, fenced, kw, current):
        assert a is args and fenced is cell and current["holding"] is True and kw["placement_context"] == cargo
        return object()

    def place_nearest(backend, **kw):
        calls.append(kw)
        return {"result": "placed", "target": "slot"}

    got = placement.before_bound_home(args, cell, 42., {}, journal, tmp_path, build_backend=build_backend,
                                      load_context=lambda *_: {"stopped_at": 100. - age, "cargo": cargo},
                                      place_nearest=place_nearest)
    assert (got.get("reason", got["result"]) if got else None) == reason
    moved = reason in ("placed", "POST_PLACEMENT_EMPTY_UNCONFIRMED")
    assert calls == ([{"holding": True, "incident_id": args.expected_incident_id, "journal": journal}] if moved else [])


@pytest.mark.parametrize("remains_held", [False, True])
@pytest.mark.parametrize("commissioning", [False, True])
def test_bound_cli_checks_fresh_empty_before_guarded_home(tmp_path, monkeypatch, remains_held, commissioning):
    import cell_auto_fold
    import cell_auto_fold_stages as stages
    import cell_recovery_placement
    import cell_recovery_placement_context as context
    import cell_recovery_placement_live as live
    import chunk_runner_recover
    import omx_incident
    import omx_incident_fleet

    incident = "a" * 32
    config = tmp_path / "cell.json"
    config.write_text("{}")
    monkeypatch.setenv("ROSY_RECOVERY_INCIDENT", incident)
    monkeypatch.setattr(omx_incident, "link_for", lambda arm: object())
    monkeypatch.setattr(stages, "bound_hold_matches", lambda link, key: key == incident)
    monkeypatch.setattr(omx_incident_fleet, "incidents_dir", lambda: tmp_path)
    monkeypatch.setattr(context, "load_context", lambda *a: {"stopped_at": 1., "cargo": {"type": "cube"}})
    def build_backend(args, cell, kw, status):
        assert kw["placement_commissioning"] is commissioning
        return cell
    monkeypatch.setattr(live, "build_backend", build_backend)
    holding = [True]
    events = []

    def place(cell, **kwargs):
        assert isinstance(cell, stages.FencedCell) and kwargs["incident_id"] == incident
        events.append("placed")
        holding[0] = remains_held
        return {"result": "placed", "target": "slot"}

    def session(args, guarded, schema):
        def act(command):
            assert command in ("state", "human-hold")
            if command == "human-hold":
                events.append(command)
            return status(holding[0])

        moved = []
        result = guarded(SimpleNamespace(act=act), [0.] * 6, 42., moved_out=moved)
        assert moved and result["result"] == ("held" if remains_held else "folded")
        assert result["placement"]["target"] == "slot"
        return 0

    def fold(cell, home, closed, **kw):
        assert kw["require_empty_gripper"] and not holding[0]
        events.append("fold")
        return {"result": "folded"}

    monkeypatch.setattr(cell_recovery_placement, "place_nearest", place)
    monkeypatch.setattr(chunk_runner_recover, "run_fold_session_cli", session)
    monkeypatch.setattr(cell_auto_fold, "recover", fold)
    fence = tmp_path / "fence.json"
    fence.write_text(json.dumps({"updated_at": time.time(), "human_hold": False, "stop_generation": 0}))
    args = ["--arm", "arm_s", "--config", str(config), "--library", str(tmp_path / "lib"),
            "--site", "site", "--roi", "0", "0", "2", "2", "--out", str(tmp_path / "out"),
            "--expected-incident-id", incident, "--expires-at", str(time.time() + 60),
            "--safety-fence", str(fence), "--stop-generation", "0"]
    if commissioning:
        args.extend(["--commissioning", "--person-at-switch"])
    assert cell_auto_fold.main(args) == 0
    assert events == ["placed", "human-hold" if remains_held else "fold"]


@pytest.mark.parametrize("extra", [["--commissioning"], ["--person-at-switch"],
                                   ["--commissioning", "--person-at-switch", "--supervised"]])
def test_unbound_or_unattended_placement_trial_is_refused(tmp_path, extra):
    import cell_auto_fold
    args = ["--arm", "arm_s", "--config", "cell", "--library", "library", "--site", "site",
            "--roi", "0", "0", "2", "2", "--out", str(tmp_path / "out")]
    with pytest.raises(SystemExit) as raised:
        cell_auto_fold.main(args + extra)
    assert raised.value.code == 2
