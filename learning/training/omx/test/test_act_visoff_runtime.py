"""Host unit tests for `act_visoff_runtime.py` and its HTTP server integration (no torch/lerobot needed)."""
from __future__ import annotations

import ast
import base64
from hashlib import sha256
import json
import math
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

LEARN_OMX = Path(__file__).resolve().parents[1]
SERVER_PATH = LEARN_OMX / "act_policy_http_server.py"
RUNTIME_PATH = LEARN_OMX / "act_visoff_runtime.py"
sys.path.insert(0, str(LEARN_OMX))
try:
    import act_policy_http_server as srv  # noqa: E402
    import act_visoff_runtime as vrt  # noqa: E402
finally:
    sys.path.remove(str(LEARN_OMX))


def _arm_a_spec_dict(weights_sha: str, **overrides) -> dict:
    doc = {
        "schema": vrt.VISOFF_SCHEMA,
        "version": "v8",
        "weights": "visoff_v8_best.pt",
        "weights_sha256": weights_sha,
        "base_xyz": [0.077, -0.16465, 0.084],
        "yaw": math.pi / 2.0,
        "arm_yaw_nom": math.pi / 2.0,
        "tcp_xyz": [0.074, -0.0016, 0.0],
        "limits_low": [-2.6, -1.9543605529017618, -1.3, -0.3, -2.0],
        "limits_high": [2.6, 1.2, 1.7, 2.3, 2.0],
        "n_action_steps": 16,
        "lock_steps": [38, 40, 42, 44, 46, 48],
        "ramp_frames": 12,
        "max_dq_deg": 6.0,
        "cam_mode": "auto",
    }
    doc.update(overrides)
    return doc


