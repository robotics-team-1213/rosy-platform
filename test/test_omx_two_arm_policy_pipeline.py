"""End-to-end pipeline, guard concurrency, D-911/D-1024 safety gates, and remote shadow tests (D-1073)."""
from __future__ import annotations

import ast
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import threading
import time
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

ROOT = Path(__file__).resolve().parents[1]
OMX = ROOT / "deploy/robot/omx"
ADAPTER = ROOT / "middleware/devices/omx/adapter"
LEARN_OMX = ROOT / "learning/training/omx"

_ADDED = [str(OMX), str(ADAPTER), str(LEARN_OMX)]
for _p in _ADDED:
    sys.path.insert(0, _p)
try:
    import act_policy_http_server as http_srv  # noqa: E402
    import cell_remote_policy as remote_mod  # noqa: E402
    import cell_two_arm_guard as guard_mod  # noqa: E402
    import cell_two_arm_policy as pol_mod  # noqa: E402
    import cell_two_arm_policy_cli as cli_mod  # noqa: E402
finally:
    for _p in _ADDED:
        if _p in sys.path:
            sys.path.remove(_p)


REAL_ARM_STATE_GATE = cli_mod._arm_state_gate


@pytest.fixture(autouse=True)
def _no_start_gate_in_older_cli_tests(monkeypatch):
    """The CLI tests below predate the start gate and carry no checkpoint folders; the gate's own tests restore the real function."""
    monkeypatch.setattr(cli_mod, "_arm_state_gate", lambda *_a: None)


class PlanarKin:
    """Deterministic 3D link_points stub exercised through REAL swept_volume + coordination."""

    def __init__(self, base_z: float = 0.08):
        self.base_z = base_z

    def link_points(self, joints_rad, fingertip_m=0.074):
        pan = float(joints_rad[0])
        lift = float(joints_rad[1])
        reach = 0.14
        x1 = reach * 0.6 * np.cos(pan)
        y1 = reach * 0.6 * np.sin(pan)
        z1 = self.base_z + 0.04
        x2 = reach * np.cos(pan) + float(fingertip_m) * 0.5 * np.cos(pan)
        y2 = reach * np.sin(pan) + float(fingertip_m) * 0.5 * np.sin(pan)
        z2 = max(-0.08, self.base_z + 0.04 - 0.12 * max(0.0, lift))
        p_base = (0.0, 0.0, self.base_z)
        p_mid = (float(x1), float(y1), float(z1))
        p_tip = (float(x2), float(y2), float(z2))
        points = [p_base, p_mid, p_mid, p_tip, p_tip, p_tip]
        return points, (0.0, 0.0, -1.0)


class FakeCell:
    def __init__(self, pose, *, fault=None, delay_s=0.0, fail_load=False, fail_run=False, hold_on_done=False):
        self.pose = list(pose)
        self.fault = fault
        self.delay_s = delay_s
        self.fail_load = fail_load
        self.fail_run = fail_run
        self.hold_on_done = hold_on_done
        self.commands: list[str] = []
        self._seq = 0
        self.lock = threading.Lock()
        self.on_run = None

    def act(self, cmd: str):
        with self.lock:
            self.commands.append(cmd)
        if cmd == "state":
            return {
                "ok": self.fault is None,
                "fault": self.fault,
                "state": list(self.pose),
                "holding": False,
                "t": time.time(),
            }
        if cmd == "human-hold":
            return {"ok": True, "command": "human-hold", "human_hold_latched": True, "torque_hold_commanded": True, "state": list(self.pose)}
        if " load " in cmd:
            if self.fail_load:
                return {"ok": False, "error": "load_rejected"}
            return {"ok": True}
        if cmd.endswith(" run policy"):
            if self.on_run is not None:
                self.on_run()
            if self.delay_s:
                time.sleep(self.delay_s)
            if self.fault:
                return {"ok": False, "fault": self.fault, "settled": False, "state": list(self.pose)}
            if self.fail_run:
                return {"ok": False, "error": "runner_refused", "settled": False, "state": list(self.pose)}
            return {"ok": True, "settled": True, "holding": self.hold_on_done, "state": list(self.pose)}
        return {"ok": True, "settled": True, "state": list(self.pose)}

    def checked(self, cmd: str, auth):
        return self.act(f"checked {auth['session_id']} {auth['library_sha256']} {cmd}")

    def frame_receipt(self, view: str, previous=None, *, max_age_s=2.0, timeout_s=10.0):
        self._seq += 1
        img = np.zeros((24, 32, 3), dtype=np.uint8)
        return {"camera": view, "image": img, "source_seq": self._seq, "source_stamp": time.time()}


def test_camera_reads_share_state_and_oldest_frame_budget(monkeypatch):
    t = 10.0
    calls = []
    monkeypatch.setattr(pol_mod, "time", SimpleNamespace(monotonic=lambda: t, time=lambda: t + 100.0))

    def frame(role, *, previous, max_age_s, timeout_s):
        nonlocal t
        calls.append((max_age_s, timeout_s))
        t += 0.1
        return {"image": role, "source_stamp": 109.75 if role == "top" else t + 100.0}

    views = dict.fromkeys(("top", "side", "wrist"))
    images, observed = pol_mod._capture_frames(
        SimpleNamespace(frame_receipt=frame), views, dry_run=False, max_age_s=0.6,
        state_mono=9.9, prev_receipts={},
    )
    assert images == {role: role for role in views}
    assert observed == pytest.approx(9.75)
    assert [call[0] for call in calls] == [0.6] * 3
    assert [call[1] for call in calls] == pytest.approx([0.5, 0.25, 0.15])


@pytest.mark.parametrize(("elapsed", "expected_calls"), [(0.6, ["top"]), (0.0, [])])
def test_camera_expiry_stops_capture_before_inference(monkeypatch, elapsed, expected_calls):
    t = 10.0
    calls = []
    monkeypatch.setattr(pol_mod, "time", SimpleNamespace(monotonic=lambda: t, time=lambda: t + 100.0))

    def frame(role, *, previous, max_age_s, timeout_s):
        nonlocal t
        calls.append(role)
        t += elapsed
        return {"image": role, "source_stamp": t + 100.0}

    views = dict.fromkeys(("top", "side", "wrist"))
    state_mono = 10.0 if elapsed else 9.0
    with pytest.raises(ValueError, match="stale policy observation .* camera top"):
        pol_mod._capture_frames(
            SimpleNamespace(frame_receipt=frame), views, dry_run=False, max_age_s=0.6,
            state_mono=state_mono, prev_receipts={},
        )
    assert calls == expected_calls


def _base_lib(home=(0.0, -40.0, 40.0, 40.0, 0.0, 50.0)):
    h = list(home)
    return {
        "schema": "rosy.omx-chunk-library.v1",
        "fps": 30,
        "gripper_closed": 47.0,
        "tcp_x_m": 0.074,
        "chunks": {
            "home": [h, h],
            "reach": [
                h,
                [h[0] - 8.0, -20.0, 30.0, 35.0, -5.0, 60.0],
                [h[0] + 8.0, -45.0, 45.0, 45.0, 5.0, 47.0],
            ],
        },
        "max_speed_units_per_s": 120.0,
    }


def _make_remote_server(tmp_path: Path, predict_map: dict, *, delay_map: dict | None = None, goal_size: int | None = None, sim_rule: dict | None = None):
    specs = []
    revs = {}
    for arm_id in ("arm_a", "arm_b"):
        pdir = tmp_path / arm_id
        pdir.mkdir(parents=True, exist_ok=True)
        raw = f"weights-{arm_id}".encode("utf-8")
        (pdir / "model.safetensors").write_bytes(raw)
        rev = sha256(raw).hexdigest()
        revs[arm_id] = rev
        if sim_rule is not None:
            (pdir / "UNITS.json").write_text(
                json.dumps({"state": "sim_rad", "gripper": "sim_jaw", "arm": arm_id}),
                encoding="utf-8",
            )
        in_feat = {
            "observation.state": {"shape": [6]},
            "observation.images.top": {"shape": [3, 24, 32]},
            "observation.images.wrist": {"shape": [3, 24, 32]},
        }
        if goal_size is not None:
            in_feat["observation.environment_state"] = {"shape": [goal_size]}
        (pdir / "config.json").write_text(
            json.dumps({
                "type": "act",
                "n_action_steps": 4,
                "chunk_size": 8,
                "input_features": in_feat,
                "output_features": {"action": {"shape": [6]}},
            }),
            encoding="utf-8",
        )
        specs.append(f"{arm_id}={pdir}:{rev}")

    def loader(pdir, *_a):
        arm_id = pdir.name

        def predict(obs):
            if delay_map and arm_id in delay_map and delay_map[arm_id] > 0:
                time.sleep(delay_map[arm_id])
            return predict_map[arm_id](obs)

        return predict

    reg = http_srv.PolicyRegistry.from_specs(specs, loader=loader)
    server = http_srv.make_server("127.0.0.1", 0, reg)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", revs


def test_deploy_modules_have_no_torch_lerobot_or_lab_ips():
    lab_ip = re.compile(r"\b(?:100\.82\.|192\.168\.1\.20[12]|192\.168\.50\.)")
    for name in ("cell_remote_policy.py", "cell_two_arm_guard.py", "cell_two_arm_policy.py", "cell_two_arm_policy_cli.py"):
        src = (OMX / name).read_text(encoding="utf-8")
        assert not lab_ip.search(src), name
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] not in ("torch", "lerobot"), name
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in ("torch", "lerobot"), name


def test_remote_policy_shadow_loopback_sim_conversion_and_timeout(tmp_path):
    srv_obj, url, revs = _make_remote_server(
        tmp_path,
        {
            "arm_a": lambda obs: [[0.0, -0.5, 0.4, 0.5, 0.0, 0.6]] * 4,
            "arm_b": lambda obs: [[0.0, -0.5, 0.4, 0.5, 0.0, 0.6]] * 4,
        },
        delay_map={"arm_b": 0.4},
    )
    try:
        with pytest.raises(ValueError, match="bearer token required"):
            remote_mod.RemotePolicyShadow("http://ai-pc.local:8765", "arm_a", revs["arm_a"])
        with pytest.raises(ValueError, match="timeout_s"):
            remote_mod.RemotePolicyShadow(url, "arm_a", revs["arm_a"], timeout_s=3.0)
        with pytest.raises(remote_mod.RemotePolicyError, match="revision"):
            remote_mod.RemotePolicyShadow(url, "arm_a", "0" * 64)

        sim_rule = {"held_30mm": 53.4, "gap_mm_per_unit": 5.0}
        sh_a = remote_mod.RemotePolicyShadow(url, "arm_a", revs["arm_a"], timeout_s=0.5, sim_rule=sim_rule)
        img = np.zeros((24, 32, 3), dtype=np.uint8)
        obs, meta = sh_a.inputs([0.0, -40.0, 40.0, 40.0, 0.0, 53.4], {"top": img, "wrist": img})
        assert meta["frame_count"] == 2 and set(meta["model_frame_sha256"]) == {"top", "wrist"}
        assert meta["sim_converted"] is True and abs(obs["state"][0]) < 0.01
        res = sh_a.infer(obs)
        assert len(res.chunk) == 4 and len(res.chunk[0]) == 6 and res.policy_revision == revs["arm_a"]
        assert abs(res.chunk[0][0]) < 0.2 and res.rtt_s >= 0.0

        sh_b_short = remote_mod.RemotePolicyShadow(url, "arm_b", revs["arm_b"], timeout_s=0.1)
        obs_b, _ = sh_b_short.inputs([0.0] * 6, {"top": img, "wrist": img})
        with pytest.raises(remote_mod.RemotePolicyError, match="failed"):
            sh_b_short.infer(obs_b)
        with pytest.raises(ValueError, match="finite"):
            sh_a.inputs([True, 0.0, 0.0, 0.0, 0.0, 50.0], {"top": img, "wrist": img})
    finally:
        srv_obj.shutdown()
        srv_obj.server_close()


