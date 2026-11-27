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

    # 3. Paused observer uses session_lock and releases lock before releasing observer on failure
    from contextlib import nullcontext
    events = []
    import joint_tune_lock as jtl
    import register_probe as rp
    import omx_incident_reassess as oir

    class _DummyLock:
        def close(self):
            events.append("lock_close")

    monkeypatch.setattr(jtl, "session_lock", lambda arm: events.append(f"lock_acquire:{arm}") or _DummyLock())
    monkeypatch.setattr(oir, "pause_observer_if_sole_holder", lambda _a, _d: events.append("pause_obs") or True)
    monkeypatch.setattr(rp, "open_readonly_port", lambda _d: nullcontext())
    monkeypatch.setattr(rp, "read_motors", lambda *_a, **_k: [{"id": 11, "hardware_error": 0}])
    monkeypatch.setattr(csh, "_release_observer", lambda arm: events.append(f"release_obs:{arm}"))
    with pytest.raises(RuntimeError):
        csh.run_safe_home(args, live_fn=lambda _c: False, lease_status_fn=lambda _a: {},
                          status_fn=lambda _a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert events == ["lock_acquire:arm_b", "pause_obs", "lock_close", "release_obs:arm_b"]

    events.clear()
    monkeypatch.setattr(rp, "read_motors", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("probe fail")))
    rc_pf, res_pf = csh.run_safe_home(args, live_fn=lambda _c: False, lease_status_fn=lambda _a: {})
    assert rc_pf == 2 and res_pf["result"] == "refused_hw_probe_unavailable"
    assert events == ["lock_acquire:arm_b", "pause_obs", "lock_close", "release_obs:arm_b"]


def test_safe_home_auto_reboots_rebootable_latch_and_refuses_unsafe_hw_errors(cell, tmp_path, monkeypatch):
    _, ports = cell
    args = args_for(tmp_path, ports["arm_a"])
    args.arm = "arm_a"
    cfg = json.loads(Path(args.config).read_text())
    cfg["arm_id"] = "arm_a"
    Path(args.config).write_text(json.dumps(cfg))
    args.library.write_text("{}")

    def six_rows(faults=None, torque_on=(), temp=35):
        faults = faults or {}
        return [
            {"id": i, "torque_enabled": 1 if i in torque_on else 0, "hardware_error": faults.get(i, 0),
             **({} if temp is None else {"temperature": temp})}
            for i in range(11, 17)
        ]

    # 1. Rebootable ID 12 overload (32) with all 6 motors torque=0 and temp<45C auto-reboots and proceeds to fold
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

    # 2. Non-rebootable hw_error=8, torque_enabled=1, hot temp>=45C, missing/bool temp refuse before calling reboot_fn
    for bad_rows in (
        six_rows({12: 8}),
        six_rows({12: 32}, torque_on=(11,)),
        six_rows({12: 32}, temp=45),
        six_rows({12: 32}, temp=None),
        six_rows({12: 32}, temp=True),
    ):
        calls = []
        rc_bad, res_bad = csh.run_safe_home(
            args, live_fn=lambda _c: False, lease_status_fn=lambda _a: {},
            read_fn=lambda _d, r=bad_rows: r,
            reboot_fn=lambda ids: calls.append(ids),
        )
        assert rc_bad == 2 and res_bad["result"] == "refused_hw_error" and calls == [] and "reboot_attempt" not in res_bad

    # 3. Unclean post-reboot readback (hw_error!=0 or bool torque=False) refuses and records reboot_attempt
    for bad_after in (
        {i: {"torque": 0, "hw_error": 32 if i == 12 else 0} for i in range(11, 17)},
        {i: {"torque": False if i == 11 else 0, "hw_error": 0} for i in range(11, 17)},
    ):
        rc_dirty, res_dirty = csh.run_safe_home(
            args, live_fn=lambda _c: False, lease_status_fn=lambda _a: {},
            read_fn=lambda _d: six_rows({12: 32}),
            reboot_fn=lambda ids, a=bad_after: {"rebooted": list(ids), "after": a},
        )
        assert rc_dirty == 2 and res_dirty["result"] == "refused_hw_error" and res_dirty["reboot_attempt"]["rebooted"] == [12]

    # 4. Refused Fleet clear returns non-zero (rc=4) with clear_failed=True while preserving folded result
    monkeypatch.chdir(tmp_path)
    tok = tmp_path / "tok"
    tok.write_text("tok")
    rc_cf, res_cf = csh.run_safe_home(
        args, live_fn=lambda _c: False, lease_status_fn=lambda _a: {},
        read_fn=lambda _d: six_rows(),
        status_fn=lambda _a: {"incident_ids": ["inc-latched"]},
        run_fn=fake_fold,
        wait_sess_fn=lambda *_a: ({"torque_after": {str(i): 0 for i in range(11, 17)}, "hardware_faults": {}, "caps_restored": True}, None),
        token_fn=lambda: tok,
        clear_fn=lambda *_a, **_kw: (_ for _ in ()).throw(SystemExit("clear refused: latched")),
    )
    assert rc_cf == 4 and res_cf["result"] == "folded" and res_cf["clear_failed"] is True
    assert "inc-latched" in res_cf["clear_errors"]

    # 5. Live probe (read_fn=None) + reboot keeps session_lock across reboot_fn before closing lock
    from contextlib import nullcontext
    import joint_tune_lock as jtl
    import omx_incident_reassess as oir
    import register_probe as rp

    seq = []

    class _SeqLock:
        def close(self):
            seq.append("lock_close")

    monkeypatch.setattr(jtl, "session_lock", lambda arm: seq.append(f"lock_acquire:{arm}") or _SeqLock())
    monkeypatch.setattr(oir, "pause_observer_if_sole_holder", lambda _a, _d: seq.append("pause_obs") or True)
    monkeypatch.setattr(rp, "open_readonly_port", lambda _d: nullcontext())
    monkeypatch.setattr(rp, "read_motors", lambda *_a, **_k: six_rows({12: 32}))
    monkeypatch.setattr(csh, "_release_observer", lambda arm: seq.append(f"release_obs:{arm}"))

    def locked_reboot(ids):
        seq.append(f"reboot:{ids}")
        return {"rebooted": list(ids), "after": {i: {"torque": 0, "hw_error": 0} for i in range(11, 17)}}

    rc_lk, res_lk = csh.run_safe_home(
        args, live_fn=lambda _c: False, lease_status_fn=lambda _a: {},
        reboot_fn=locked_reboot, status_fn=lambda _a: {"incident_ids": []}, run_fn=fake_fold,
    )
    assert rc_lk == 0 and res_lk["rebooted_ids"] == [12]
    assert seq == ["lock_acquire:arm_a", "pause_obs", "reboot:[12]", "lock_close"]
