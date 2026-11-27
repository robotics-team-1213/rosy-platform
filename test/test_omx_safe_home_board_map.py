"""2026-11-26: safe_home for arm_b resolved arm_a's OpenRB from its record config; a board the map gives another arm is
refused before any read or fold, and an unmapped or missing record port falls back to the arm's own mapped board."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_safe_home as csh  # noqa: E402
import cell_upkeep_checks as cuc  # noqa: E402

SERIALS = {"2B162C9B50323952582E3120FF06202D": "arm_a", "7F31D1FE50323952582E3120FF061D2D": "arm_b",
           "00FB51A150323952582E3120FF070726": "arm_s"}  # /etc/rosy/omx-arm-boards.json on the cell


@pytest.fixture
def cell(tmp_path, monkeypatch):
    (tmp_path / "boards.json").write_text(json.dumps(SERIALS))
    monkeypatch.setenv("ROSY_OMX_ARM_BOARDS", str(tmp_path / "boards.json"))
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    ports = {}
    for serial, arm in SERIALS.items():
        ports[arm] = by_id / f"usb-ROBOTIS_OpenRB-150_{serial}-if00"
        ports[arm].write_text("")
    monkeypatch.setattr(csh, "BY_ID", by_id)
    return tmp_path, ports


def args_for(tmp_path, port, device=None):
    record = tmp_path / "record-config.json"
    record.write_text(json.dumps({"robot": {"port": str(port)}} if port else {}))
    cfg = tmp_path / "cell-arm-b.json"
    cfg.write_text(json.dumps({"arm_id": "arm_b", "io": str(tmp_path / "io"), "record": {"config": str(record)}}))
    return SimpleNamespace(arm="arm_b", config=cfg, library=tmp_path / "lib.json", site="floor", roi=[0, 0, 10, 10],
                           out=tmp_path / "out.json", device=device, max_incidents=3, no_clear=False)


def run(args):
    read, folds = [], []
    rc, res = csh.run_safe_home(args, live_fn=lambda _c: False, run_fn=lambda *a, **k: folds.append(a),
                                read_fn=lambda d: read.append(d) or [{"id": 11, "hardware_error": 32}])
    return rc, res, read, folds


def test_a_b_config_naming_the_a_board_is_refused_before_any_read_or_fold(cell):
    tmp_path, ports = cell
    rc, res, read, folds = run(args_for(tmp_path, ports["arm_a"]))
    assert (rc, res["result"], res["device"]) == (2, "refused_device_arm_mismatch", str(ports["arm_a"]))
    assert read == [] and folds == []
    assert json.loads((tmp_path / "out.json").read_text())["result"] == "refused_device_arm_mismatch"


def test_an_explicit_device_of_another_arm_is_refused_too(cell):
    tmp_path, ports = cell
    rc, res, read, _ = run(args_for(tmp_path, ports["arm_b"], device=str(ports["arm_s"])))
    assert (rc, res["result"], read) == (2, "refused_device_arm_mismatch", [])


def test_a_b_config_naming_the_b_board_reads_that_board(cell):
    tmp_path, ports = cell
    rc, res, read, _ = run(args_for(tmp_path, ports["arm_b"]))
    assert read == [str(ports["arm_b"])] and res["result"] == "refused_hw_error"  # past the device check


@pytest.mark.parametrize("record_port", ["/dev/ttyACM9", None])
def test_an_unmapped_or_missing_record_port_falls_back_to_the_mapped_board(cell, record_port):
    tmp_path, ports = cell
    _, _, read, _ = run(args_for(tmp_path, record_port))
    assert read == [str(ports["arm_b"])]


def test_an_unreadable_board_map_is_refused(cell, monkeypatch):
    tmp_path, ports = cell
    monkeypatch.setenv("ROSY_OMX_ARM_BOARDS", str(tmp_path / "missing.json"))
    rc, res, read, _ = run(args_for(tmp_path, ports["arm_b"]))
    assert (rc, res["result"], read) == (2, "refused_board_map_unavailable", [])


def test_upkeep_never_reads_or_writes_another_arms_board(cell):
    _, ports = cell

    class Bus:
        def bus_read(self, device):
            raise AssertionError(f"read {device}")

    row = cuc.check_registers("arm_b", str(ports["arm_a"]), Bus(), True, Path("."), "s")
    assert row["status"] == "fail" and "arm_a's board" in row["detail"]
    assert cuc.check_pose("arm_b", str(ports["arm_a"]), Bus(), {"chunks": {"home": [[0] * 6]}})["status"] == "fail"


def test_safe_home_unlinks_stale_out_sets_session_chunks_and_refuses_held_lease(cell, monkeypatch):
    tmp_path, ports = cell
    args = args_for(tmp_path, ports["arm_b"])
    out_file = Path(args.out)
    stale = {"result": "held", "reason": "ALL_PATHS_BLOCKED"}

    # 1. Held lease refuses before probing hardware or launching wrapper
    out_file.write_text(json.dumps(stale))
    read_calls, run_calls = [], []
    rc, res = csh.run_safe_home(
        args, live_fn=lambda _c: False, lease_status_fn=lambda _a: {"arm_b": {"hold": "runner HOLD", "owner": "api", "pid": 99}},
        read_fn=lambda d: read_calls.append(d) or [], run_fn=lambda *a, **k: run_calls.append((a, k)) or SimpleNamespace(returncode=0),
    )
    assert (rc, res["result"], res["hold"]) == (2, "refused_lease_held", "runner HOLD")
    assert read_calls == [] and run_calls == [] and json.loads(out_file.read_text())["result"] == "refused_lease_held"

    # 2. Pre-start wrapper failure (exit 2 without writing out.json) never leaks stale ALL_PATHS_BLOCKED and propagates ROSY_SESSION_CHUNKS
    for live_mode in (False, True):
        out_file.write_text(json.dumps(stale))
        envs = []
        rc, res = csh.run_safe_home(
            args, live_fn=lambda _c, m=live_mode: m, lease_status_fn=lambda _a: {}, read_fn=lambda _d: [{"id": 11, "hardware_error": 0}],
            status_fn=lambda _a: {"incident_ids": []}, run_fn=lambda *a, **k: envs.append(k.get("env")) or SimpleNamespace(returncode=2),
        )
        assert rc == 2 and res["result"] != "held" and res.get("reason") != "ALL_PATHS_BLOCKED"
        assert json.loads(out_file.read_text())["result"] == res["result"]
        if not live_mode:
            assert envs[0]["ROSY_SESSION_CHUNKS"] == str(args.library.resolve())

    # 3. Paused observer is released if status_fn or wrapper fails before session start
    from contextlib import nullcontext
    released = []
    import register_probe as rp
    import omx_incident_reassess as oir
    monkeypatch.setattr(oir, "pause_observer_if_sole_holder", lambda _a, _d: True)
    monkeypatch.setattr(rp, "open_readonly_port", lambda _d: nullcontext())
    monkeypatch.setattr(rp, "read_motors", lambda *_a, **_k: [{"id": 11, "hardware_error": 0}])
    monkeypatch.setattr(csh, "_release_observer", lambda arm: released.append(arm))
    with pytest.raises(RuntimeError):
        csh.run_safe_home(args, live_fn=lambda _c: False, lease_status_fn=lambda _a: {},
                          status_fn=lambda _a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert released == ["arm_b"]


def test_safe_home_auto_reboots_rebootable_latch_and_refuses_unsafe_hw_errors(cell, tmp_path):
    _, ports = cell
    args = args_for(tmp_path, ports["arm_a"])
    args.arm = "arm_a"
    cfg = json.loads(Path(args.config).read_text())
    cfg["arm_id"] = "arm_a"
    Path(args.config).write_text(json.dumps(cfg))
    args.library.write_text("{}")

    def six_rows(faults=None, torque_on=()):
        faults = faults or {}
        return [
            {"id": i, "torque_enabled": 1 if i in torque_on else 0, "hardware_error": faults.get(i, 0)}
            for i in range(11, 17)
        ]

    # 1. Rebootable ID 12 overload (32) with all 6 motors torque=0 auto-reboots and proceeds to fold
    reboot_calls, fold_envs = [], []

    def ok_reboot(ids):
        reboot_calls.append(list(ids))
        after = {i: {"torque": 0, "hw_error": 0} for i in range(11, 17)}
        return {"rebooted": list(ids), "before": {}, "after": after}

    def fake_fold(cmd, env=None, timeout=None):
        fold_envs.append(env)
        Path(args.out).write_text(json.dumps({"result": "folded", "candidate": "park", "home": [0] * 6, "state": [0] * 6}))
        return SimpleNamespace(returncode=0)

    rc_ok, res_ok = csh.run_safe_home(
        args, live_fn=lambda _c: False, lease_status_fn=lambda _a: {},
        read_fn=lambda _d: six_rows({12: 32}),
        reboot_fn=ok_reboot,
        status_fn=lambda _a: {"incident_ids": []},
        run_fn=fake_fold,
    )
    assert rc_ok == 0 and reboot_calls == [[12]] and res_ok["rebooted_ids"] == [12] and len(fold_envs) == 1

    # 2. Non-rebootable hw_error=8 (encoder) OR torque_enabled=1 refuses before calling reboot_fn
    for bad_rows in (six_rows({12: 8}), six_rows({12: 32}, torque_on=(11,))):
        calls = []
        rc_bad, res_bad = csh.run_safe_home(
            args, live_fn=lambda _c: False, lease_status_fn=lambda _a: {},
            read_fn=lambda _d, r=bad_rows: r,
            reboot_fn=lambda ids: calls.append(ids),
        )
        assert rc_bad == 2 and res_bad["result"] == "refused_hw_error" and calls == [] and "reboot_attempt" not in res_bad

    # 3. Unclean post-reboot readback refuses and records reboot_attempt
    rc_dirty, res_dirty = csh.run_safe_home(
        args, live_fn=lambda _c: False, lease_status_fn=lambda _a: {},
        read_fn=lambda _d: six_rows({12: 32}),
        reboot_fn=lambda ids: {"rebooted": list(ids), "after": {i: {"torque": 0, "hw_error": 32 if i == 12 else 0} for i in range(11, 17)}},
    )
    assert rc_dirty == 2 and res_dirty["result"] == "refused_hw_error" and res_dirty["reboot_attempt"]["rebooted"] == [12]