def test_validate_two_arm_task_pair_canonical_classification_and_refusals():
    t1 = guard_mod.validate_two_arm_task_pair(
        {"src": "not_places:belt", "dst": "temp_a:r1-s1-t1"},
        {"src": "temp_b:r1-s1-t1", "dst": "temp_b:r2-s1-t1"},
    )
    assert t1["task_id"] == "T1_CONCURRENT_ZONE_SPLIT" and t1["arm_a"]["src"] == "belt"

    t2 = guard_mod.validate_two_arm_task_pair(
        {"src": "temp_a:r1-s1-t1", "dst": "stand:r1-s1-t1"},
        {"src": "yard:r1-s2-t1", "dst": "temp_b:r1-s1-t1"},
    )
    assert t2["task_id"] == "T2_CONCURRENT_OUTBOUND_STAGING"

    t3 = guard_mod.validate_two_arm_task_pair(
        {"src": "belt", "dst": "yard:r2-s1-t1"},
        {"src": "belt", "dst": "yard:r1-s2-t1"},
    )
    assert t3["task_id"] == "T3_SHARED_MID_ALTERNATING" and t3["need_mid"] == {"a": True, "b": True}

    for bad_a, bad_b in (
        ({"src": "belt", "dst": "temp_b:r1-s1-t1"}, {"src": "belt", "dst": "temp_b:r2-s1-t1"}),
        ({"src": "temp_a:r1-s1-t1", "dst": "stand:r1-s1-t1"}, {"src": "belt", "dst": "stand:r1-s1-t1"}),
        ({"src": "belt", "dst": "yard:r1-s2-t1"}, {"src": "temp_b:r1-s1-t1", "dst": "yard:r1-s2-t2"}),
        ({"src": "temp_a:r1-s1-t1", "dst": "temp_a:r1-s1-t1"}, {"src": "belt", "dst": "temp_b:r1-s1-t1"}),
        ({"src": "unknown-site", "dst": "temp_a:r1-s1-t1"}, {"src": "belt", "dst": "temp_b:r1-s1-t1"}),
    ):
        with pytest.raises(ValueError):
            guard_mod.validate_two_arm_task_pair(bad_a, bad_b)


def test_two_arm_chunk_guard_concurrency_refusals_and_deadlock():
    kins = {"a": PlanarKin(0.10), "b": PlanarKin(0.10)}
    rigids = {"a": (0.0, 0.0, -0.25), "b": (0.0, 0.0, 0.25)}
    tips = {"a": 0.074, "b": 0.074}
    guard = guard_mod.TwoArmChunkGuard(
        kins, rigids, tips, margin_m=0.05, min_z_m=-0.01, mid_y_band=0.03, wait_timeout_s=0.25,
    )

    # Missing peer pose fails immediately before waiting.
    res_missing = guard.admit_chunk("a", [[-20.0, -20.0, 20.0, 20.0, 0.0, 50.0]])
    assert res_missing == {"admitted": False, "reason": "missing_peer_pose"}

    # Seed separated home poses: both admit simultaneously.
    pose_a = [-40.0, -20.0, 20.0, 20.0, 0.0, 50.0]
    pose_b = [40.0, -20.0, 20.0, 20.0, 0.0, 50.0]
    guard.update_pose("a", pose_a)
    guard.update_pose("b", pose_b)
    adm_a = guard.admit_chunk("a", [pose_a, [-45.0, -20.0, 20.0, 20.0, 0.0, 50.0]])
    adm_b = guard.admit_chunk("b", [pose_b, [45.0, -20.0, 20.0, 20.0, 0.0, 50.0]])
    assert adm_a["admitted"] is True and adm_b["admitted"] is True
    guard.release_chunk("a", final_pose=pose_a)
    guard.release_chunk("b", final_pose=pose_b)

    # Base origin at z=0.0 does not false-trip when link0 proximal point rests on base plate, while limb dip still fails.
    g_base0 = guard_mod.TwoArmChunkGuard(
        {"a": PlanarKin(0.02), "b": PlanarKin(0.02)}, rigids, tips, margin_m=0.05, min_z_m=0.0, mid_y_band=0.03,
    )
    g_base0.update_pose("a", pose_a)
    g_base0.update_pose("b", pose_b)
    assert g_base0.admit_chunk("a", [pose_a])["admitted"] is True
    assert g_base0.admit_chunk("a", [[-40.0, 90.0, 20.0, 20.0, 0.0, 50.0]])["reason"] == "floor_violation"

    # Table floor violation fails immediately.
    bad_floor = guard.admit_chunk("a", [[-40.0, 90.0, 20.0, 20.0, 0.0, 50.0]])
    assert bad_floor["admitted"] is False and bad_floor["reason"] == "floor_violation"

    # Stationary peer collision when reaching straight across onto peer (close bases) refuses immediately.
    close_guard = guard_mod.TwoArmChunkGuard(
        kins, {"a": (0.0, 0.0, -0.04), "b": (0.0, 0.0, 0.04)}, tips,
        margin_m=0.12, min_z_m=-0.10, mid_y_band=0.0, wait_timeout_s=0.5,
    )
    close_guard.update_pose("a", [0.0, 0.0, 0.0, 0.0, 0.0, 50.0])
    close_guard.update_pose("b", [0.0, 0.0, 0.0, 0.0, 0.0, 50.0])
    t0 = time.monotonic()
    res_stat = close_guard.admit_chunk("a", [[0.0, 0.0, 0.0, 0.0, 0.0, 50.0]])
    assert res_stat["admitted"] is False and res_stat["reason"] == "stationary_collision"
    assert (time.monotonic() - t0) < 0.15

    # Mid-zone handoff: arm_a holds mid, arm_b waits cleanly and admits right after release_chunk.
    assert guard.admit_chunk("a", [pose_a], need_mid=True)["admitted"] is True
    b_result = {}

    def wait_for_mid():
        b_result["res"] = guard.admit_chunk("b", [pose_b], need_mid=True, wait_timeout_s=1.0)

    th = threading.Thread(target=wait_for_mid, daemon=True)
    th.start()
    time.sleep(0.05)
    guard.release_chunk("a", final_pose=pose_a)
    th.join(timeout=1.5)
    assert b_result["res"]["admitted"] is True and b_result["res"]["used_mid"] is True
    guard.release_chunk("b", final_pose=pose_b)

    # Wait timeout while peer executes mid.
    assert guard.admit_chunk("a", [pose_a], need_mid=True)["admitted"] is True
    res_to = guard.admit_chunk("b", [pose_b], need_mid=True, wait_timeout_s=0.05)
    assert res_to["admitted"] is False and res_to["reason"] == "wait_timeout"
    guard.release_chunk("a", final_pose=pose_a)

    # Mutual deadlock + coupled latch_stop.
    assert guard.admit_chunk("a", [pose_a], need_mid=True)["admitted"] is True
    guard._arms["a"].waiting = True
    dead = guard.admit_chunk("b", [pose_b], need_mid=True)
    assert dead["admitted"] is False and dead["reason"] == "deadlock"
    guard.release_chunk("a", final_pose=pose_a)

    guard.latch_stop("operator_abort")
    assert guard.admit_chunk("a", [pose_a]) == {"admitted": False, "reason": "coupled_stop:operator_abort"}