def _make_bundle(root: Path, arm_id: str, *, visoff_doc: dict | None = None, weights_name: str = "visoff_v8_best.pt", chunk_size: int = 32):
    pdir = root / arm_id
    pdir.mkdir(parents=True, exist_ok=True)
    raw = f"act-weights-{arm_id}".encode("utf-8")
    (pdir / "model.safetensors").write_bytes(raw)
    rev = sha256(raw).hexdigest()
    cfg = {
        "type": "act",
        "n_action_steps": 4,
        "chunk_size": chunk_size,
        "input_features": {
            "observation.state": {"shape": [6]},
            "observation.environment_state": {"shape": [10]},
            "observation.images.top": {"shape": [3, 24, 32]},
            "observation.images.side": {"shape": [3, 24, 32]},
            "observation.images.wrist": {"shape": [3, 24, 32]},
        },
        "output_features": {"action": {"shape": [6]}},
    }
    (pdir / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    if visoff_doc is not None:
        wbytes = f"visoff-{arm_id}".encode("utf-8")
        (pdir / weights_name).write_bytes(wbytes)
        wsha = sha256(wbytes).hexdigest()
        doc = _arm_a_spec_dict(wsha, weights=weights_name, **visoff_doc)
        (pdir / vrt.VISOFF_SPEC_FILE).write_text(json.dumps(doc), encoding="utf-8")
    return pdir, rev


def _encode_b64_jpeg(h: int, w: int) -> str:
    img = np.full((h, w, 3), 42, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _http_json(url: str, *, method: str = "GET", body: dict | None = None, token: str | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_no_forbidden_top_level_imports():
    forbidden = {"torch", "lerobot", "mujoco", "deploy", "tools"}
    for path in (RUNTIME_PATH, SERVER_PATH):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            names = (
                [a.name.split(".")[0] for a in node.names]
                if isinstance(node, ast.Import)
                else ([node.module.split(".")[0]] if isinstance(node, ast.ImportFrom) and node.module else [])
            )
            assert not (forbidden & set(names)), f"{path.name}: forbidden top-level import {names}"


def test_read_visoff_spec_validation_and_fail_closed(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert vrt.read_visoff_spec(plain, chunk_size=16) is None

    pdir, _ = _make_bundle(tmp_path, "valid", visoff_doc={})
    spec = vrt.read_visoff_spec(pdir, chunk_size=32)
    assert spec is not None and spec["version"] == "v8" and spec["n_action_steps"] == 16

    for mut in (
        {"weights_sha256": "0" * 64},
        {"weights": "../outside.pt"},
        {"version": "v9"},
        {"schema": "wrong"},
        {"n_action_steps": 33},
        {"lock_steps": [48, 40]},
        {"cam_mode": "invalid"},
    ):
        bad_doc = {**json.loads((pdir / vrt.VISOFF_SPEC_FILE).read_text()), **mut}
        bad_dir = tmp_path / ("bad_" + "_".join(mut.keys()))
        bad_dir.mkdir(exist_ok=True)
        (bad_dir / "visoff_v8_best.pt").write_bytes((pdir / "visoff_v8_best.pt").read_bytes())
        (bad_dir / vrt.VISOFF_SPEC_FILE).write_text(json.dumps(bad_doc), encoding="utf-8")
        with pytest.raises(ValueError):
            vrt.read_visoff_spec(bad_dir, chunk_size=32)

    no_nom = json.loads((pdir / vrt.VISOFF_SPEC_FILE).read_text())
    no_nom.pop("arm_yaw_nom")
    bad_nom = tmp_path / "bad_nom"
    bad_nom.mkdir()
    (bad_nom / "visoff_v8_best.pt").write_bytes((pdir / "visoff_v8_best.pt").read_bytes())
    (bad_nom / vrt.VISOFF_SPEC_FILE).write_text(json.dumps(no_nom), encoding="utf-8")
    with pytest.raises(ValueError, match="arm_yaw_nom"):
        vrt.read_visoff_spec(bad_nom, chunk_size=32)


def test_ik_delta_se2_accuracy_both_arms(tmp_path):
    for arm_name, yaw, by, max_deg in (("arm_a", math.pi / 2.0, -0.16465, 6.0), ("arm_b", -math.pi / 2.0, 0.16765, 6.5)):
        nom = vrt.OmxNominalKinematics(
            [0.077, by, 0.084], yaw, [0.074, -0.0016, 0.0],
            [-2.6, -1.9543605529017618, -1.3, -0.3, -2.0],
            [2.6, 1.2, 1.7, 2.3, 2.0],
        )
        dx_m, dy_m, dyaw_r = 0.004, -0.004, math.radians(1.0)
        pert = vrt.OmxNominalKinematics(
            [0.077 + dx_m, by + dy_m, 0.084], yaw + dyaw_r, [0.074, -0.0016, 0.0],
            nom._limits_low, nom._limits_high,
        )
        q_test = np.array([0.0, -0.7, 0.7, math.pi / 2.0, 0.5], dtype=np.float64)
        p_nom, R_nom = nom._tcp_and_R(q_test)
        dq = vrt.ik_delta_se2(nom, q_test, -dx_m, -dy_m, -dyaw_r, math.radians(max_deg), iters=2)
        p_pert, R_pert = pert._tcp_and_R(q_test + dq)
        pos_err_mm = float(np.linalg.norm(p_pert - p_nom) * 1000.0)
        rot_err_deg = math.degrees(math.acos(float(np.clip((np.trace(R_pert @ R_nom.T) - 1.0) * 0.5, -1.0, 1.0))))
        assert pos_err_mm < 0.1 and rot_err_deg < 0.1, f"{arm_name} pos={pos_err_mm} rot={rot_err_deg}"


def test_episode_controller_lock_ramp_decouple_and_guards(tmp_path):
    pdir, _ = _make_bundle(tmp_path, "arm_a", visoff_doc={"episode_timeout_s": 5.0})
    spec = vrt.read_visoff_spec(pdir, chunk_size=32)
    kin = vrt.OmxNominalKinematics.from_spec(spec)
    now = [100.0]
    seen_states = []
    q_base = np.array([0.0, -1.2, 1.1, 1.6, 0.5, 0.0], dtype=np.float64)

    def base_predict(obs):
        seen_states.append(list(obs["state"]))
        return [q_base.tolist() for _ in range(32)]

    pred_state = {"agree": 1.0, "samples": [(5.0, -4.0, 1.5), (5.0, -4.0, 1.5)]}

    def fake_visoff(_frames, _q0):
        dx, dy, dw = pred_state["samples"].pop(0) if len(pred_state["samples"]) > 1 else pred_state["samples"][0]
        return {
            "fused": (dx, dy, dw),
            "top": (dx, dy, dw),
            "side": (dx, dy, dw),
            "wrist": (dx + pred_state["agree"], dy, dw),
            "agree_tw_mm": pred_state["agree"],
        }

    ctrl = vrt.VisoffEpisodeController(base_predict, fake_visoff, kin, spec, 16, clock=lambda: now[0])
    dummy_frames = {"top": np.zeros((24, 32, 3), np.uint8), "side": np.zeros((24, 32, 3), np.uint8), "wrist": np.zeros((24, 32, 3), np.uint8)}

    # step 0: preview returned, lock not frozen yet, zero IK offset applied
    c0, d0 = ctrl({"state": q_base.tolist(), "frames_rgb": dummy_frames, "episode_id": "ep1"})
    assert len(c0) == 16 and d0["locked"] is False and d0["preview_dxyw"] == [5.0, -4.0, 1.5]
    assert np.allclose(c0[0], q_base)

    # step 16: before lock_start=38
    c1, d1 = ctrl({"state": q_base.tolist(), "frames_rgb": dummy_frames, "episode_id": "ep1"})
    assert d1["step_idx"] == 16 and d1["locked"] is False

    # step 32: overlaps lock_start=38 (end=47 < 48), buffers first sample
    c2, d2 = ctrl({"state": q_base.tolist(), "frames_rgb": dummy_frames, "episode_id": "ep1"})
    assert d2["step_idx"] == 32 and d2["locked"] is False

    # step 48: reaches lock_end=48 -> freezes and ramps from frame 48 (1/12 .. 12/12)
    c3, d3 = ctrl({"state": q_base.tolist(), "frames_rgb": dummy_frames, "episode_id": "ep1"})
    assert d3["step_idx"] == 48 and d3["locked"] is True and d3["eff_dxyw"] == [5.0, -4.0, 1.5]
    assert not np.allclose(c3[0][:5], q_base[:5]) and np.allclose(c3[-1][:5] - q_base[:5], 12.0 * (c3[0][:5] - q_base[:5]), atol=1e-4)

    # step 64: raw state minus last_applied_dq is passed to base ACT
    last_dq = np.asarray(c3[-1][:5]) - q_base[:5]
    ctrl({"state": (q_base[:5] + last_dq).tolist() + [0.0], "frames_rgb": dummy_frames, "episode_id": "ep1"})
    assert np.allclose(seen_states[-1][:5], q_base[:5], atol=1e-6)

    # v8 auto wrist fallback + MAD abstain + timeout reset (preview@0 + 2 lock samples@32,48)
    pred_state["agree"] = 6.0
    pred_state["samples"] = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (8.0, 0.0, 0.0)]  # wrist diverges -> MAD=(3.5 > 1.8)
    for st in (0, 16, 32, 48):
        c_ab, d_ab = ctrl({"state": q_base.tolist(), "frames_rgb": dummy_frames, "episode_id": "ep2", "step_idx": st})
    assert d_ab["fallback_wrist"] is True and d_ab["abstained"] is True and d_ab["eff_dxyw"] == [0.0, 0.0, 0.0]

    # Timeout reset without episode_id
    ctrl({"state": q_base.tolist(), "frames_rgb": dummy_frames, "reset": True})
    now[0] += 6.0
    _, d_to = ctrl({"state": q_base.tolist(), "frames_rgb": dummy_frames})
    assert d_to["step_idx"] == 0 and d_to["locked"] is False


def test_http_server_with_visoff_controller_and_backward_compat(tmp_path):
    pdir, rev = _make_bundle(tmp_path, "arm_b", visoff_doc={
        "version": "v7",
        "arm_yaw_nom": None,
        "yaw": -math.pi / 2.0,
        "base_xyz": [0.077, 0.16765, 0.084],
        "n_action_steps": 8,
        "lock_steps": [4, 8],
        "ramp_frames": 4,
    }, weights_name="visoff_v7_best.pt", chunk_size=16)

    def make_base(_pdir, _views, n_steps, _goal_size, _dev):
        return lambda obs: [[0.0, -1.2, 1.1, 1.6, 0.5, 0.0] for _ in range(16)]

    def make_visoff(bundle_dir, spec, base_pred, n_steps, _dev):
        kin = vrt.OmxNominalKinematics.from_spec(spec)
        return vrt.VisoffEpisodeController(base_pred, lambda _f, _q0: {"fused": (0.2, 0.1, 0.1)}, kin, spec, n_steps)

    reg = srv.PolicyRegistry.from_specs([f"arm_b={pdir}:{rev}"], loader=make_base, visoff_builder=make_visoff)
    server = srv.make_server("127.0.0.1", 0, reg, token="tok")
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        st, h = _http_json(f"{base}/health")
        assert st == 200 and h["arms"]["arm_b"]["n_action_steps"] == 8
        assert h["arms"]["arm_b"]["visoff"]["version"] == "v7"

        jpg = _encode_b64_jpeg(24, 32)
        body = {
            "arm_id": "arm_b", "revision": rev, "state": [0.0] * 6,
            "frames": {"top": jpg, "side": jpg, "wrist": jpg}, "goal": [0.0] * 10,
            "episode_id": "e1", "step_idx": 0,
        }
        # Bad optional field types fail closed with 400
        assert _http_json(f"{base}/infer", method="POST", body={**body, "step_idx": True}, token="tok")[0] == 400
        assert _http_json(f"{base}/infer", method="POST", body={**body, "reset": "yes"}, token="tok")[0] == 400
        assert _http_json(f"{base}/infer", method="POST", body={**body, "episode_id": ""}, token="tok")[0] == 400

        c0, r0 = _http_json(f"{base}/infer", method="POST", body=body, token="tok")
        assert c0 == 200 and len(r0["chunk"]) == 8 and r0["visoff"]["locked"] is False and r0["visoff"]["preview_dxyw"] == [0.2, 0.1, 0.1]

        c1, r1 = _http_json(f"{base}/infer", method="POST", body={**body, "step_idx": 8}, token="tok")
        # Deadzone suppresses (0.2, 0.1, 0.1) -> eff_dxyw=[0,0,0]
        assert c1 == 200 and r1["visoff"]["locked"] is True and r1["visoff"]["eff_dxyw"] == [0.0, 0.0, 0.0]
    finally:
        server.shutdown()
        server.server_close()
