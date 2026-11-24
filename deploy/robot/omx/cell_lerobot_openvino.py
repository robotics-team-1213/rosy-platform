"""Pure-NumPy normalization and OpenVINO CPU runtime helpers for cell OMX ACT bundles."""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import numpy as np

WEIGHTS = "model.safetensors"
ONNX_MODEL = "model.onnx"
ONNX_META = "ONNX_EXPORT.json"
ONNX_SCHEMA = "rosy.omx-onnx-export.v1"

_PRE_ALLOWED = frozenset({
    "rename_observations_processor",
    "to_batch_processor",
    "device_processor",
    "normalizer_processor",
})
_POST_ALLOWED = frozenset({"unnormalizer_processor", "device_processor"})
_NORM_MODES = frozenset({"IDENTITY", "MEAN_STD", "MIN_MAX", "QUANTILES", "QUANTILE10"})


def _weights_sha256(root: Path) -> str:
    weights = root / WEIGHTS
    if weights.is_symlink() or not weights.is_file():
        raise ValueError(f"{WEIGHTS} must be a regular file")
    with weights.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _apply_norm(arr: np.ndarray, stats: dict[str, np.ndarray], key: str, mode: str, eps: float, *, inverse: bool) -> np.ndarray:
    if mode == "IDENTITY":
        return arr
    if mode not in _NORM_MODES:
        raise ValueError(f"unsupported normalization mode {mode!r} for {key}")
    eps32 = np.float32(eps)
    if mode == "MEAN_STD":
        mean, std = stats[f"{key}.mean"].astype(np.float32), stats[f"{key}.std"].astype(np.float32)
        return (arr * std + mean) if inverse else ((arr - mean) / (std + eps32))
    lo_k, hi_k = {"MIN_MAX": ("min", "max"), "QUANTILES": ("q01", "q99"), "QUANTILE10": ("q10", "q90")}[mode]
    lo, hi = stats[f"{key}.{lo_k}"].astype(np.float32), stats[f"{key}.{hi_k}"].astype(np.float32)
    denom = hi - lo
    denom = np.where(denom == 0, eps32, denom)
    if inverse:
        return (arr + np.float32(1.0)) * np.float32(0.5) * denom + lo
    return np.float32(2.0) * (arr - lo) / denom - np.float32(1.0)


def _load_step_tensors(root: Path, state_file: str | None) -> dict[str, np.ndarray]:
    if not state_file:
        raise ValueError("normalizer step is missing state_file")
    path = root / state_file
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"processor state_file must be a regular file inside the checkpoint: {state_file}")
    from safetensors.numpy import load_file

    return {k: np.asarray(v, dtype=np.float32) for k, v in load_file(str(path)).items()}