def test_run_two_arm_policy_concurrent_live_dry_run_and_coupled_stops(tmp_path):
    home_a = [-40.0, -40.0, 40.0, 40.0, 0.0, 50.0]
    home_b = [40.0, -40.0, 40.0, 40.0, 0.0, 50.0]
    next_a = [-42.0, -40.0, 40.0, 40.0, 0.0, 50.0]
    next_b = [42.0, -40.0, 40.0, 40.0, 0.0, 50.0]
    srv_obj, url, revs = _make_remote_server(
        tmp_path / "srv",
        {"arm_a": lambda obs: [next_a] * 4, "arm_b": lambda obs: [next_b] * 4},
    )
    kins = {"a": PlanarKin(0.10), "b": PlanarKin(0.10)}
    rigids = {"a": (0.0, 0.0, -0.25), "b": (0.0, 0.0, 0.25)}
    tips = {"a": 0.074, "b": 0.074}
    libs = {"a": _base_lib(home_a), "b": _base_lib(home_b)}
    task_a = {"src": "belt", "dst": "temp_a:r1-s1-t1"}
    task_b = {"src": "temp_b:r1-s1-t1", "dst": "temp_b:r2-s1-t1"}
    try:
        sh_a = remote_mod.RemotePolicyShadow(url, "arm_a", revs["arm_a"], timeout_s=0.5)
        sh_b = remote_mod.RemotePolicyShadow(url, "arm_b", revs["arm_b"], timeout_s=0.5)
        # 1. Dry-run sends zero motion/hold commands while running infer + guard.
        dry_a, dry_b = FakeCell(home_a), FakeCell(home_b)
        g_dry = guard_mod.TwoArmChunkGuard(kins, rigids, tips, margin_m=0.05, min_z_m=-0.05, mid_y_band=0.02)
        dry_res = pol_mod.run_two_arm_policy(
            {"a": dry_a, "b": dry_b}, {"a": sh_a, "b": sh_b}, libs, g_dry, task_a, task_b, tmp_path / "dry",
            max_chunks=2, dry_run=True,
        )
        assert dry_res["result"] == "dry_run"
        assert dry_res["arms"]["a"]["chunks_done"] == 2 and dry_res["arms"]["b"]["chunks_done"] == 2
        for c in (dry_a, dry_b):
            assert not any("load" in cmd or "run policy" in cmd or "human-hold" in cmd for cmd in c.commands)

        # 2. Live run without authorizers refuses before touching cells.
        with pytest.raises(ValueError, match="authorizer"):
            pol_mod.run_two_arm_policy(
                {"a": FakeCell(home_a), "b": FakeCell(home_b)}, {"a": sh_a, "b": sh_b}, libs, g_dry,
                task_a, task_b, tmp_path / "noauth", dry_run=False,
            )

        # 3. Live run proves simultaneous execution overlap via barrier inside run policy.
        barrier = threading.Barrier(2, timeout=2.0)
        live_a, live_b = FakeCell(home_a), FakeCell(home_b)
        live_a.on_run = barrier.wait
        live_b.on_run = barrier.wait
        g_live = guard_mod.TwoArmChunkGuard(kins, rigids, tips, margin_m=0.05, min_z_m=-0.05, mid_y_band=0.02)
        auths = {k: (lambda _lib, _st, _seq, _k=k: {"session_id": f"s-{_k}", "library_sha256": "f" * 64}) for k in ("a", "b")}
        live_res = pol_mod.run_two_arm_policy(
            {"a": live_a, "b": live_b}, {"a": sh_a, "b": sh_b}, libs, g_live, task_a, task_b, tmp_path / "live",
            max_chunks=1, dry_run=False, authorizers=auths,
        )
        assert live_res["result"] == "chunks_done" and live_res["task_id"] == "T1_CONCURRENT_ZONE_SPLIT"
        assert any(cmd.endswith("run policy") for cmd in live_a.commands)
        assert any(cmd.endswith("run policy") for cmd in live_b.commands)

        # 4. Pre-chunk floor violation stops BOTH arms via human-hold and never loads or runs policy.
        sh_floor = remote_mod.RemotePolicyShadow(url, "arm_a", revs["arm_a"], timeout_s=0.5)
        bad_a = FakeCell(home_a)
        bad_b = FakeCell(home_b)
        g_floor = guard_mod.TwoArmChunkGuard(kins, rigids, tips, margin_m=0.05, min_z_m=0.50, mid_y_band=0.02)
        ref_res = pol_mod.run_two_arm_policy(
            {"a": bad_a, "b": bad_b}, {"a": sh_floor, "b": sh_b}, libs, g_floor, task_a, task_b, tmp_path / "floor",
            max_chunks=1, dry_run=False, authorizers=auths,
        )
        assert ref_res["result"] == "refused" and "floor_violation" in (ref_res["stopped_reason"] or "")
        assert "human-hold" in bad_a.commands and "human-hold" in bad_b.commands
        assert not any("load" in c or "run policy" in c for c in bad_a.commands)

        # 5. Fault on arm_b halts both arms cleanly and never sends park to faulted arm.
        ok_a = FakeCell(home_a)
        fault_b = FakeCell(home_b, fault="over_temp")
        g_flt = guard_mod.TwoArmChunkGuard(kins, rigids, tips, margin_m=0.05, min_z_m=-0.05)
        flt_res = pol_mod.run_two_arm_policy(
            {"a": ok_a, "b": fault_b}, {"a": sh_a, "b": sh_b}, libs, g_flt, task_a, task_b, tmp_path / "flt",
            max_chunks=1, dry_run=False, authorizers=auths,
        )
        assert flt_res["result"] == "fault" and "human-hold" in ok_a.commands
        assert not any("park" in c for c in fault_b.commands)

        # 6. Remote inference timeout on arm_b latches coupled_stop and sends human-hold to BOTH arms.
        slow_srv, slow_url, slow_revs = _make_remote_server(
            tmp_path / "slow_srv",
            {"arm_a": lambda obs: [next_a] * 4, "arm_b": lambda obs: [next_b] * 4},
            delay_map={"arm_b": 0.35},
        )
        try:
            sh_fast_a = remote_mod.RemotePolicyShadow(slow_url, "arm_a", slow_revs["arm_a"], timeout_s=0.5)
            sh_slow_b = remote_mod.RemotePolicyShadow(slow_url, "arm_b", slow_revs["arm_b"], timeout_s=0.1)
            to_a, to_b = FakeCell(home_a), FakeCell(home_b)
            g_to = guard_mod.TwoArmChunkGuard(kins, rigids, tips, margin_m=0.05, min_z_m=-0.05)
            to_res = pol_mod.run_two_arm_policy(
                {"a": to_a, "b": to_b}, {"a": sh_fast_a, "b": sh_slow_b}, libs, g_to, task_a, task_b, tmp_path / "to",
                max_chunks=1, dry_run=False, authorizers=auths,
            )
            assert to_res["result"] == "refused" and "RemotePolicyError" in (to_res["stopped_reason"] or "")
            assert "human-hold" in to_a.commands and "human-hold" in to_b.commands
        finally:
            slow_srv.shutdown()
            slow_srv.server_close()
    finally:
        srv_obj.shutdown()
        srv_obj.server_close()


