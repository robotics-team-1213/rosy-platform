"""PR-6 test: canonical_workers.run_cell_live_check exports ONNX + OpenVINO parity into cell_live_check.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "learning" / "training" / "omx"))
sys.path.insert(0, str(ROOT / "contracts" / "learning" / "src"))

import canonical_workers as cw  # noqa: E402
from rosy.contracts.learning.omx_canonical import default_canonical_spec  # noqa: E402


def test_run_cell_live_check_exports_onnx_meta_and_propagates_failure(tmp_path: Path, monkeypatch):
    import experiment_artifact as ea
    import lerobot.policies.act.modeling_act as act_mod
    import lerobot.policies.factory as fac_mod

    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    (ckpt / "config.json").write_text(json.dumps({
        "type": "act", "n_action_steps": 1,
        "input_features": {"observation.state": {"shape": [6]}, "observation.images.rs": {"shape": [3, 8, 8]}},
        "output_features": {"action": {"shape": [6]}},
    }), encoding="utf-8")
    (ckpt / "model.safetensors").write_bytes(b"weights")
    (ckpt / "policy_preprocessor.json").write_text("{}", encoding="utf-8")
    (ckpt / "policy_postprocessor.json").write_text("{}", encoding="utf-8")

    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    for role in ("top", "side", "wrist"):
        cv2.imwrite(str(frames_dir / f"cell-live-{role}.jpg"), np.full((8, 8, 3), 120, np.uint8))

    lib = tmp_path / "env.json"
    lib.write_text(json.dumps({"chunks": {"home": [[0.0] * 6], "site_a": [[0.0] * 6]}}), encoding="utf-8")

    class _FakePolicy:
        config = type("C", (), {"input_features": {"observation.state": (6,), "observation.images.top": (3, 8, 8)}, "n_action_steps": 1})()
        def to(self, _d): return self
        def eval(self): return self
        def reset(self): pass
        def select_action(self, _b): return torch.zeros((1, 6), dtype=torch.float32)

    monkeypatch.setattr(act_mod.ACTPolicy, "from_pretrained", classmethod(lambda cls, *_a, **_k: _FakePolicy()))
    monkeypatch.setattr(fac_mod, "make_pre_post_processors", lambda *_a, **_k: (lambda b: b, lambda a: a))
    onnx_calls = []
    monkeypatch.setattr(ea, "export_cell_onnx", lambda bdir: onnx_calls.append(Path(bdir)) or {
        "schema": "rosy.omx-onnx-export.v1", "onnx_sha256": "c" * 64, "openvino_parity_max_abs_diff": 1e-6,
    })

    spec = default_canonical_spec()
    req = {"kind": "cell_live_check", "arm_id": "arm_a", "spec": spec, "spec_sha256": "d" * 64,
           "params": {"checkpoint_dir": str(ckpt), "frames_dir": str(frames_dir), "envelope_path": str(lib)}}
    out_dir = tmp_path / "out1"
    out_dir.mkdir()
    res = cw.run_cell_live_check(req, out_dir)
    assert len(onnx_calls) == 1 and res["onnx_export"]["openvino_parity_max_abs_diff"] == 1e-6
    written = json.loads((out_dir / "cell_live_check.json").read_text(encoding="utf-8"))
    assert written["onnx_export"]["onnx_sha256"] == "c" * 64

    monkeypatch.setattr(ea, "export_cell_onnx", lambda _b: (_ for _ in ()).throw(ValueError("OpenVINO parity exceeded")))
    out_fail = tmp_path / "out2"
    out_fail.mkdir()
    try:
        cw.run_cell_live_check(req, out_fail)
        raise AssertionError("expected ValueError on parity failure")
    except ValueError as exc:
        assert "parity" in str(exc)
