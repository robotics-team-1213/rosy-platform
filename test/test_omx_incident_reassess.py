"""D-1040: the cell reads a free arm again without moving it and sends that read with the AI assessor's clear."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
import cell_arm_lease  # noqa: E402
import omx_incident as oi  # noqa: E402
import omx_incident_reassess as ra  # noqa: E402
from core_common.protocol.arm_incident.arm_incidents import ArmIncidentRemeasure  # noqa: E402

# arm_b's folded registers of 2026-11-17 (its 17:10 fault record): raw 2063 = 0.76 units, the plan home's 0.8
FOLDED = [2063, 773, 3134, 3104, 2972, 2002]
JPEG = b"\xff\xd8 a frame"
SERIALS = {"2B162C9B50323952582E3120FF06202D": "arm_a", "7F31D1FE50323952582E3120FF061D2D": "arm_b",
           "00FB51A150323952582E3120FF070726": "arm_s"}  # /etc/rosy/omx-arm-boards.json on the cell
LOST = {"fault_type": "SerialException",
        "fault": "device reports readiness to read but returned no data (device disconnected or multiple access on port?)"}


@pytest.fixture
def cell(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_OMX_HOME", str(tmp_path / "arm-home"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "boards.json").write_text(json.dumps(SERIALS))
    monkeypatch.setenv("ROSY_OMX_ARM_BOARDS", str(tmp_path / "boards.json"))
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    for serial in SERIALS:
        (by_id / f"usb-ROBOTIS_OpenRB-150_{serial}-if00").write_text("")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"home": [0.8, -62.2, 53.1, 51.6, 45.2]}))
    configs = {}
    for arm in ("arm_a", "arm_b", "arm_s"):
        configs[arm] = tmp_path / f"cell-{arm}.json"
        configs[arm].write_text(json.dumps({"arm_id": arm, "plan_path": str(plan)}))
    cal = tmp_path / "cal"
    cal.mkdir()
    for arm in ("arm_a", "arm_b", "arm_s"):
        (cal / f"{arm}_follower.json").write_text(json.dumps({"gripper": {"range_min": 950, "range_max": 2950}}))
    return {"configs": configs, "by_id": by_id, "leases": tmp_path / "leases", "read": [], "cal": cal}


def motors(positions=FOLDED, torque=0, error=0):
    return [{"id": 11 + i, "torque_enabled": torque, "hardware_error": error, "position_raw": p}
            for i, p in enumerate(positions)]


def tick():
    t = iter(range(1794910000, 1794910100, 6))  # each read 6 s after the last
    return lambda: float(next(t))


def run(cell, rows=None, fetch=lambda view: JPEG + view.encode(), arm="arm_b", config=None, device=None, held=True):
    clock = tick()

    def read(device):
        cell["read"].append(device)
        return motors() if rows is None else rows
    return ra.reassess(arm, config or cell["configs"][arm], device=device, fetch=fetch, read=read,
                       lease_root=cell["leases"], by_id=cell["by_id"], calibration_dir=cell["cal"],
                       now=clock, sleep=lambda s: None, gap=5.0, held=held)


def test_a_free_folded_quiet_arm_gives_a_whole_read_with_its_stills(cell):
    block = run(cell)
    assert ArmIncidentRemeasure.model_validate(block).folded is True and block["max_home_err"] < 0.1
    assert block["torque_after"] == block["hardware_error"] == {str(m): 0 for m in range(11, 17)}
    assert [f["role"] for f in block["frames"]] == ["top", "wrist"]
    assert block["at"] == 1794910006.0 and block["first_at"] == 1794910000.0
    assert block["gripper_pos"] == block["first_gripper_pos"] == 52.6
    assert (block["arm"], block["board_serial"]) == ("arm_b", "7F31D1FE50323952582E3120FF061D2D")
    port = str(cell["by_id"] / "usb-ROBOTIS_OpenRB-150_7F31D1FE50323952582E3120FF061D2D-if00")
    assert cell["read"] == [port, port]  # two reads under one lock
    assert block["stable"] is True and set(block["home_err"]) == set(oi.omx_incident_reassess.BODY)
    kept = sorted(p.name for p in (oi.incidents_dir() / "reassess").iterdir())
    assert len(kept) == 3 and json.loads(next(p for p in (oi.incidents_dir() / "reassess").glob("*.json"))
                                         .read_text())["frames"] == block["frames"]


@pytest.mark.parametrize(("arm", "top", "wrist"), [
    ("arm_a", "top", "arm_a_wrist"), ("arm_b", "top", "arm_b_wrist"), ("arm_s", "arm_s_top", "arm_s_wrist"),
])
def test_keeps_the_arms_top_and_wrist_bytes_and_hashes(cell, arm, top, wrist):
    block = run(cell, arm=arm)
    for frame, view in zip(block["frames"], (top, wrist), strict=True):
        data = JPEG + view.encode()
        kept = next((oi.incidents_dir() / "reassess").glob(f"*-{arm}-{frame['role']}.jpg"))
        assert kept.read_bytes() == data and hashlib.sha256(data).hexdigest() == frame["sha256"]


def test_legacy_clear_reassessment_keeps_its_side_still(cell):
    block = run(cell, held=False)
    assert [f["role"] for f in block["frames"]] == ["top", "side"]
    assert "gripper_pos" not in block


def test_what_the_read_saw_is_reported_as_it_was(cell):
    off_home = run(cell, motors([2063, 900, 3134, 3104, 2972, 2002]))  # shoulder_lift about 6 units up
    assert off_home["folded"] is False and off_home["max_home_err"] > 3
    on = run(cell, motors(torque=1, error=32))
    assert set(on["torque_after"].values()) == {1} and set(on["hardware_error"].values()) == {32}


def test_only_the_arms_own_board_and_plan_are_read(cell):
    with pytest.raises(SystemExit, match="is not this arm's follower"):
        run(cell, device=cell["by_id"] / "usb-ROBOTIS_OpenRB-150_2B162C9B50323952582E3120FF06202D-if00")
    with pytest.raises(SystemExit, match="config of 'arm_a'"):
        run(cell, config=cell["configs"]["arm_a"])
    assert run(cell, device=cell["by_id"] / "usb-ROBOTIS_OpenRB-150_7F31D1FE50323952582E3120FF061D2D-if00")["arm"]
    (cell["by_id"] / "usb-ROBOTIS_OpenRB-150_7F31D1FE50323952582E3120FF061D2D-if00").unlink()
    with pytest.raises(SystemExit, match="0 plugged in"):
        run(cell)
    Path("boards.json").write_text(json.dumps({**SERIALS, "1111111150323952582E3120FF000000": "arm_b"}))
    with pytest.raises(SystemExit, match="2 boards mapped"):
        run(cell)
    assert len(cell["read"]) == 2  # no refused case opened the port


def test_the_fault_records_the_arms_incidents_name_go_with_the_read(cell, tmp_path):
    record = tmp_path / "faults" / "arm_b_follower-20261117T081025-77a5f4.json"
    record.parent.mkdir()
    record.write_text(json.dumps({"session_id": "x", **LOST, "motors": []}))
    folder = tmp_path / "incidents" / "20261117T171027-arm_b"
    folder.mkdir(parents=True)
    (folder / "incident.json").write_text(json.dumps({"facts": {"fault_records": [str(record)]}}))
    other = tmp_path / "incidents" / "20261117T182025-arm_a"
    other.mkdir()
    (other / "incident.json").write_text(json.dumps({"facts": {"fault_records": [str(tmp_path / "a.json")]}}))
    block = run(cell)
    assert block["fault_records"] == [{"name": record.name, **LOST}]
    assert ArmIncidentRemeasure.model_validate(block).fault_records[0].fault_type == "SerialException"


def test_an_arm_someone_holds_or_an_incomplete_read_is_never_a_read(cell):
    with pytest.raises(SystemExit, match="incomplete|not a full read"):
        run(cell, motors()[:5])
    with pytest.raises(SystemExit, match="not a JPEG"):
        run(cell, fetch=lambda view: b"<html>")
    from joint_tune import session_lock
    lock = session_lock("arm_b")
    try:
        with pytest.raises(SystemExit, match="session"):
            run(cell)
    finally:
        lock.close()
    cell_arm_lease.claim("arm_b", owner="cell-app", purpose="calibrate", ttl_s=600, root=cell["leases"])
    cell["read"].clear()
    with pytest.raises(SystemExit, match="lease held by cell-app"):
        run(cell)
    assert cell["read"] == []  # the port was never opened


def test_clear_reassess_sends_the_read_with_the_assessors_token_and_a_plain_clear_is_unchanged(cell, monkeypatch):
    sent = []
    monkeypatch.setattr(oi, "clear", lambda *a, **k: sent.append((a, k)) or 0)
    monkeypatch.setattr(ra, "reassess", lambda arm, config, **k: {"read": arm, "device": k["device"]})
    monkeypatch.delenv("ROSY_ARM_ASSESSOR_TOKEN_FILE", raising=False)
    base = ["clear", "--arm", "arm_b", "--note", "fresh read quiet", "--cause", "software_or_config",
            "--basis", "measured"]
    where = ["--config", str(cell["configs"]["arm_b"])]
    with pytest.raises(SystemExit, match="token file"):
        oi.main(base + ["--reassess"] + where)
    with pytest.raises(SystemExit, match="--config"):
        oi.main(base + ["--reassess", "--token-file", "ai.token"])
    monkeypatch.setenv("ROSY_ARM_ASSESSOR_TOKEN_FILE", "ai.token")
    with pytest.raises(SystemExit, match="token file, --cause"):
        oi.main(base[:5] + ["--reassess"] + where)  # no cause: an assessor must name one
    assert oi.main(base + ["--reassess"] + where) == 0
    assert sent[-1] == (("arm_b", "fresh read quiet", Path("ai.token")),
                        {"cause": "software_or_config", "basis": "measured",
                         "remeasured": {"read": "arm_b", "device": None}})
    assert oi.main(base) == 0 and sent[-1] == (("arm_b", "fresh read quiet", None),
                                               {"cause": "software_or_config", "basis": "measured"})
    assert oi.main(["reassess", "--arm", "arm_b"] + where) == 0 and len(sent) == 2  # a read alone clears nothing


def test_the_link_carries_the_read_and_an_assessors_clear_never_drops_its_cause(monkeypatch):
    import omx_incident_fleet as fleet

    class Link:
        def __init__(self):
            self.calls = []

        def hold(self):
            return type("Hold", (), {"incident_ids": ["a" * 32], "held": True})()

        def clear(self, incident_id, note, token, **kw):
            self.calls.append(kw)
            error = OSError("422")
            error.code = 422
            raise error

    link = Link()
    with pytest.raises(OSError):
        fleet.clear_incidents("arm_b", "x", link=link, token="t", cause="other", basis="measured",
                              remeasured={"read": 1})
    # bound to the incident it clears, and no retry without the cause
    assert link.calls == [{"cause": "other", "basis": "measured", "remeasured": {"read": 1, "incident_id": "a" * 32}}]


def test_a_missing_follower_calibration_refuses_the_read(cell):
    (cell["cal"] / "arm_b_follower.json").unlink()
    with pytest.raises(SystemExit, match="no follower calibration"):
        run(cell)
    assert cell["read"] == []


def test_held_read_requires_a_calibrated_gripper(cell):
    (cell["cal"] / "arm_b_follower.json").write_text("{}")
    with pytest.raises(SystemExit, match="no valid gripper calibration"):
        run(cell)
    assert cell["read"] == []


def test_signed_per_joint_error_and_a_creeping_arm_is_not_stable(cell):
    sag = run(cell, motors([2063, 773, 3134, 3104 + 100, 2972, 2002]))  # wrist_flex raw +100 = +4.9 units over home
    assert sag["home_err"]["wrist_flex"] > 4 and sag["home_err"]["wrist_flex"] == sag["first_home_err"]["wrist_flex"]
    assert sag["stable"] is True and sag["folded"] is False
    rows = iter([motors(), motors([2063, 773, 3134, 3104 + 20, 2972, 2002])])  # +1.9 units between the reads
    block = ra.reassess("arm_b", cell["configs"]["arm_b"], fetch=lambda v: JPEG, read=lambda d: next(rows),
                        lease_root=cell["leases"], by_id=cell["by_id"], calibration_dir=cell["cal"], now=tick(),
                        sleep=lambda s: None)
    assert block["stable"] is False


def test_a_creeping_gripper_is_recorded_and_not_stable(cell):
    rows = iter([motors(), motors([*FOLDED[:5], 2022])])
    block = ra.reassess("arm_b", cell["configs"]["arm_b"], fetch=lambda v: JPEG, read=lambda d: next(rows),
                        lease_root=cell["leases"], by_id=cell["by_id"], calibration_dir=cell["cal"], now=tick(),
                        sleep=lambda s: None)
    assert block["first_gripper_pos"] == 52.6 and block["gripper_pos"] == 53.6
    assert block["stable"] is False


def test_pause_and_resume_observer_sole_holder_vs_foreign_holder(tmp_path):
    from types import SimpleNamespace

    port = tmp_path / "ttyACM0"
    port.write_text("", encoding="utf-8")
    calls, holders_seq = [], iter([{4242}, set(), {5151}])

    def run(*args):
        calls.append(args)
        if args[0] == "is-active":
            return SimpleNamespace(returncode=0, stdout="active\n", stderr="")
        if args[0] == "show":
            return SimpleNamespace(returncode=0, stdout="4242\n" if len(calls) <= 2 else "5151\n", stderr="")
        if args[0] == "is-enabled":
            return SimpleNamespace(returncode=0, stdout="enabled\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    cur = next(holders_seq)
    def poll(_d):
        nonlocal cur
        val = cur
        cur = next(holders_seq, set())
        return SimpleNamespace(returncode=0 if val else 1, stdout=" ".join(map(str, val)), stderr="")

    assert ra.pause_observer_if_sole_holder("arm_s", port, run=run, users=poll, scan=lambda _p: set(), sleep=lambda _s: None) is True
    assert ("stop", "rosy-omx-observer@arm_s.service") in calls
    # Foreign holder on port must NOT stop observer (fails closed).
    foreign_calls = []
    assert ra.pause_observer_if_sole_holder(
        "arm_s", port,
        run=lambda *a: foreign_calls.append(a) or SimpleNamespace(returncode=0, stdout="active\n" if a[0] == "is-active" else "4242\n", stderr=""),
        users=lambda _p: SimpleNamespace(returncode=0, stdout="4242 9999", stderr=""),
        scan=lambda _p: set(),
    ) is False
    assert all(c[0] != "stop" for c in foreign_calls)


def test_reassess_unlocks_before_resuming_paused_observer(cell, monkeypatch):
    import register_probe

    events = []
    class _Lock:
        def close(self):
            events.append("unlock")

    monkeypatch.setattr("joint_tune.session_lock", lambda _arm: _Lock())
    monkeypatch.setattr(ra, "pause_observer_if_sole_holder", lambda *_a, **_kw: events.append("pause") or True)
    monkeypatch.setattr(ra, "resume_observer", lambda *_a, **_kw: events.append("resume"))
    monkeypatch.setattr(register_probe, "collect", lambda _p: events.append("read") or motors())
    block = ra.reassess("arm_b", cell["configs"]["arm_b"], fetch=lambda _v: JPEG, lease_root=cell["leases"],
                        by_id=cell["by_id"], calibration_dir=cell["cal"], now=tick(), sleep=lambda _s: None)
    assert block["folded"] is True and events == ["pause", "read", "read", "unlock", "resume"]


def test_resume_observer_passes_by_id_symlink_to_restart(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import observer_handoff as oh

    target = tmp_path / "ttyACM0"
    target.write_text("", encoding="utf-8")
    link = tmp_path / "usb-ROBOTIS_OpenRB-150_TEST-if00"
    link.symlink_to(target)
    monkeypatch.setattr(oh, "BY_ID", tmp_path)
    seq = iter([set(), {6161}])
    seen = []

    def fake_restart(arm, **kw):
        seen.append((arm, kw["device"]))
        assert oh.resolve_device(kw["device"]) == str(target.resolve())
        return ("resumed", None)

    monkeypatch.setattr(oh, "restart", fake_restart)
    res = ra.resume_observer(
        "arm_s", link,
        run=lambda *a: SimpleNamespace(returncode=0, stdout="enabled\n" if a[0] == "is-enabled" else "6161\n", stderr=""),
        users=lambda _d: SimpleNamespace(returncode=1 if not (v := next(seq, {6161})) else 0, stdout=" ".join(map(str, v)), stderr=""),
        scan=lambda _d: set(),
        sleep=lambda _s: None,
    )
    assert res == ("resumed", None) and seen == [("arm_s", str(link))]
