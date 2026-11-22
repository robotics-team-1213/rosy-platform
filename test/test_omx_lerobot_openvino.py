"""Tests for pure-NumPy normalization, ONNX integrity validation, and OpenVINO routing."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_lerobot_openvino as ov_backend  # noqa: E402
import cell_lerobot_shadow as lrs  # noqa: E402

pytest.importorskip("cv2")

CONFIG = {
    "type": "act",
    "input_features": {
        "observation.state": {"type": "STATE", "shape": [6]},
        "observation.images.top": {"type": "VISUAL", "shape": [3, 8, 12]},
        "observation.images.wrist": {"type": "VISUAL", "shape": [3, 8, 12]},
    },
    "output_features": {"action": {"type": "ACTION", "shape": [6]}},
}


def _ckpt(tmp_path: Path, *, config=CONFIG):
    root = tmp_path / "ckpt"
    root.mkdir()
    (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (root / "model.safetensors").write_bytes(b"weights")
    return root, hashlib.sha256(b"weights").hexdigest()


def _bgr(value=(10, 20, 30)):
    return np.tile(np.asarray(value, dtype=np.uint8), (8, 12, 1))


def _write_norm_processors(root: Path, monkeypatch, *, extra_pre=None, rename_map=None):
    fake_tensors = {
        "policy_preprocessor_step_3_normalizer_processor.safetensors": {
            "observation.state.mean": np.array([1.0, -1.0, 0.5, 0.0, 2.0, -0.5], dtype=np.float32),
            "observation.state.std": np.array([2.0, 4.0, 0.5, 1.0, 2.0, 0.25], dtype=np.float32),
            "observation.images.top.mean": np.array([[[0.485]], [[0.456]], [[0.406]]], dtype=np.float32),
            "observation.images.top.std": np.array([[[0.229]], [[0.224]], [[0.225]]], dtype=np.float32),
            "observation.images.wrist.mean": np.array([[[0.5]], [[0.5]], [[0.5]]], dtype=np.float32),
            "observation.images.wrist.std": np.array([[[0.25]], [[0.25]], [[0.25]]], dtype=np.float32),
        },
        "policy_postprocessor_step_0_unnormalizer_processor.safetensors": {
            "action.mean": np.array([0.2, -0.4, 0.1, 0.0, 1.5, 0.5], dtype=np.float32),
            "action.std": np.array([0.5, 2.0, 1.0, 0.25, 0.5, 0.2], dtype=np.float32),
        },
    }
    for fname in fake_tensors:
        (root / fname).write_bytes(b"stub-sf")
    pre_steps = [
        {"registry_name": "rename_observations_processor", "config": {"rename_map": rename_map or {}}},
        {"registry_name": "to_batch_processor", "config": {}},
        {"registry_name": "device_processor", "config": {"device": "cpu"}},
        {
            "registry_name": "normalizer_processor",
            "config": {
                "eps": 1e-8,
                "features": {
                    "observation.state": {"type": "STATE", "shape": [6]},
                    "observation.environment_state": {"type": "ENV", "shape": [10]},
                    "observation.images.top": {"type": "VISUAL", "shape": [3, 8, 12]},
                    "observation.images.wrist": {"type": "VISUAL", "shape": [3, 8, 12]},
                },
                "norm_map": {"VISUAL": "MEAN_STD", "STATE": "MEAN_STD", "ACTION": "MEAN_STD"},
            },
            "state_file": "policy_preprocessor_step_3_normalizer_processor.safetensors",
        },
    ]
    if extra_pre:
        pre_steps.insert(1, extra_pre)
    (root / "policy_preprocessor.json").write_text(json.dumps({"steps": pre_steps}), encoding="utf-8")
    (root / "policy_postprocessor.json").write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "registry_name": "unnormalizer_processor",
                        "config": {"eps": 1e-8, "norm_map": {"ACTION": "MEAN_STD"}},
                        "state_file": "policy_postprocessor_step_0_unnormalizer_processor.safetensors",
                    },
                    {"registry_name": "device_processor", "config": {"device": "cpu"}},
                ]
            }
        ),
        encoding="utf-8",
    )

    fake_sf = type("_FakeSfNumpy", (), {"load_file": staticmethod(lambda p: fake_tensors[Path(p).name])})()
    monkeypatch.setitem(sys.modules, "safetensors", type("_FakeSfPkg", (), {"numpy": fake_sf})())
    monkeypatch.setitem(sys.modules, "safetensors.numpy", fake_sf)
    return fake_tensors


def test_numpy_norm_roundtrip_and_guards(tmp_path, monkeypatch):
    root, _ = _ckpt(
        tmp_path,
        config={**CONFIG, "input_features": {**CONFIG["input_features"], lrs.GOAL: {"shape": [10]}}},
    )
    tensors = _write_norm_processors(root, monkeypatch)
    pre, post = ov_backend.load_numpy_norm(root)
    obs = {
        "observation.state": np.array([3.0, 7.0, 1.0, -2.0, 0.0, 0.0], dtype=np.float32),
        "observation.environment_state": np.eye(10, dtype=np.float32)[4],
        "observation.images.top": np.full((3, 8, 12), 0.5, dtype=np.float32),
        "observation.images.wrist": np.full((3, 8, 12), 0.25, dtype=np.float32),
    }
    norm = pre(obs)
    assert norm["observation.state"].shape == (1, 6)
    st_t = tensors["policy_preprocessor_step_3_normalizer_processor.safetensors"]
    expected_state = (obs["observation.state"] - st_t["observation.state.mean"]) / (
        st_t["observation.state.std"] + np.float32(1e-8)
    )
    np.testing.assert_allclose(norm["observation.state"][0], expected_state, rtol=1e-6, atol=1e-6)
    np.testing.assert_array_equal(norm["observation.environment_state"], obs["observation.environment_state"][None, :])
    np.testing.assert_allclose(norm["observation.images.wrist"], -1.0, rtol=1e-5, atol=1e-5)

    unnorm = post(np.ones((1, 4, 6), dtype=np.float32))
    expected_action = np.array([0.7, 1.6, 1.1, 0.25, 2.0, 0.7], dtype=np.float64)
    assert unnorm.shape == (4, 6) and unnorm.dtype == np.float64
    np.testing.assert_allclose(unnorm[0], expected_action, rtol=1e-6, atol=1e-6)

    _write_norm_processors(root, monkeypatch, rename_map={"a": "b"})
    with pytest.raises(ValueError, match="rename_map"):
        ov_backend.load_numpy_norm(root)

    _write_norm_processors(root, monkeypatch, extra_pre={"registry_name": "custom_crop_processor", "config": {}})
    with pytest.raises(ValueError, match="unsupported preprocessor step"):
        ov_backend.load_numpy_norm(root)


def test_validate_onnx_export_checks_revision_sha_and_inputs(tmp_path):
    root, sha = _ckpt(tmp_path)
    onnx_bytes = b"fake-onnx-model"
    (root / lrs.ONNX_MODEL).write_bytes(onnx_bytes)
    onnx_sha = hashlib.sha256(onnx_bytes).hexdigest()
    meta = {
        "schema": ov_backend.ONNX_SCHEMA,
        "policy_revision": sha,
        "onnx_sha256": onnx_sha,
        "opset": 17,
        "inputs": {
            "observation.state": [1, 6],
            "observation.images.top": [1, 3, 8, 12],
            "observation.images.wrist": [1, 3, 8, 12],
        },
        "output_name": "action",
    }
    (root / lrs.ONNX_META).write_text(json.dumps(meta), encoding="utf-8")
    assert ov_backend.validate_onnx_export(root, sha)["onnx_sha256"] == onnx_sha

    with pytest.raises(ValueError, match="policy_revision differs"):
        ov_backend.validate_onnx_export(root, "f" * 64)

    (root / lrs.ONNX_MODEL).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="sha256"):
        ov_backend.validate_onnx_export(root, sha)

    (root / lrs.ONNX_MODEL).write_bytes(onnx_bytes)
    bad_inputs = {**meta, "inputs": {"observation.state": [1, 6]}}
    (root / lrs.ONNX_META).write_text(json.dumps(bad_inputs), encoding="utf-8")
    with pytest.raises(ValueError, match="inputs"):
        ov_backend.validate_onnx_export(root, sha)


def test_load_lerobot_backend_routing_and_pure_numpy_openvino_mock(tmp_path, monkeypatch):
    root, sha = _ckpt(tmp_path)
    _write_norm_processors(root, monkeypatch)
    onnx_bytes = b"onnx-graph"
    (root / lrs.ONNX_MODEL).write_bytes(onnx_bytes)
    meta = {
        "schema": ov_backend.ONNX_SCHEMA,
        "policy_revision": sha,
        "onnx_sha256": hashlib.sha256(onnx_bytes).hexdigest(),
        "opset": 17,
        "inputs": {
            "observation.state": [1, 6],
            "observation.images.top": [1, 3, 8, 12],
            "observation.images.wrist": [1, 3, 8, 12],
        },
        "output_name": "action",
    }
    (root / lrs.ONNX_META).write_text(json.dumps(meta), encoding="utf-8")

    class _FakeOutPort:
        def get_index(self):
            return 0

    class _FakeReq:
        def __init__(self):
            self.feeds = []

        def infer(self, feed):
            self.feeds.append(feed)

        def get_output_tensor(self, idx):
            assert idx == 0
            return type("_Tensor", (), {"data": np.zeros((1, 2, 6), dtype=np.float32)})()

    req = _FakeReq()

    class _FakeCompiled:
        inputs = [type("_In", (), {"any_name": k})() for k in meta["inputs"]]
        outputs = [_FakeOutPort()]

        def output(self, idx):
            assert idx == 0
            return _FakeOutPort()

        def create_infer_request(self):
            return req

    class _FakeCore:
        def compile_model(self, model_path, device, config):
            assert device == "CPU" and config["PERFORMANCE_HINT"] == "LATENCY" and config["INFERENCE_NUM_THREADS"] == 4
            return _FakeCompiled()

    monkeypatch.setitem(sys.modules, "openvino", type("_FakeOV", (), {"Core": _FakeCore})())
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.delenv("ROSY_ACT_BACKEND", raising=False)

    sh = lrs.LeRobotShadow(root, sha, device="cpu")
    frames = {v: _bgr() for v in sh.image_views}
    obs, _ = sh.inputs([0.0] * 6, frames)
    res = sh.infer(obs)
    assert len(res.chunk) == 2 and len(req.feeds) == 1
    assert "torch" not in sys.modules

    monkeypatch.setenv("ROSY_ACT_BACKEND", "openvino")
    with pytest.raises(ValueError, match="requires device='cpu'"):
        lrs.LeRobotShadow(root, sha, device="cuda")

    monkeypatch.setenv("ROSY_ACT_BACKEND", "invalid")
    with pytest.raises(ValueError, match="ROSY_ACT_BACKEND"):
        lrs._load_lerobot(root, "cpu")

    # Auto mode refuses corrupt/stale ONNX rather than silently falling back to PyTorch
    monkeypatch.setenv("ROSY_ACT_BACKEND", "auto")
    (root / lrs.ONNX_MODEL).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="sha256"):
        lrs.LeRobotShadow(root, sha, device="cpu")


def test_openvino_and_norm_additional_guards(tmp_path, monkeypatch):
    root, sha = _ckpt(tmp_path)
    _write_norm_processors(root, monkeypatch)

    # Unsupported float_dtype rejected
    pre_doc = json.loads((root / "policy_preprocessor.json").read_text(encoding="utf-8"))
    pre_doc["steps"][2]["config"]["float_dtype"] = "float16"
    (root / "policy_preprocessor.json").write_text(json.dumps(pre_doc), encoding="utf-8")
    with pytest.raises(ValueError, match="float_dtype"):
        ov_backend.load_numpy_norm(root)

    # Selective normalize_observation_keys rejected
    _write_norm_processors(root, monkeypatch)
    pre_doc = json.loads((root / "policy_preprocessor.json").read_text(encoding="utf-8"))
    pre_doc["steps"][3]["config"]["normalize_observation_keys"] = ["observation.state"]
    (root / "policy_preprocessor.json").write_text(json.dumps(pre_doc), encoding="utf-8")
    with pytest.raises(ValueError, match="normalize_observation_keys"):
        ov_backend.load_numpy_norm(root)

    # Wrong action width rejected by postprocessor
    _write_norm_processors(root, monkeypatch)
    _, post = ov_backend.load_numpy_norm(root)
    with pytest.raises(ValueError, match="incompatible with expected width 6"):
        post(np.zeros((1, 2, 5), dtype=np.float32))

    # Wrong recorded ONNX input shape rejected
    onnx_bytes = b"onnx-graph"
    (root / lrs.ONNX_MODEL).write_bytes(onnx_bytes)
    bad_shape_meta = {
        "schema": ov_backend.ONNX_SCHEMA,
        "policy_revision": sha,
        "onnx_sha256": hashlib.sha256(onnx_bytes).hexdigest(),
        "opset": 17,
        "inputs": {
            "observation.state": [1, 6],
            "observation.images.top": [1, 3, 9, 12],
            "observation.images.wrist": [1, 3, 8, 12],
        },
        "output_name": "action",
    }
    (root / lrs.ONNX_META).write_text(json.dumps(bad_shape_meta), encoding="utf-8")
    with pytest.raises(ValueError, match="inputs"):
        ov_backend.validate_onnx_export(root, sha)

    # Symlinked ONNX_EXPORT.json fails closed under auto mode even without reading PyTorch
    orig_is_symlink = Path.is_symlink
    meta_path = (root / lrs.ONNX_META).resolve()
    monkeypatch.setattr(Path, "is_symlink", lambda self: True if self.resolve(strict=False) == meta_path else orig_is_symlink(self))
    monkeypatch.setitem(sys.modules, "openvino", type("_FakeOV", (), {})())
    monkeypatch.setenv("ROSY_ACT_BACKEND", "auto")
    with pytest.raises(ValueError, match="regular file"):
        lrs._load_lerobot(root, "cpu")

