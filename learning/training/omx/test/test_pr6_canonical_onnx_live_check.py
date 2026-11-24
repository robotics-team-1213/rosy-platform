"""PR-6 test: canonical_workers.run_cell_live_check exports ONNX + OpenVINO parity into cell_live_check.json."""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "learning" / "training" / "omx"))
sys.path.insert(0, str(ROOT / "contracts" / "learning" / "src"))

import canonical_workers as cw  # noqa: E402
from rosy.contracts.learning.omx_canonical import default_canonical_spec  # noqa: E402


class _FakeTensor:
    def __init__(self, data):
        self.arr = np.asarray(data)

    @property
    def shape(self):
        return self.arr.shape

    def __len__(self):
        return len(self.arr)

    def __iter__(self):
        return iter(self.arr)

    def __getitem__(self, idx):
        return _FakeTensor(self.arr[idx])

    def __truediv__(self, other):
        return _FakeTensor(self.arr / other)

    def __array__(self, dtype=None):
        return self.arr if dtype is None else self.arr.astype(dtype)

    def permute(self, *axes):
        return _FakeTensor(np.transpose(self.arr, axes))

    def float(self):
        return _FakeTensor(self.arr.astype(np.float32))

    def detach(self):
        return self

    def cpu(self):
        return self

    def squeeze(self, *axes):
        return _FakeTensor(np.squeeze(self.arr, *axes) if axes else np.squeeze(self.arr))

    def reshape(self, *shape):
        return _FakeTensor(self.arr.reshape(*shape))

    def numpy(self):
        return self.arr

    def tolist(self):
        return self.arr.tolist()


def _install_fake_ml_modules(monkeypatch):
    class _FakePolicy:
        config = SimpleNamespace(
            input_features={"observation.state": (6,), "observation.images.top": (3, 8, 8)},
            n_action_steps=1,
        )

        def to(self, _d):
            return self

        def eval(self):
            return self

        def reset(self):
            pass

        def select_action(self, _b):
            return _FakeTensor(np.zeros((1, 6), dtype=np.float32))

    class _ACTPolicy:
        @classmethod
        def from_pretrained(cls, *_a, **_k):
            return _FakePolicy()

    fake_cv2 = ModuleType("cv2")
    fake_cv2.COLOR_BGR2RGB = 4
    fake_cv2.imread = lambda p: np.full((8, 8, 3), 120, np.uint8) if Path(p).exists() else None
    fake_cv2.cvtColor = lambda img, _code: img[..., ::-1].copy()

    fake_torch = ModuleType("torch")
    fake_torch.float32 = np.float32
    fake_torch.from_numpy = lambda a: _FakeTensor(a)
    fake_torch.tensor = lambda a, dtype=None: _FakeTensor(a)
    fake_torch.zeros = lambda shape, dtype=None: _FakeTensor(np.zeros(shape, dtype=dtype or np.float32))
    fake_torch.inference_mode = contextlib.nullcontext
    fake_torch.no_grad = contextlib.nullcontext
    fake_torch.nn = SimpleNamespace(
        functional=SimpleNamespace(
            one_hot=lambda idx, n: _FakeTensor(np.eye(n, dtype=np.float32)[np.asarray(idx)])
        )
    )

    lerobot_mod = ModuleType("lerobot")
    policies_mod = ModuleType("lerobot.policies")
    act_pkg = ModuleType("lerobot.policies.act")
    act_mod = ModuleType("lerobot.policies.act.modeling_act")
    act_mod.ACTPolicy = _ACTPolicy
    fac_mod = ModuleType("lerobot.policies.factory")
    fac_mod.make_pre_post_processors = lambda *_a, **_k: (lambda b: b, lambda a: a)

    for name, mod in (
        ("cv2", fake_cv2),
        ("torch", fake_torch),
        ("lerobot", lerobot_mod),
        ("lerobot.policies", policies_mod),
        ("lerobot.policies.act", act_pkg),
        ("lerobot.policies.act.modeling_act", act_mod),
        ("lerobot.policies.factory", fac_mod),
    ):
        monkeypatch.setitem(sys.modules, name, mod)


def test_run_cell_live_check_exports_onnx_meta_and_propagates_failure(tmp_path: Path, monkeypatch):
    import experiment_artifact as ea

    _install_fake_ml_modules(monkeypatch)

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
        (frames_dir / f"cell-live-{role}.jpg").write_bytes(b"jpg")

    lib = tmp_path / "env.json"
    lib.write_text(json.dumps({"chunks": {"home": [[0.0] * 6], "site_a": [[0.0] * 6]}}), encoding="utf-8")

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