def test_cli_d911_d1024_gates_and_dry_run_receipt(tmp_path, monkeypatch, capsys):
    home = [0.0, -40.0, 40.0, 40.0, 0.0, 50.0]
    srv_obj, url, revs = _make_remote_server(
        tmp_path / "srv",
        {"arm_a": lambda obs: [home] * 4, "arm_b": lambda obs: [home] * 4},
    )
    try:
        lib_a = tmp_path / "lib_a.json"
        lib_b = tmp_path / "lib_b.json"
        lib_a.write_text(json.dumps(_base_lib(home)), encoding="utf-8")
        lib_b.write_text(json.dumps(_base_lib(home)), encoding="utf-8")
        cfg_a = tmp_path / "cfg_a.json"
        cfg_b = tmp_path / "cfg_b.json"
        cal_a_p = tmp_path / "cal_a.json"
        cal_b_p = tmp_path / "cal_b.json"
        cal_a_p.write_text(json.dumps({"sites": {"belt": {"homography": [[0.001, 0.0, 0.0], [0.0, 0.001, -0.17], [0.0, 0.0, 1.0]]}}}), encoding="utf-8")
        cal_b_p.write_text(json.dumps({"sites": {"belt": {"homography": [[0.001, 0.0, 0.0], [0.0, 0.001, 0.17], [0.0, 0.0, 1.0]]}}}), encoding="utf-8")
        prof = tmp_path / "profile.json"
        prof.write_text(json.dumps({
            "schema": "rosy.omx-cell-robot-profile.v1",
            "device_id": "dev-1", "instance_id": "arm", "robot_config_sha256": "a" * 64,
            "operating_envelope_path": "rev.json", "work_dir": ".",
        }), encoding="utf-8")
        plan_p = tmp_path / "grasp-plan.json"
        plan_p.write_text((OMX / "grasp-plan.example.json").read_text(encoding="utf-8"), encoding="utf-8")
        for cfg, cal_p in ((cfg_a, cal_a_p), (cfg_b, cal_b_p)):
            cfg.write_text(json.dumps({
                "io": str(tmp_path), "cameras": {}, "operating_profile_path": str(prof),
                "calibration_path": str(cal_p), "plan_path": str(plan_p),
            }), encoding="utf-8")

        base_args = [
            "--config-a", str(cfg_a), "--config-b", str(cfg_b),
            "--endpoint-url", url,
            "--revision-a", revs["arm_a"], "--revision-b", revs["arm_b"],
            "--library-a", str(lib_a), "--library-b", str(lib_b),
            "--task-a", "belt->temp_a:r1-s1-t1", "--task-b", "temp_b:r1-s1-t1->temp_b:r2-s1-t1",
            "--work-dir", str(tmp_path / "work"),
            "--max-chunks", "1",
        ]
        # D-1024 same proposer/operator rejected.
        with pytest.raises(SystemExit):
            cli_mod.main([*base_args, "--proposer", "alice", "--operator", "alice", "--dry-run"])
        # D-911 live without commissioning + person-at-switch rejected.
        with pytest.raises(SystemExit):
            cli_mod.main([*base_args, "--proposer", "alice", "--operator", "bob", "--commissioning"])

        monkeypatch.setattr(cli_mod.cell_two_arm, "open_cells", lambda *_a, **_kw: {"a": FakeCell(home), "b": FakeCell(home)})
        monkeypatch.setattr(cli_mod.cell_two_arm, "kinematics_for", lambda *_a, **_kw: {"a": PlanarKin(0.10), "b": PlanarKin(0.10)})
        rc = cli_mod.main([*base_args, "--proposer", "alice", "--operator", "bob", "--dry-run"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert out["result"] == "dry_run" and out["task_id"] == "T1_CONCURRENT_ZONE_SPLIT"
        receipt = json.loads(Path(out["receipt"]).read_text(encoding="utf-8"))
        assert receipt["proposer"] == "alice" and receipt["operator"] == "bob" and receipt["dry_run"] is True

        # Live without calibration site maps fails closed before inference/motion.
        cfg_nocal = tmp_path / "cfg_nocal.json"
        cfg_nocal.write_text(json.dumps({
            "io": str(tmp_path), "cameras": {}, "operating_profile_path": str(prof), "plan_path": str(plan_p),
        }), encoding="utf-8")
        with pytest.raises(SystemExit, match="calibration site maps"):
            cli_mod.main([
                "--config-a", str(cfg_nocal), "--config-b", str(cfg_b),
                *base_args[4:], "--proposer", "alice", "--operator", "bob",
                "--commissioning", "--person-at-switch",
            ])
    finally:
        srv_obj.shutdown()
        srv_obj.server_close()


def test_review_regressions_playback_offsets_real_kin_mid_and_fault_isolation(tmp_path, monkeypatch, capsys):
    import math as _m
    sys.path.insert(0, str(OMX))
    try:
        import chunk_policy_playback as playback_mod
        import grasp_planner as gp
    finally:
        sys.path.remove(str(OMX))

    # 1. RemotePolicyShadow UNITS.json dir bug fix, bool health guard, int goal slot, sim jaw [0,1] + readback preservation.
    sim_rule = {"schema": "rosy.omx-sim-units.v1", "held_30mm": 53.4, "gap_mm_per_unit": 5.0}
    seen_goal_obs = {}
    srv_sim, url_sim, revs_sim = _make_remote_server(
        tmp_path / "srv_sim",
        {
            "arm_a": lambda obs: (seen_goal_obs.setdefault("a", obs["goal"]) and False) or [[0.0, -0.5, 0.4, 0.5, 0.0, float(obs["state"][-1])]] * 4,
            "arm_b": lambda obs: [[0.0, -0.5, 0.4, 0.5, 0.0, 1.25]] * 4,
        },
        goal_size=4,
        sim_rule=sim_rule,
    )
    try:
        arm_cal_a = tmp_path / "arm-cal-arm_a.json"
        arm_cal_a.write_text(json.dumps({"arm_id": "arm_a", "held_30mm": 53.4, "gap_mm_per_unit": 5.0}), encoding="utf-8")
        sh_sim = remote_mod.RemotePolicyShadow(
            url_sim, "arm_a", revs_sim["arm_a"], timeout_s=0.5,
            policy_root=tmp_path / "srv_sim/arm_a",
            config={"arm_id": "arm_a", "arm_calibration_path": str(arm_cal_a)},
        )
        assert sh_sim.sim_rule is not None
        img = np.zeros((24, 32, 3), dtype=np.uint8)
        obs_g, meta_g = sh_sim.inputs([0.0, -40.0, 40.0, 40.0, 0.0, 80.0], {"top": img, "wrist": img}, goal=2)
        assert meta_g["goal_slot"] == 2 and seen_goal_obs == {}
        res_g = sh_sim.infer(obs_g, state=[0.0, -40.0, 40.0, 40.0, 0.0, 80.0])
        assert seen_goal_obs["a"] == [0.0, 0.0, 1.0, 0.0]
        assert res_g.chunk[0][5] == pytest.approx(80.0)  # gap > 60 preserves readback when echoing clipped angle

        sh_bad_jaw = remote_mod.RemotePolicyShadow(url_sim, "arm_b", revs_sim["arm_b"], timeout_s=0.5, sim_rule=sim_rule)
        obs_b, _ = sh_bad_jaw.inputs([0.0, -40.0, 40.0, 40.0, 0.0, 53.4], {"top": img, "wrist": img}, goal=1)
        with pytest.raises(remote_mod.RemotePolicyError, match=r"0\.\.1"):
            sh_bad_jaw.infer(obs_b)

        with pytest.raises(remote_mod.RemotePolicyError, match="metadata"):
            class _Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *_a):
                    return False

                def read(self):
                    return json.dumps({
                        "ok": True,
                        "arms": {"arm_a": {"revision": revs_sim["arm_a"], "views": {"top": [24, 32]}, "n_action_steps": True, "chunk_size": 4}},
                    }).encode("utf-8")

            remote_mod.RemotePolicyShadow(
                url_sim, "arm_a", revs_sim["arm_a"], timeout_s=0.5, sim_rule=sim_rule,
                opener=lambda *_a, **_kw: _Resp(),
            )
    finally:
        srv_sim.shutdown()
        srv_sim.server_close()

    # 2. Real OmxKinematics + fingertip_m=0.0 + physical X-separated rigids: no floor false-trip and accurate midline bisector.
    real_kin, _, _ = gp.load_kinematics(None, 0.074)
    kins_real = {"a": real_kin, "b": real_kin}
    rigids_x = {"a": (_m.pi, 0.34, 0.0), "b": (0.0, 0.0, 0.0)}
    tips_zero = {"a": 0.0, "b": 0.0}
    home_real = [0.0, -58.0, 50.0, 50.0, -5.0, 50.0]
    away_mid = [-60.0, -58.0, 50.0, 50.0, -5.0, 50.0]
    reach_mid = [0.0, -20.0, 15.0, 45.0, 0.0, 50.0]
    g_real = guard_mod.TwoArmChunkGuard(kins_real, rigids_x, tips_zero, margin_m=0.02, min_z_m=-0.02, mid_y_band=0.04)
    g_real.update_pose("a", away_mid)
    g_real.update_pose("b", away_mid)
    r_home = g_real.admit_chunk("b", [away_mid])
    assert r_home["admitted"] is True and r_home["used_mid"] is False
    g_real.release_chunk("b", final_pose=away_mid)
    r_reach = g_real.admit_chunk("b", [reach_mid])
    assert r_reach["admitted"] is True and r_reach["used_mid"] is True
    g_real.release_chunk("b", final_pose=away_mid)

    # 3. validate_two_arm_task_pair rejects belt destination & ensures need_mid when one arm enters mid; woken peer -> stationary_collision.
    with pytest.raises(ValueError, match="destination"):
        guard_mod.validate_two_arm_task_pair({"src": "temp_a:r1-s1-t1", "dst": "belt"}, {"src": "temp_b:r1-s1-t1", "dst": "temp_b:r2-s1-t1"})
    t1_mid_a = guard_mod.validate_two_arm_task_pair({"src": "belt", "dst": "temp_a:r1-s1-t1"}, {"src": "temp_b:r1-s1-t1", "dst": "temp_b:r2-s1-t1"})
    assert t1_mid_a["task_id"] == "T1_CONCURRENT_ZONE_SPLIT" and t1_mid_a["need_mid"] == {"a": True, "b": False}

    g_woken = guard_mod.TwoArmChunkGuard(
        {"a": PlanarKin(0.10), "b": PlanarKin(0.10)}, {"a": (0.0, 0.0, -0.04), "b": (0.0, 0.0, 0.04)}, tips_zero,
        margin_m=0.12, min_z_m=-0.10, mid_y_band=0.0,
    )
    g_woken.update_pose("a", [0.0] * 6)
    g_woken.update_pose("b", [0.0] * 6)
    g_woken._arms["b"].waiting = True
    assert g_woken.admit_chunk("a", [[0.0] * 6])["reason"] == "stationary_collision"
    g_woken._arms["b"].waiting = False

    # 4. Offset signs (+off on input, -off on output), real Playback contract + jaw_gate, and coupled hold / safe_fold failures.
    class RecShadow:
        image_views = {"top": (24, 32)}
        sim_rule = None
        arm_id = "arm_a"

        def __init__(self, target_out):
            self.target_out = target_out
            self.saw_in = []
            self.saw_st = []

        def inputs(self, state, frames, goal=None):
            self.saw_in.append(list(state))
            return {"state": list(state), "frames": frames}, {"frame_count": 1}

        def infer(self, obs, state=None):
            self.saw_st.append(list(state) if isinstance(state, list) else state)
            return SimpleNamespace(chunk=[list(self.target_out)] * 2, rtt_s=0.005)

    lib_jaw = {
        **_base_lib(home_real),
        "chunks": {
            **_base_lib(home_real)["chunks"],
            "grasp_pick": [home_real, [0.0, -25.0, 35.0, 45.0, -5.0, 47.0]],
        },
        "source": {"pick": {"x": 0.14, "y": 0.0, "z": 0.04, "yaw_deg": 0.0}},
    }
    jspec = {"x": 0.14, "y": 0.0, "z_m": 0.04, "xy_radius_m": 0.08, "yaw_deg": 0.0, "tol_deg": 45.0, "max_tilt_rad": 1.0, "tcp_x_m": 0.074}
    auths = {k: (lambda _lib, _st, _seq, _k=k: {"session_id": f"s-{_k}", "library_sha256": "f" * 64}) for k in ("a", "b")}
    work_pb = tmp_path / "pb_work"
    ca, cb = FakeCell(home_real), FakeCell(home_real)
    off_a = [2.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    sh_a = RecShadow([2.0, -58.0, 50.0, 50.0, -5.0, 50.0])
    sh_b = RecShadow(home_real)
    g_pb = guard_mod.TwoArmChunkGuard(kins_real, rigids_x, tips_zero, margin_m=0.02, min_z_m=-0.02, mid_y_band=0.02)
    res_pb = pol_mod.run_two_arm_policy(
        {"a": ca, "b": cb},
        {"a": sh_a, "b": sh_b},
        {"a": lib_jaw, "b": _base_lib(home_real)},
        g_pb, {"src": "temp_a:r1-s1-t1", "dst": "temp_a:r2-s1-t1"}, {"src": "temp_b:r1-s1-t1", "dst": "temp_b:r2-s1-t1"},
        work_pb, offsets={"a": off_a, "b": [0.0] * 6}, jaw_specs={"a": jspec, "b": None}, kins=kins_real,
        max_chunks=1, dry_run=False, authorizers=auths,
    )
    assert res_pb["result"] == "chunks_done"
    assert sh_a.saw_in[0][0] == pytest.approx(2.0) and sh_a.saw_st[0] == home_real
    assert sh_b.saw_in[0][0] == pytest.approx(0.0) and sh_b.saw_st[0] == home_real
    saved_chunk = json.loads((work_pb / "arm_a-chunk-0.json").read_text(encoding="utf-8"))
    assert saved_chunk["chunks"]["policy"][0][0] == pytest.approx(0.0)
    play = playback_mod.Playback(saved_chunk["policy_playback"], float(saved_chunk["fps"]))
    assert play.ready(saved_chunk["chunks"]["policy"], home_real, saved_chunk["policy_playback"]["start"])
    assert "jaw_gate" in saved_chunk["policy_playback"]

    # load_reply fault skips safe_fold; coupled human hold stays 'refused'; failed safe_fold downgrades to 'refused'.
    c_load_flt = FakeCell(home_real)
    orig_act = c_load_flt.act
    c_load_flt.act = lambda cmd: ({"ok": False, "fault": "overload"} if " load " in cmd else orig_act(cmd))
    fold_called = []
    monkeypatch.setattr(pol_mod.cell_two_arm, "away_from_home", lambda *_a: ["a"])
    monkeypatch.setattr(pol_mod.cell_two_arm, "safe_fold", lambda *_a, **_kw: fold_called.append(True) or {"folded": False, "person_needed": "jammed"})
    res_lf = pol_mod.run_two_arm_policy(
        {"a": c_load_flt, "b": FakeCell(home_real)}, {"a": RecShadow(home_real), "b": RecShadow(home_real)},
        {"a": _base_lib(home_real), "b": _base_lib(home_real)},
        guard_mod.TwoArmChunkGuard(kins_real, rigids_x, tips_zero, margin_m=0.02, min_z_m=-0.05),
        {"src": "temp_a:r1-s1-t1", "dst": "temp_a:r2-s1-t1"}, {"src": "temp_b:r1-s1-t1", "dst": "temp_b:r2-s1-t1"},
        tmp_path / "lf_work", max_chunks=1, dry_run=False, authorizers=auths,
        fold_context={"kin": kins_real, "rigids": rigids_x, "tips": tips_zero, "margin_m": 0.02},
    )
    assert res_lf["result"] == "fault" and fold_called == []

    # Failed safe_fold downgrades overall result to refused.
    res_bad_fold = pol_mod.run_two_arm_policy(
        {"a": FakeCell(home_real), "b": FakeCell(home_real)}, {"a": RecShadow(home_real), "b": RecShadow(home_real)},
        {"a": _base_lib(home_real), "b": _base_lib(home_real)},
        guard_mod.TwoArmChunkGuard(kins_real, rigids_x, tips_zero, margin_m=0.02, min_z_m=-0.05),
        {"src": "temp_a:r1-s1-t1", "dst": "temp_a:r2-s1-t1"}, {"src": "temp_b:r1-s1-t1", "dst": "temp_b:r2-s1-t1"},
        tmp_path / "bf_work", max_chunks=1, dry_run=False, authorizers=auths,
        fold_context={"kin": kins_real, "rigids": rigids_x, "tips": tips_zero, "margin_m": 0.02},
    )
    assert res_bad_fold["result"] == "refused" and res_bad_fold["stopped_reason"] == "jammed"

    # Coupled human-hold peer fault stays refused (not hardware fault), and post-wait stale observation aborts before load.
    hold_latched = threading.Event()
    c_hh_a, c_hh_b = FakeCell(home_real), FakeCell(home_real)
    c_hh_a.fail_load = True
    orig_hh_a = c_hh_a.act
    def act_a(cmd):
        if cmd == "human-hold":
            hold_latched.set()
        return orig_hh_a(cmd)
    c_hh_a.act = act_a
    c_hh_b.act = lambda cmd: (
        (hold_latched.wait(1.0) and False) or {"ok": False, "fault": "human hold", "settled": False}
        if cmd.endswith("run policy")
        else FakeCell.act(c_hh_b, cmd)
    )
    res_chh = pol_mod.run_two_arm_policy(
        {"a": c_hh_a, "b": c_hh_b}, {"a": RecShadow(home_real), "b": RecShadow(home_real)},
        {"a": _base_lib(home_real), "b": _base_lib(home_real)},
        guard_mod.TwoArmChunkGuard(kins_real, rigids_x, tips_zero, margin_m=0.02, min_z_m=-0.05),
        {"src": "temp_a:r1-s1-t1", "dst": "temp_a:r2-s1-t1"}, {"src": "temp_b:r1-s1-t1", "dst": "temp_b:r2-s1-t1"},
        tmp_path / "chh_work", max_chunks=1, dry_run=False, authorizers=auths,
    )
    assert res_chh["result"] == "refused"

    # Post-guard-wait stale observation triggers bounded re-observation with fresh frames so both arms finish cleanly.
    g_wait = guard_mod.TwoArmChunkGuard(kins_real, rigids_x, tips_zero, margin_m=0.02, min_z_m=-0.05, mid_y_band=0.0)
    c_wa, c_wb = FakeCell(home_real, delay_s=0.08), FakeCell(home_real, delay_s=0.08)
    sh_wa, sh_wb = RecShadow(home_real), RecShadow(home_real)
    res_wait = pol_mod.run_two_arm_policy(
        {"a": c_wa, "b": c_wb}, {"a": sh_wa, "b": sh_wb},
        {"a": _base_lib(home_real), "b": _base_lib(home_real)},
        g_wait, {"src": "belt", "dst": "temp_a:r1-s1-t1"}, {"src": "belt", "dst": "temp_b:r1-s1-t1"},
        tmp_path / "stale_wait", max_chunks=1, dry_run=False, max_obs_age_s=0.04, authorizers=auths,
    )
    assert res_wait["result"] == "chunks_done"
    assert any(ev.get("event") == "reobserve_after_wait" for ev in res_wait["events"])
    assert sum(" load " in f" {c}" for c in c_wa.commands + c_wb.commands) == 2
    assert len(sh_wa.saw_in) + len(sh_wb.saw_in) == 3

    # CLI live preflight: binds profile into Authorization, pops static _commissioning, validates normalized cal, goal slot, tips==0.0.
    srv_goal, url_goal, revs_goal = _make_remote_server(
        tmp_path / "srv_cli_live",
        {"arm_a": lambda obs: [home_real] * 4, "arm_b": lambda obs: [home_real] * 4},
        goal_size=4,
    )
    try:
        cli_dir = tmp_path / "cli_live"
        cli_dir.mkdir()
        (cli_dir / "lib.json").write_text(json.dumps(_base_lib(home_real)), encoding="utf-8")
        (cli_dir / "plan.json").write_text((OMX / "grasp-plan.example.json").read_text(encoding="utf-8"), encoding="utf-8")
        jcal = {n: {"range_min": 0, "range_max": 4095, "homing_offset": 0, "drive_mode": 0} for n in remote_mod.JOINT_NAMES}
        (cli_dir / "jcal.json").write_text(json.dumps(jcal), encoding="utf-8")
        (cli_dir / "cal_a.json").write_text(json.dumps({"sites": {"belt": {"homography": [[0.001, 0, 0], [0, 0.001, -0.17], [0, 0, 1]]}}}), encoding="utf-8")
        (cli_dir / "cal_b.json").write_text(json.dumps({"sites": {"belt": {"homography": [[0.001, 0, 0], [0, 0.001, 0.17], [0, 0, 1]]}}}), encoding="utf-8")
        (cli_dir / "prof.json").write_text(json.dumps({
            "schema": "rosy.omx-cell-robot-profile.v1", "device_id": "dev-cli", "instance_id": "arm",
            "robot_config_sha256": "a" * 64, "operating_envelope_path": "env_rev.json", "work_dir": "work_rel",
        }), encoding="utf-8")
        for idx_c, cal_name in (("a", "cal_a.json"), ("b", "cal_b.json")):
            (cli_dir / f"cfg_{idx_c}.json").write_text(json.dumps({
                "io": str(cli_dir), "cameras": {}, "operating_profile_path": str(cli_dir / "prof.json"),
                "calibration_path": str(cli_dir / cal_name), "plan_path": str(cli_dir / "plan.json"),
                "_commissioning": {"person_at_switch": True},
            }), encoding="utf-8")

        seen_auth_cfg, seen_tips = [], []
        monkeypatch.setattr(cli_mod.cell_two_arm, "open_cells", lambda *_a, **_kw: {"a": FakeCell(home_real), "b": FakeCell(home_real)})
        monkeypatch.setattr(cli_mod.cell_two_arm, "kinematics_for", lambda *_a, **_kw: kins_real)
        monkeypatch.setattr(cli_mod.cell_two_arm, "away_from_home", lambda *_a: [])
        monkeypatch.setattr(cli_mod.cell_policy_handoff, "Authorization", lambda cfg: seen_auth_cfg.append(cfg) or (lambda *_a: {"session_id": "s-ok", "library_sha256": "e" * 64}))
        orig_guard_cls = cli_mod.TwoArmChunkGuard
        monkeypatch.setattr(cli_mod, "TwoArmChunkGuard", lambda k, r, t, **kw: seen_tips.append(t) or orig_guard_cls(k, r, t, **kw))
        monkeypatch.setattr(cli_mod, "run_two_arm_policy", lambda *_a, **_kw: {"result": "chunks_done", "task_id": "T1_CONCURRENT_ZONE_SPLIT"})

        live_args = [
            "--config-a", str(cli_dir / "cfg_a.json"), "--config-b", str(cli_dir / "cfg_b.json"),
            "--endpoint-url", url_goal, "--revision-a", revs_goal["arm_a"], "--revision-b", revs_goal["arm_b"],
            "--library-a", str(cli_dir / "lib.json"), "--library-b", str(cli_dir / "lib.json"),
            "--task-a", "belt->temp_a:r1-s1-t1", "--task-b", "temp_b:r1-s1-t1->temp_b:r2-s1-t1",
            "--goal-a", "2", "--goal-b", "1",
            "--model-cal-a", str(cli_dir / "jcal.json"), "--cell-cal-a", str(cli_dir / "jcal.json"),
            "--model-cal-b", str(cli_dir / "jcal.json"), "--cell-cal-b", str(cli_dir / "jcal.json"),
            "--work-dir", str(cli_dir / "out"), "--max-chunks", "1",
            "--proposer", "alice", "--operator", "bob", "--commissioning", "--person-at-switch",
        ]
        # Live without a checkpoint folder cannot judge the start state: refused before the runner is built (start gate, 2026-11-26).
        monkeypatch.setattr(cli_mod, "_arm_state_gate", REAL_ARM_STATE_GATE)
        assert cli_mod.main(live_args) == 1
        assert "--policy-root-a is required" in capsys.readouterr().out
        gate_roots, passed_gates = [], {}
        monkeypatch.setattr(cli_mod, "build_gate", lambda root, *_a: gate_roots.append(Path(root).name) or f"gate-{Path(root).name}")
        monkeypatch.setattr(cli_mod.cell_policy_shape, "demonstrated_range", lambda *_a: None)
        monkeypatch.setattr(cli_mod, "run_two_arm_policy", lambda *_a, **kw: passed_gates.update(kw["state_gates"]) or {"result": "chunks_done", "task_id": "T1_CONCURRENT_ZONE_SPLIT"})
        rc_live = cli_mod.main([*live_args, "--policy-root-a", str(cli_dir / "ckpt_a"), "--policy-root-b", str(cli_dir / "ckpt_b")])
        assert rc_live == 0
        assert gate_roots == ["ckpt_a", "ckpt_b"] and passed_gates == {"a": "gate-ckpt_a", "b": "gate-ckpt_b"}  # each arm: its own checkpoint
        assert seen_tips[0] == {"a": 0.0, "b": 0.0}
        assert len(seen_auth_cfg) == 2 and str(seen_auth_cfg[0]["operating_envelope_path"]).endswith("env_rev.json")
        assert seen_auth_cfg[0]["_commissioning"] == {"person_at_switch": True}

        # Live normalized checkpoint missing --model-cal-a must exit cleanly.
        with pytest.raises(SystemExit, match="model-cal-a"):
            cli_mod.main([
                "--config-a", str(cli_dir / "cfg_a.json"), "--config-b", str(cli_dir / "cfg_b.json"),
                "--endpoint-url", url_goal, "--revision-a", revs_goal["arm_a"], "--revision-b", revs_goal["arm_b"],
                "--library-a", str(cli_dir / "lib.json"), "--library-b", str(cli_dir / "lib.json"),
                "--task-a", "belt->temp_a:r1-s1-t1", "--task-b", "temp_b:r1-s1-t1->temp_b:r2-s1-t1",
                "--goal-a", "2", "--goal-b", "1",
                "--work-dir", str(cli_dir / "out2"), "--max-chunks", "1",
                "--proposer", "alice", "--operator", "bob", "--commissioning", "--person-at-switch",
            ])
    finally:
        srv_goal.shutdown()
        srv_goal.server_close()

    # R2 findings: 2-tick Playback start lead under authorize+FIFO latency, post-wait fresh auth state, canonical rim_z_m.
    seen_auth_t: dict[str, list[float]] = {"a": [], "b": []}
    enter_auth_mono: dict[str, float] = {}
    pre_wait_t = {"a": time.time() - 0.55, "b": time.time() - 0.55}

    class StaleFirstCell(FakeCell):
        def __init__(self, pose, arm_key):
            super().__init__(pose, delay_s=0.06 if arm_key == "a" else 0.0)
            self._arm_key = arm_key
            self._reads = 0

        def act(self, cmd: str):
            res = super().act(cmd)
            if cmd == "state":
                self._reads += 1
                if self._reads in (2, 3):  # pre and pre_shape reads before admit_chunk
                    res["t"] = pre_wait_t[self._arm_key]
            return res

    def auth_delayed(arm_k):
        def _auth(_lib, st, _seq):
            seen_auth_t[arm_k].append(float(st["t"]))
            enter_auth_mono[arm_k] = time.monotonic()
            return {"session_id": f"s-r2-{arm_k}", "library_sha256": "f" * 64}
        return _auth

    work_r2 = tmp_path / "r2_work"
    res_r2 = pol_mod.run_two_arm_policy(
        {"a": StaleFirstCell(home_real, "a"), "b": StaleFirstCell(home_real, "b")},
        {"a": RecShadow(home_real), "b": RecShadow(home_real)},
        {"a": lib_jaw, "b": _base_lib(home_real)},
        guard_mod.TwoArmChunkGuard(kins_real, rigids_x, tips_zero, margin_m=0.02, min_z_m=-0.05, mid_y_band=0.0),
        {"src": "belt", "dst": "temp_a:r1-s1-t1"}, {"src": "belt", "dst": "temp_b:r1-s1-t1"},
        work_r2, max_chunks=1, dry_run=False, max_obs_age_s=1.5,
        jaw_specs={"a": jspec, "b": None}, kins=kins_real,
        authorizers={"a": auth_delayed("a"), "b": auth_delayed("b")},
    )
    assert res_r2["result"] == "chunks_done"
    for arm_k in ("a", "b"):
        assert seen_auth_t[arm_k] and seen_auth_t[arm_k][0] > pre_wait_t[arm_k] + 0.30
    saved_r2 = json.loads((work_r2 / "arm_a-chunk-0.json").read_text(encoding="utf-8"))
    play_r2 = playback_mod.Playback(saved_r2["policy_playback"], float(saved_r2["fps"]))
    assert saved_r2["policy_playback"]["start"] > enter_auth_mono["a"] + 0.045
    assert play_r2.ready(saved_r2["chunks"]["policy"], home_real, enter_auth_mono["a"] + 0.04) is False
    assert play_r2.ready(saved_r2["chunks"]["policy"], home_real, saved_r2["policy_playback"]["start"]) is True

    for site_cfg, task_spec, expected_rim in (
        ({"sites": {"belt": {"surface_z": 0.049, "rim_z": 0.082}}}, {"src": "not_places:belt", "dst": "temp_a:r1-s1-t1"}, 0.082),
        ({"sites": {"tmp-a-1": {"surface_z": 0.040, "rim_z": 0.075}}}, {"src": "temp_a:r1-s1-t1", "dst": "temp_a:r2-s1-t1"}, 0.075),
        ({"sites": {"ship-h2r0": {"surface_z": 0.030, "rim_z": 0.068}}}, {"src": "yard:r1-s1-t1", "dst": "temp_a:r1-s1-t1"}, 0.068),
    ):
        spec_r2 = cli_mod._build_jaw_spec("a", site_cfg, lib_jaw, real_kin, task_spec)
        assert spec_r2 is not None and spec_r2["rim_z_m"] == pytest.approx(expected_rim)


def test_remote_policy_shadow_reuses_keepalive_connection_caches_ip_and_verifies_request_id(tmp_path, monkeypatch):
    import socket

    mode = {"fail": False, "drop": False}
    infer_calls = [0]

    def arm_a_fn(obs):
        infer_calls[0] += 1
        if mode["drop"]:
            for sock in list(srv_obj._active_socks):
                srv_obj._close_sock(sock)
            return [[0.0] * 6] * 4
        if mode["fail"]:
            raise RuntimeError("transient infer boom")
        return [[0.0, -0.5, 0.4, 0.5, 0.0, 0.6]] * 4

    srv_obj, url, revs = _make_remote_server(tmp_path / "ka", {"arm_a": arm_a_fn})
    srv_obj.handle_error = lambda *_a, **_kw: None
    accepted = [0]
    orig_get_request = srv_obj.get_request

    def _counting_accept():
        accepted[0] += 1
        return orig_get_request()

    srv_obj.get_request = _counting_accept
    port = srv_obj.server_address[1]
    real_getaddrinfo = socket.getaddrinfo
    real_socket_cls = socket.socket
    dns_calls, connect_attempts = [], []

    def _spy_getaddrinfo(host, p, *args, **kwargs):
        dns_calls.append(host)
        if host == "localhost":
            good = real_getaddrinfo("127.0.0.1", p, *args, **kwargs)
            bad = [(socket.AF_INET, g[1], g[2], g[3], ("127.0.0.2", p)) for g in good[:1]]
            return bad + good
        return real_getaddrinfo(host, p, *args, **kwargs)

    class _TimeoutFirstSocket(real_socket_cls):
        def connect(self, addr):
            connect_attempts.append((addr, self.gettimeout()))
            if addr[0] == "127.0.0.2":
                raise TimeoutError("simulated connect timeout")
            return super().connect(addr)

    try:
        img = np.zeros((24, 32, 3), dtype=np.uint8)
        with monkeypatch.context() as mp:
            mp.setattr(socket, "getaddrinfo", _spy_getaddrinfo)
            mp.setattr(socket, "socket", _TimeoutFirstSocket)
            sh = remote_mod.RemotePolicyShadow(f"http://localhost:{port}", "arm_a", revs["arm_a"], token="ka-tok", timeout_s=0.5)
            assert any(a[0] == "127.0.0.2" and t is not None and 0 < t <= 0.35 for a, t in connect_attempts)
            assert sh._resolved_addrs[0][3] == ("127.0.0.1", port) and len(sh._resolved_addrs) == 2
            obs, _ = sh.inputs([0.0] * 6, {"top": img, "wrist": img})
            for _ in range(3):
                res = sh.infer(obs)
                assert len(res.chunk) == 4
            assert dns_calls == ["localhost"] and accepted[0] == 1 and infer_calls[0] == 3
            assert sh._conn is not None and sh._conn.sock is not None
            assert sh._conn.sock.gettimeout() == pytest.approx(0.5)
            assert sh._conn.sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) != 0

            # Server 500 closes connection while retaining working address cache.
            mode["fail"] = True
            with pytest.raises(remote_mod.RemotePolicyError, match="HTTP 500"):
                sh.infer(obs)
            assert sh._conn is None and sh._resolved_addrs[0][3] == ("127.0.0.1", port) and infer_calls[0] == 4

            mode["fail"] = False
            assert len(sh.infer(obs).chunk) == 4
            assert dns_calls == ["localhost"] and accepted[0] == 2 and infer_calls[0] == 5

            # Mid-request socket drop fails closed with zero /infer resend and resets resolved cache.
            mode["drop"] = True
            with pytest.raises(remote_mod.RemotePolicyError):
                sh.infer(obs)
            assert sh._conn is None and sh._resolved_addrs == [] and infer_calls[0] == 6

            mode["drop"] = False
            res_reconnect = sh.infer(obs)
            assert len(res_reconnect.chunk) == 4
            assert dns_calls == ["localhost", "localhost"] and accepted[0] == 3 and infer_calls[0] == 7
            sh.close()
            assert sh._conn is None

        # IPv6 link-local scope_id is preserved across distinct interfaces.
        with monkeypatch.context() as mp_v6:
            mp_v6.setattr(
                socket,
                "getaddrinfo",
                lambda *_a, **_kw: [
                    (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("fe80::1", port, 0, 2)),
                    (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("fe80::1", port, 0, 3)),
                ],
            )
            scoped = sh._resolve_addrs()
            assert len(scoped) == 2 and [a[3][3] for a in scoped] == [2, 3]

        # Mismatched request_id in server reply fails closed.
        class _WrongReqIdResp:
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def read(self):
                return json.dumps({
                    "ok": True, "request_id": "wrong-req-id", "arm_id": "arm_a",
                    "revision": revs["arm_a"], "chunk": [[0.0] * 6],
                }).encode("utf-8")

        sh_bad = remote_mod.RemotePolicyShadow(url, "arm_a", revs["arm_a"], timeout_s=0.5)
        sh_bad._opener = lambda *_a, **_kw: _WrongReqIdResp()
        obs_bad, _ = sh_bad.inputs([0.0] * 6, {"top": img, "wrist": img})
        with pytest.raises(remote_mod.RemotePolicyError, match="request_id"):
            sh_bad.infer(obs_bad)
    finally:
        srv_obj.shutdown()
        srv_obj.server_close()


def test_two_arm_single_row_library_and_worker_setup_exception(tmp_path):
    from omx_adapter.chunk_library import NAMES as OMX_NAMES, SCHEMA as OMX_SCHEMA

    home_real = [0.0, -58.0, 51.0, 50.0, 0.0, 49.0]
    kins_real = {"a": PlanarKin(), "b": PlanarKin()}
    rigids_x = {"a": np.array([0.0, -0.17, 0.0]), "b": np.array([0.0, 0.17, 0.0])}
    tips_zero = {"a": 0.0, "b": 0.0}
    auths = {a: (lambda *_x: {"session_id": "s", "library_sha256": "h" * 64}) for a in ("a", "b")}
    lib_1 = {"schema": OMX_SCHEMA, "names": OMX_NAMES, "fps": 30, "gripper_closed": 49.0, "chunks": {"home": [home_real]}}

    class _Cell:
        def act(self, cmd):
            base = cmd.split(" ", 3)[-1] if cmd.startswith("checked ") else cmd
            return {"ok": True, "settled": True, "state": list(home_real), "command": base, "holding": False,
                    **({"human_hold_latched": True, "torque_hold_commanded": True} if base == "human-hold" else {})}

        def frame_receipt(self, _v, **_kw):
            return {"image": np.zeros((4, 4, 3), np.uint8), "source_stamp": time.time()}

    class _Shadow:
        image_views, sim_rule = {"top": (4, 4), "wrist": (4, 4)}, None
        inputs = staticmethod(lambda _s, _f, goal=None: ({}, {}))
        infer = staticmethod(lambda _o, state=None: SimpleNamespace(chunk=[home_real] * 2, rtt_s=0.01))

    res_ok = pol_mod.run_two_arm_policy(
        {"a": _Cell(), "b": _Cell()}, {"a": _Shadow(), "b": _Shadow()}, {"a": lib_1, "b": lib_1},
        guard_mod.TwoArmChunkGuard(kins_real, rigids_x, tips_zero, margin_m=0.02, min_z_m=-0.05),
        {"src": "temp_a:r1-s1-t1", "dst": "temp_a:r2-s1-t1"}, {"src": "temp_b:r1-s1-t1", "dst": "temp_b:r2-s1-t1"},
        tmp_path / "single_row", max_chunks=1, dry_run=True, authorizers=auths,
    )
    assert res_ok["result"] == "dry_run" and res_ok["arms"]["b"]["outcome"] == "dry_run"

    bad_b = {**lib_1, "chunks": {"home": [[0.0, -58.0, 51.0, 50.0, float("nan"), 49.0]]}}
    res_bad = pol_mod.run_two_arm_policy(
        {"a": _Cell(), "b": _Cell()}, {"a": _Shadow(), "b": _Shadow()}, {"a": lib_1, "b": bad_b},
        guard_mod.TwoArmChunkGuard(kins_real, rigids_x, tips_zero, margin_m=0.02, min_z_m=-0.05),
        {"src": "temp_a:r1-s1-t1", "dst": "temp_a:r2-s1-t1"}, {"src": "temp_b:r1-s1-t1", "dst": "temp_b:r2-s1-t1"},
        tmp_path / "bad_setup", max_chunks=1, dry_run=False, authorizers=auths,
    )
    assert res_bad["result"] == "refused" and "b" in res_bad["arms"] and "b:setup:" in (res_bad["stopped_reason"] or "")


def test_pr1_wait_exhaustion_hold_retries_fault_pose_and_released_completion(tmp_path, monkeypatch):
    home_a = [-40.0, -40.0, 40.0, 40.0, 0.0, 50.0]
    home_b = [40.0, -40.0, 40.0, 40.0, 0.0, 50.0]
    kins = {"a": PlanarKin(0.10), "b": PlanarKin(0.10)}
    rigids = {"a": (0.0, 0.0, -0.25), "b": (0.0, 0.0, 0.25)}
    tips = {"a": 0.074, "b": 0.074}
    libs = {"a": _base_lib(home_a), "b": _base_lib(home_b)}
    task_a = {"src": "temp_a:r1-s1-t1", "dst": "temp_a:r2-s1-t1"}
    task_b = {"src": "temp_b:r1-s1-t1", "dst": "temp_b:r2-s1-t1"}
    auths = {k: (lambda _lib, _st, _seq, _k=k: {"session_id": f"s-{_k}", "library_sha256": "f" * 64}) for k in ("a", "b")}

    class _Shadow:
        image_views = {"top": (24, 32)}
        sim_rule = None

        def __init__(self, out_fn):
            self.out_fn = out_fn
            self.calls = 0

        def inputs(self, state, frames, goal=None):
            return {"state": list(state)}, {"frame_count": 1}

        def infer(self, obs, state=None):
            idx = self.calls
            self.calls += 1
            return SimpleNamespace(chunk=self.out_fn(idx), rtt_s=0.002)

    # 1. Default wait_timeout_s covers real chunk durations (4.0s).
    g_def = guard_mod.TwoArmChunkGuard(kins, rigids, tips)
    assert g_def._wait_timeout_s == pytest.approx(4.0)

    # 2. _hold_arm retries unconfirmed replies via send_hold and logs failures cleanly.
    attempts_ok = [0]

    class _FlakyHoldCell:
        def act(self, cmd):
            assert cmd == "human-hold"
            attempts_ok[0] += 1
            ok_latched = attempts_ok[0] >= 3
            return {"ok": True, "command": "human-hold", "human_hold_latched": True, "torque_hold_commanded": ok_latched}

    assert pol_mod._hold_arm(_FlakyHoldCell()) is True and attempts_ok[0] == 3
    logged_holds = []

    class _NeverConfirmHoldCell:
        def act(self, _cmd):
            return {"ok": True, "command": "human-hold", "human_hold_latched": True, "torque_hold_commanded": False}

    assert pol_mod._hold_arm(_NeverConfirmHoldCell(), log=logged_holds.append) is False
    assert logged_holds and logged_holds[0]["unconfirmed"] is True

    # 3. Exhausting post-wait re-observe retries fails closed before any stale load/run policy.
    g_exhaust = guard_mod.TwoArmChunkGuard(kins, rigids, tips, margin_m=0.02, min_z_m=-0.05)
    orig_admit = g_exhaust.admit_chunk

    def slow_admit(arm, chunk, **kw):
        res = orig_admit(arm, chunk, **kw)
        if arm == "a" and res.get("admitted"):
            time.sleep(0.05)
        return res

    g_exhaust.admit_chunk = slow_admit
    ca_ex, cb_ex = FakeCell(home_a), FakeCell(home_b)
    sh_ex_a = _Shadow(lambda _i: [home_a] * 2)
    res_ex = pol_mod.run_two_arm_policy(
        {"a": ca_ex, "b": cb_ex}, {"a": sh_ex_a, "b": _Shadow(lambda _i: [home_b] * 2)},
        libs, g_exhaust, task_a, task_b, tmp_path / "exhaust",
        max_chunks=1, dry_run=False, max_obs_age_s=0.03, authorizers=auths,
    )
    assert res_ex["result"] == "refused"
    assert "stale policy observation after guard wait" in (res_ex["stopped_reason"] or "")
    assert sum(1 for ev in res_ex["events"] if ev.get("event") == "reobserve_after_wait" and ev.get("arm") == "a") == pol_mod.MAX_WAIT_REOBSERVE
    assert not any(" load " in f" {c}" or c.endswith("run policy") for c in ca_ex.commands)

    # 4. Mid-chunk fault/contact captures actual stopped state into guard instead of pre-chunk pose; malformed state falls back safely.
    stopped_b = [44.0, -35.0, 38.0, 40.0, 0.0, 53.0]
    for mode, reply_extra in (
        ("contact", {"ok": False, "contact": True, "holding": True, "state": stopped_b}),
        ("fault", {"ok": False, "fault": "overload", "settled": False, "holding": True, "state": stopped_b}),
        ("unsettled", {"ok": True, "settled": False, "holding": True, "state": stopped_b}),
        ("bad_state", {"ok": False, "fault": "overload", "state": ["nan-str"]}),
    ):
        g_pose = guard_mod.TwoArmChunkGuard(kins, rigids, tips, margin_m=0.02, min_z_m=-0.05)
        ca_p, cb_p = FakeCell(home_a), FakeCell(home_b)
        orig_act_b = cb_p.act
        cb_p.act = lambda cmd, _ex=reply_extra, _o=orig_act_b: ({"command": cmd, **_ex} if cmd.endswith("run policy") else _o(cmd))
        res_p = pol_mod.run_two_arm_policy(
            {"a": ca_p, "b": cb_p}, {"a": _Shadow(lambda _i: [home_a] * 2), "b": _Shadow(lambda _i: [home_b] * 2)},
            libs, g_pose, task_a, task_b, tmp_path / f"pose_{mode}",
            max_chunks=1, dry_run=False, authorizers=auths,
        )
        assert res_p["result"] == ("fault" if "fault" in reply_extra else "refused")
        if mode == "bad_state":
            assert g_pose._arms["b"].pose == tuple(home_b)
        else:
            assert g_pose._arms["b"].pose == pytest.approx(tuple(stopped_b))
            assert g_pose._arms["b"].holding is True

    # 5. Single-arm parity released exit: holding True -> False with open gripper stops cleanly before max_chunks & CLI exits 0.
    ca_rel, cb_rel = FakeCell(home_a), FakeCell(home_b)

    class _ReleaseCell(FakeCell):
        def __init__(self, pose):
            super().__init__(pose)
            self._runs = 0

        def act(self, cmd):
            if cmd.endswith("run policy"):
                self._runs += 1
                self.commands.append(cmd)
                return {"ok": True, "settled": True, "holding": (self._runs == 1), "state": list(self.pose)}
            return super().act(cmd)

    ca_rel, cb_rel = _ReleaseCell(home_a), _ReleaseCell(home_b)
    rel_pose_a = [*home_a[:5], 60.0]
    rel_pose_b = [*home_b[:5], 60.0]
    res_rel = pol_mod.run_two_arm_policy(
        {"a": ca_rel, "b": cb_rel},
        {"a": _Shadow(lambda i: [home_a] * 2 if i == 0 else [rel_pose_a] * 3),
         "b": _Shadow(lambda i: [home_b] * 2 if i == 0 else [rel_pose_b] * 3)},
        libs, guard_mod.TwoArmChunkGuard(kins, rigids, tips, margin_m=0.02, min_z_m=-0.05),
        task_a, task_b, tmp_path / "released", max_chunks=4, dry_run=False, authorizers=auths,
    )
    assert res_rel["result"] == "released"
    assert res_rel["arms"]["a"]["outcome"] == "released" and res_rel["arms"]["a"]["chunks_done"] == 2
    assert res_rel["arms"]["b"]["outcome"] == "released" and res_rel["arms"]["b"]["chunks_done"] == 2

    srv_cli, url_cli, revs_cli = _make_remote_server(tmp_path / "srv_rel", {"arm_a": lambda _o: [home_a] * 2, "arm_b": lambda _o: [home_b] * 2})
    try:
        rdir = tmp_path / "cli_rel"
        rdir.mkdir()
        (rdir / "lib.json").write_text(json.dumps(_base_lib(home_a)), encoding="utf-8")
        (rdir / "plan.json").write_text((OMX / "grasp-plan.example.json").read_text(encoding="utf-8"), encoding="utf-8")
        jcal = {n: {"range_min": 0, "range_max": 4095, "homing_offset": 0, "drive_mode": 0} for n in remote_mod.JOINT_NAMES}
        (rdir / "jcal.json").write_text(json.dumps(jcal), encoding="utf-8")
        (rdir / "cal_a.json").write_text(json.dumps({"sites": {"belt": {"homography": [[0.001, 0, 0], [0, 0.001, -0.17], [0, 0, 1]]}}}), encoding="utf-8")
        (rdir / "cal_b.json").write_text(json.dumps({"sites": {"belt": {"homography": [[0.001, 0, 0], [0, 0.001, 0.17], [0, 0, 1]]}}}), encoding="utf-8")
        (rdir / "prof.json").write_text(json.dumps({"schema": "rosy.omx-cell-robot-profile.v1", "device_id": "d", "instance_id": "a", "robot_config_sha256": "a" * 64, "operating_envelope_path": "e.json", "work_dir": "."}), encoding="utf-8")
        for s_arm in ("a", "b"):
            (rdir / f"cfg_{s_arm}.json").write_text(json.dumps({"io": str(rdir), "cameras": {}, "operating_profile_path": str(rdir / "prof.json"), "calibration_path": str(rdir / f"cal_{s_arm}.json"), "plan_path": str(rdir / "plan.json")}), encoding="utf-8")
        monkeypatch.setattr(cli_mod.cell_two_arm, "open_cells", lambda *_a, **_kw: {"a": FakeCell(home_a), "b": FakeCell(home_b)})
        monkeypatch.setattr(cli_mod.cell_two_arm, "kinematics_for", lambda *_a, **_kw: kins)
        monkeypatch.setattr(cli_mod.cell_two_arm, "away_from_home", lambda *_a: [])
        monkeypatch.setattr(cli_mod.cell_policy_handoff, "Authorization", lambda _cfg: (lambda *_a: {"session_id": "s", "library_sha256": "e" * 64}))
        monkeypatch.setattr(cli_mod, "run_two_arm_policy", lambda *_a, **_kw: {"result": "released", "task_id": "T1_CONCURRENT_ZONE_SPLIT"})
        assert cli_mod.main([
            "--config-a", str(rdir / "cfg_a.json"), "--config-b", str(rdir / "cfg_b.json"),
            "--endpoint-url", url_cli, "--revision-a", revs_cli["arm_a"], "--revision-b", revs_cli["arm_b"],
            "--library-a", str(rdir / "lib.json"), "--library-b", str(rdir / "lib.json"),
            "--model-cal-a", str(rdir / "jcal.json"), "--cell-cal-a", str(rdir / "jcal.json"),
            "--model-cal-b", str(rdir / "jcal.json"), "--cell-cal-b", str(rdir / "jcal.json"),
            "--task-a", "belt->temp_a:r1-s1-t1", "--task-b", "temp_b:r1-s1-t1->temp_b:r2-s1-t1",
            "--work-dir", str(rdir / "out"), "--proposer", "alice", "--operator", "bob", "--commissioning", "--person-at-switch",
        ]) == 0
    finally:
        srv_cli.shutdown()
        srv_cli.server_close()


def test_pr2_cli_dry_run_passive_fallback_and_live_failure_bundle_emission(tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(ROOT / "contracts/foundation"))
    sys.path.insert(0, str(OMX))
    try:
        import cell_failure_context as cfc  # noqa: E402
        import cell_job_readiness as readiness_mod  # noqa: E402
        from core_common.protocol.cell_failure_context import CellFailureContext  # noqa: E402
    finally:
        for p in (str(OMX), str(ROOT / "contracts/foundation")):
            if p in sys.path:
                sys.path.remove(p)

    home = [0.0, -40.0, 40.0, 40.0, 0.0, 50.0]
    kins = {"a": PlanarKin(0.10), "b": PlanarKin(0.10)}
    srv_obj, url, revs = _make_remote_server(tmp_path / "srv", {"arm_a": lambda _o: [home] * 4, "arm_b": lambda _o: [home] * 4})
    bundle_root = tmp_path / "bundles"
    try:
        lib_p = tmp_path / "lib.json"
        lib_no_home = tmp_path / "lib_no_home.json"
        base_lib = _base_lib(home)
        lib_p.write_text(json.dumps(base_lib), encoding="utf-8")
        no_home_lib = {**base_lib, "chunks": {"reach": base_lib["chunks"]["reach"]}}
        lib_no_home.write_text(json.dumps(no_home_lib), encoding="utf-8")
        jcal = {n: {"range_min": 0, "range_max": 4095, "homing_offset": 0, "drive_mode": 0} for n in remote_mod.JOINT_NAMES}
        jcal_p = tmp_path / "jcal.json"
        jcal_p.write_text(json.dumps(jcal), encoding="utf-8")
        cal_a = tmp_path / "cal_a.json"
        cal_b = tmp_path / "cal_b.json"
        cal_a.write_text(json.dumps({"sites": {"belt": {"homography": [[0.001, 0, 0], [0, 0.001, -0.17], [0, 0, 1]]}}}), encoding="utf-8")
        cal_b.write_text(json.dumps({"sites": {"belt": {"homography": [[0.001, 0, 0], [0, 0.001, 0.17], [0, 0, 1]]}}}), encoding="utf-8")
        prof = tmp_path / "prof.json"
        prof.write_text(json.dumps({"schema": "rosy.omx-cell-robot-profile.v1", "device_id": "d", "instance_id": "a", "robot_config_sha256": "a" * 64, "operating_envelope_path": "e.json", "work_dir": "."}), encoding="utf-8")
        plan_p = tmp_path / "plan.json"
        plan_p.write_text((OMX / "grasp-plan.example.json").read_text(encoding="utf-8"), encoding="utf-8")
        cfg_a, cfg_b = tmp_path / "cfg_a.json", tmp_path / "cfg_b.json"
        for cfg_p, cal_p in ((cfg_a, cal_a), (cfg_b, cal_b)):
            cfg_p.write_text(json.dumps({
                "io": str(tmp_path), "cameras": {}, "failure_bundle_root": str(bundle_root),
                "operating_profile_path": str(prof), "calibration_path": str(cal_p), "plan_path": str(plan_p),
            }), encoding="utf-8")

        class _NoRunnerCell(FakeCell):
            def __init__(self):
                super().__init__(home, fault="no runner")

        monkeypatch.setattr(cli_mod.cell_two_arm, "kinematics_for", lambda *_a, **_kw: kins)
        monkeypatch.setattr(cli_mod.cell_two_arm, "away_from_home", lambda *_a: [])
        monkeypatch.setattr(cli_mod.cell_policy_handoff, "Authorization", lambda _cfg: (lambda *_a: {"session_id": "s", "library_sha256": "f" * 64}))

        # _PassiveDryRunCell wrapper fails closed on non-state act/checked and forwards frame_receipt cleanly.
        wrapped = cli_mod._PassiveDryRunCell(_NoRunnerCell(), home)
        assert wrapped.act("state")["passive_source"] == "library_home"
        assert wrapped.act("human-hold")["fault"] == "dry_run_passive_cell"
        assert wrapped.checked("run policy", {"session_id": "s", "library_sha256": "f" * 64})["fault"] == "dry_run_passive_cell"
        assert wrapped.frame_receipt("top")["camera"] == "top"

        common_args = [
            "--config-a", str(cfg_a), "--config-b", str(cfg_b), "--endpoint-url", url,
            "--revision-a", revs["arm_a"], "--revision-b", revs["arm_b"],
            "--task-a", "belt->temp_a:r1-s1-t1", "--task-b", "temp_b:r1-s1-t1->temp_b:r2-s1-t1",
            "--max-chunks", "1", "--proposer", "alice", "--operator", "bob",
        ]

        # 1. --dry-run succeeds passively when FifoCell reports fault='no runner'.
        monkeypatch.setattr(cli_mod.cell_two_arm, "open_cells", lambda *_a, **_kw: {"a": _NoRunnerCell(), "b": _NoRunnerCell()})
        capsys.readouterr()
        rc_dry = cli_mod.main([*common_args, "--library-a", str(lib_p), "--library-b", str(lib_p), "--work-dir", str(tmp_path / "w_dry"), "--dry-run"])
        assert rc_dry == 0
        out_dry = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        rec_dry = json.loads(Path(out_dry["receipt"]).read_text(encoding="utf-8"))
        assert out_dry["result"] == "dry_run" and out_dry["passive_dry_run_arms"] == ["a", "b"]
        assert rec_dry["passive_dry_run_arms"] == ["a", "b"] and "failure_bundle_id" not in rec_dry

        # 2. --dry-run fails closed if library has no valid chunks.home, and emits no failure bundle.
        rc_no_home = cli_mod.main([*common_args, "--library-a", str(lib_no_home), "--library-b", str(lib_p), "--work-dir", str(tmp_path / "w_nohome"), "--dry-run"])
        assert rc_no_home == 1
        assert not bundle_root.exists() or list(bundle_root.iterdir()) == []

        # 3. Live run NEVER enables passive fallback on no_runner (fails closed & emits failure bundle).
        live_args = [
            *common_args, "--library-a", str(lib_p), "--library-b", str(lib_p),
            "--model-cal-a", str(jcal_p), "--cell-cal-a", str(jcal_p),
            "--model-cal-b", str(jcal_p), "--cell-cal-b", str(jcal_p),
            "--commissioning", "--person-at-switch",
        ]
        capsys.readouterr()
        rc_live_nr = cli_mod.main([*live_args, "--work-dir", str(tmp_path / "w_livenr")])
        assert rc_live_nr == 1
        out_nr = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert out_nr["result"] == "fault" and "passive_dry_run_arms" not in out_nr and out_nr.get("failure_bundle_id")

        # 4. Live mid-run fault on arm_b emits D-1072 CellFailureContext bundle and surfaces failure_bundle_id via parse_structured_result.
        ca_live, cb_live = FakeCell(home), FakeCell(home)
        orig_cb = cb_live.act
        cb_live.act = lambda cmd: ({"ok": False, "fault": "overload", "settled": False, "state": list(home)} if cmd.endswith("run policy") else orig_cb(cmd))
        monkeypatch.setattr(cli_mod.cell_two_arm, "open_cells", lambda *_a, **_kw: {"a": ca_live, "b": cb_live})
        capsys.readouterr()
        rc_flt = cli_mod.main([*live_args, "--work-dir", str(tmp_path / "w_flt")])
        assert rc_flt == 1
        stdout_line = capsys.readouterr().out.strip().splitlines()[-1]
        out_flt = json.loads(stdout_line)
        rec_flt = json.loads(Path(out_flt["receipt"]).read_text(encoding="utf-8"))
        bid = out_flt["failure_bundle_id"]
        assert bid and rec_flt["failure_bundle_id"] == bid
        fake_log = tmp_path / "job.log"
        fake_log.write_text(("noise\n" * 50) + stdout_line + "\n", encoding="utf-8")
        _, parsed_bid = readiness_mod.parse_structured_result(fake_log)
        assert parsed_bid == bid
        bundle = cfc.load_bundle(bundle_root, bid)
        CellFailureContext.model_validate(bundle)
        assert bundle["arm_id"] == "arm_b" and bundle["cell_id"] == "cell_ab" and bundle["kind"] == "fault"
    finally:
        srv_obj.shutdown()
        srv_obj.server_close()


def test_remote_policy_jpeg_quality_validation_compression_and_cli(tmp_path, monkeypatch):
    import base64

    assert remote_mod.DEFAULT_JPEG_QUALITY == 85
    home = [0.0, -40.0, 40.0, 40.0, 0.0, 50.0]
    srv_obj, url, revs = _make_remote_server(
        tmp_path,
        {"arm_a": lambda _obs: [home] * 4, "arm_b": lambda _obs: [home] * 4},
    )
    try:
        sh85 = remote_mod.RemotePolicyShadow(url, "arm_a", revs["arm_a"])
        assert sh85.jpeg_quality == 85
        for bad in (True, False, 49, 101, 85.5, "85"):
            with pytest.raises(ValueError, match="jpeg_quality"):
                remote_mod.RemotePolicyShadow(url, "arm_a", revs["arm_a"], jpeg_quality=bad)

        rng = np.random.default_rng(7)
        textured = rng.integers(0, 256, size=(24, 32, 3), dtype=np.uint8)
        j85 = remote_mod._encode_jpeg_bgr(textured, (24, 32), quality=85)
        j95 = remote_mod._encode_jpeg_bgr(textured, (24, 32), quality=95)
        assert len(j85) < len(j95)

        sh95 = remote_mod.RemotePolicyShadow(url, "arm_a", revs["arm_a"], jpeg_quality=95)
        obs85, _ = sh85.inputs([0.0] * 6, {"top": textured, "wrist": textured})
        obs95, _ = sh95.inputs([0.0] * 6, {"top": textured, "wrist": textured})
        assert len(base64.b64decode(obs85["frames"]["top"])) < len(base64.b64decode(obs95["frames"]["top"]))

        lib_p, cfg_a, cfg_b, prof, plan_p = (
            tmp_path / "lib.json", tmp_path / "cfg_a.json", tmp_path / "cfg_b.json",
            tmp_path / "profile.json", tmp_path / "plan.json",
        )
        lib_p.write_text(json.dumps(_base_lib(home)), encoding="utf-8")
        prof.write_text(json.dumps({
            "schema": "rosy.omx-cell-robot-profile.v1", "device_id": "dev-1", "instance_id": "arm",
            "robot_config_sha256": "a" * 64, "operating_envelope_path": "rev.json", "work_dir": ".",
        }), encoding="utf-8")
        plan_p.write_text((OMX / "grasp-plan.example.json").read_text(encoding="utf-8"), encoding="utf-8")
        for cfg in (cfg_a, cfg_b):
            cfg.write_text(json.dumps({"io": str(tmp_path), "cameras": {}, "operating_profile_path": str(prof), "plan_path": str(plan_p)}), encoding="utf-8")

        base_args = [
            "--config-a", str(cfg_a), "--config-b", str(cfg_b), "--endpoint-url", url,
            "--revision-a", revs["arm_a"], "--revision-b", revs["arm_b"],
            "--library-a", str(lib_p), "--library-b", str(lib_p),
            "--task-a", "belt->temp_a:r1-s1-t1", "--task-b", "temp_b:r1-s1-t1->temp_b:r2-s1-t1",
            "--work-dir", str(tmp_path / "w"), "--max-chunks", "1", "--proposer", "alice", "--operator", "bob", "--dry-run",
        ]
        monkeypatch.setattr(cli_mod.cell_two_arm, "open_cells", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("must not open cells")))
        for bad_q in ("49", "101"):
            with pytest.raises(SystemExit, match="jpeg-quality"):
                cli_mod.main([*base_args, "--jpeg-quality", bad_q])

        seen_q = []
        orig_cls = remote_mod.RemotePolicyShadow

        def _spy_shadow(*a, **kw):
            inst = orig_cls(*a, **kw)
            seen_q.append((inst.arm_id, inst.jpeg_quality))
            return inst

        monkeypatch.setattr(cli_mod.cell_two_arm, "open_cells", lambda *_a, **_kw: {"a": FakeCell(home), "b": FakeCell(home)})
        monkeypatch.setattr(cli_mod.cell_two_arm, "kinematics_for", lambda *_a, **_kw: {"a": PlanarKin(0.10), "b": PlanarKin(0.10)})
        monkeypatch.setattr(cli_mod.cell_remote_policy, "RemotePolicyShadow", _spy_shadow)
        assert cli_mod.main([*base_args, "--jpeg-quality", "90"]) == 0
        assert seen_q == [("arm_a", 90), ("arm_b", 90)]
    finally:
        srv_obj.shutdown()
        srv_obj.server_close()