def load_numpy_norm(root: Path, *, action_width: int = 6):
    """Build pure-NumPy pre/post processors matching LeRobot's _NormalizationMixin without importing torch."""
    pre_path = root / "policy_preprocessor.json"
    post_path = root / "policy_postprocessor.json"
    for p in (pre_path, post_path):
        if p.is_symlink() or not p.is_file():
            raise ValueError(f"processor config {p.name} must be a regular file")
    pre_steps = json.loads(pre_path.read_text(encoding="utf-8")).get("steps") or []
    post_steps = json.loads(post_path.read_text(encoding="utf-8")).get("steps") or []

    norm_step = None
    for step in pre_steps:
        name = step.get("registry_name")
        if name not in _PRE_ALLOWED:
            raise ValueError(f"unsupported preprocessor step for pure-NumPy backend: {name!r}")
        if name == "rename_observations_processor" and (step.get("config") or {}).get("rename_map"):
            raise ValueError("non-empty rename_map is not supported by pure-NumPy backend")
        if name == "device_processor" and (step.get("config") or {}).get("float_dtype") not in (None, "float32"):
            raise ValueError("device_processor float_dtype is not supported by pure-NumPy backend")
        if name == "normalizer_processor":
            if norm_step is not None:
                raise ValueError("duplicate normalizer_processor in policy_preprocessor.json")
            norm_step = step
    if norm_step is None:
        raise ValueError("policy_preprocessor.json missing normalizer_processor")

    unnorm_step = None
    for step in post_steps:
        name = step.get("registry_name")
        if name not in _POST_ALLOWED:
            raise ValueError(f"unsupported postprocessor step for pure-NumPy backend: {name!r}")
        if name == "device_processor" and (step.get("config") or {}).get("float_dtype") not in (None, "float32"):
            raise ValueError("device_processor float_dtype is not supported by pure-NumPy backend")
        if name == "unnormalizer_processor":
            if unnorm_step is not None:
                raise ValueError("duplicate unnormalizer_processor in policy_postprocessor.json")
            unnorm_step = step
    if unnorm_step is None:
        raise ValueError("policy_postprocessor.json missing unnormalizer_processor")

    pre_cfg = norm_step.get("config") or {}
    if pre_cfg.get("normalize_observation_keys") is not None:
        raise ValueError("normalize_observation_keys is not supported by pure-NumPy backend")
    pre_features = pre_cfg.get("features") or {}
    pre_norm_map = pre_cfg.get("norm_map") or {}
    pre_eps = float(pre_cfg.get("eps", 1e-8))
    pre_stats = _load_step_tensors(root, norm_step.get("state_file"))

    post_cfg = unnorm_step.get("config") or {}
    post_norm_map = post_cfg.get("norm_map") or {}
    post_eps = float(post_cfg.get("eps", 1e-8))
    post_stats = _load_step_tensors(root, unnorm_step.get("state_file"))
    action_mode = post_norm_map.get("ACTION", "IDENTITY")

    def pre(obs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        batch = {}
        for key, value in obs.items():
            arr = np.asarray(value, dtype=np.float32)
            spec = pre_features.get(key) or {}
            shape = tuple(spec.get("shape") or ())
            if shape:
                if arr.shape == shape:
                    arr = arr[np.newaxis, ...]
                elif arr.ndim != len(shape) + 1 or arr.shape[1:] != shape:
                    raise ValueError(f"{key} shape {arr.shape} differs from expected {shape}")
            mode = pre_norm_map.get(spec.get("type", ""), "IDENTITY")
            batch[key] = np.ascontiguousarray(
                _apply_norm(arr, pre_stats, key, mode, pre_eps, inverse=False), dtype=np.float32
            )
        return batch

    def post(action: np.ndarray) -> np.ndarray:
        arr = np.asarray(action, dtype=np.float32)
        if arr.ndim < 2 or arr.shape[-1] != action_width:
            raise ValueError(f"ONNX action output shape {arr.shape} incompatible with expected width {action_width}")
        arr = _apply_norm(arr, post_stats, "action", action_mode, post_eps, inverse=True)
        return np.asarray(arr, dtype=np.float64).reshape(-1, action_width)

    return pre, post


def validate_onnx_export(root: Path, policy_revision: str | None = None, *, onnx_sha256: str | None = None) -> dict:
    """Validate model.onnx + ONNX_EXPORT.json integrity, revision pin, and feature schema."""
    import cell_lerobot_shadow as shadow

    onnx_path = root / ONNX_MODEL
    meta_path = root / ONNX_META
    for p in (onnx_path, meta_path):
        if p.is_symlink() or not p.is_file():
            raise ValueError(f"ONNX export requires regular file {p.name}")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("schema") != ONNX_SCHEMA:
        raise ValueError(f"{ONNX_META} schema {meta.get('schema')!r} != {ONNX_SCHEMA!r}")

    revision = policy_revision if policy_revision is not None else _weights_sha256(root)
    if meta.get("policy_revision") != revision:
        raise ValueError(f"{ONNX_META} policy_revision differs from pinned weights revision {revision}")

    if onnx_sha256 is not None:
        actual_onnx_sha = onnx_sha256
    else:
        with onnx_path.open("rb") as stream:
            actual_onnx_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    if meta.get("onnx_sha256") != actual_onnx_sha:
        raise ValueError(f"{ONNX_MODEL} sha256 {actual_onnx_sha} differs from {ONNX_META}")

    cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
    views, action_dim, goal_size = shadow.read_features(cfg)
    expected_shapes = {"observation.state": [1, action_dim]}
    for view, (height, width) in views.items():
        expected_shapes[shadow.IMAGE_PREFIX + view] = [1, 3, height, width]
    if goal_size is not None:
        expected_shapes[shadow.GOAL] = [1, goal_size]
    recorded_inputs = meta.get("inputs") or {}
    if set(recorded_inputs) != set(expected_shapes) or any(
        recorded_inputs.get(k) != shape for k, shape in expected_shapes.items()
    ):
        raise ValueError(f"{ONNX_META} inputs {recorded_inputs} differ from config {expected_shapes}")
    if meta.get("output_name") != "action":
        raise ValueError(f"{ONNX_META} output_name must be 'action'")
    return meta


def load_openvino(root: Path, policy_revision: str | None = None, *, onnx_sha256: str | None = None,
                  num_threads: int = 4, action_width: int = 6):
    """Pure-NumPy pre/post + OpenVINO CPU backend (never imports torch)."""
    meta = validate_onnx_export(root, policy_revision, onnx_sha256=onnx_sha256)
    pre, post = load_numpy_norm(root, action_width=action_width)
    import openvino as ov

    core = ov.Core()
    compiled = core.compile_model(
        str(root / ONNX_MODEL),
        "CPU",
        {"PERFORMANCE_HINT": "LATENCY", "INFERENCE_NUM_THREADS": int(num_threads)},
    )
    if len(compiled.outputs) != 1:
        raise ValueError(f"compiled OpenVINO model must have exactly 1 output, got {len(compiled.outputs)}")
    compiled_inputs = {inp.any_name for inp in compiled.inputs}
    expected_inputs = set(meta["inputs"])
    if compiled_inputs != expected_inputs:
        raise ValueError(f"compiled OpenVINO inputs {sorted(compiled_inputs)} differ from {sorted(expected_inputs)}")
    request = compiled.create_infer_request()
    output_port = compiled.output(0)
    lock = threading.Lock()
    ordered_inputs = tuple(meta["inputs"])

    def predict(obs: dict) -> np.ndarray:
        batch = pre(obs)
        feed = {name: np.ascontiguousarray(batch[name], dtype=np.float32) for name in ordered_inputs}
        with lock:
            request.infer(feed)
            out = request.get_output_tensor(output_port.get_index()).data.copy()
        return post(out)

    return predict
