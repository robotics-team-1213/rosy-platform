#!/usr/bin/env python3
"""Shadow binding for a single-arm LeRobot ACT checkpoint.

The checkpoint folder is used as LeRobot wrote it (config.json, model.safetensors, policy_pre/postprocessor*), pinned by
the sha256 of model.safetensors: `act_shadow` = {"kind": "lerobot", "policy_root", "policy_revision": <that sha256>}.
Its inputs are the cell's own: the runner's joint state (`cell.act("state")`, already LeRobot-normalized like the
recording) and one BGR frame per trained camera name. A frame whose size differs from the trained size is a refusal,
not a resize. An optional cam_warp.json in the folder (2x3 affine fitted by the model owner's omx_cam_warp.py) maps the
current view of that one camera back to the training view before inference, as the owner's runner does.

Goal-conditioned checkpoints need a goal slot. UNITS.json opts into sim-unit inference for a named arm.
The result is the proposed action chunk in LeRobot units. This module reads frames and numbers only; it has no
bus, runner or execution port (cell_act_shadow logs the chunk next to the real IK outcome)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from cell_belt_pose import BELT_NAMES

WEIGHTS = "model.safetensors"
ONNX_MODEL = "model.onnx"
ONNX_META = "ONNX_EXPORT.json"
WARP = "cam_warp.json"
UNITS = "UNITS.json"
ENV_STATE = "ENV_STATE.json"  # optional: {"names": [...], "belt_reference": {...}} copied from the dataset's meta/info.json
GOAL = "observation.environment_state"
# chunk_runner NAMES order (LeRobot omx_follower motors); the checkpoint's 6-wide state/action follow it.
JOINT_NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
IMAGE_PREFIX = "observation.images."
# The cell's camera roles; a checkpoint must name its inputs by them (docs/solutions/logic-errors/omx-policy-camera-names-differ-from-cell-roles-2026-11-21.md).
CAMERA_ROLES = ("top", "side", "wrist")


def checkpoint_digest(root: Path) -> dict[str, str]:
    """sha256 of every file in the folder; a link is refused (immutable files only, like deployment.py)."""
    digests = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"checkpoint link is not an immutable file: {path.name}")
        if path.is_file() and "__pycache__" not in path.parts:
            digests[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def read_features(config: dict) -> tuple[dict[str, tuple[int, int]], int, int | None]:
    """Trained camera sizes, action width and optional one-hot goal width from config.json."""
    if config.get("type") != "act":
        raise ValueError(f"policy type {config.get('type')!r}: only LeRobot ACT is bound")  # shortcut: ACT only, add smolvla when one is trained for a cell
    features, outputs = config.get("input_features") or {}, config.get("output_features") or {}
    if (features.get("observation.state") or {}).get("shape") != [len(JOINT_NAMES)]:
        raise ValueError("checkpoint state is not the 6 joints of one arm")
    if (outputs.get("action") or {}).get("shape") != [len(JOINT_NAMES)]:
        raise ValueError("checkpoint action is not the 6 joints of one arm")
    views = {}
    for key, spec in features.items():
        if key.startswith(IMAGE_PREFIX):
            channels, height, width = spec["shape"]
            if channels != 3:
                raise ValueError(f"{key} is not RGB")
            views[key[len(IMAGE_PREFIX):]] = (int(height), int(width))
    unknown = sorted(set(views) - set(CAMERA_ROLES))
    if unknown:
        raise ValueError(f"camera inputs {unknown} are not cell roles {CAMERA_ROLES}: rename the checkpoint inputs after checking a frame of each")
    if not views:
        raise ValueError("checkpoint has no camera input")
    goal_size = None
    if GOAL in features:
        spec = features[GOAL]
        shape = spec.get("shape") if isinstance(spec, dict) else None
        if not isinstance(shape, list) or len(shape) != 1 or type(shape[0]) is not int or shape[0] < 1:
            raise ValueError(f"{GOAL} must have a one-dimensional positive goal width")
        goal_size = shape[0]
    return views, len(JOINT_NAMES), goal_size


def read_env_state(path: Path, width: int | None) -> tuple[list | None, dict | None]:
    """(environment_state names, belt_reference) from ENV_STATE.json; (None, None) without the file."""
    if not path.is_file():
        return None, None
    doc = json.loads(path.read_text(encoding="utf-8"))
    names = doc.get("names") if isinstance(doc, dict) else None
    if (width is None or not isinstance(names, list) or len(names) != width
            or not all(isinstance(name, str) for name in names)):
        raise ValueError(f"{ENV_STATE}: names must list the {width} {GOAL} entries")
    return names, doc.get("belt_reference")


def read_sim_rule(path: Path, config: dict | None) -> dict | None:
    if not path.exists():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or (doc.get("state"), doc.get("gripper")) != ("sim_rad", "sim_jaw"):
        raise ValueError(f"{UNITS}: expected state=sim_rad and gripper=sim_jaw")
    arm = doc.get("arm")
    if arm not in ("arm_a", "arm_b") or (config or {}).get("arm_id") != arm:
        raise ValueError(f"{UNITS}: arm {arm!r} must match the cell config's arm_id (arm_a or arm_b)")
    from cell_arm_cal import profile_path

    profile = json.loads(profile_path(config, arm).read_text(encoding="utf-8"))
    if not isinstance(profile, dict) or profile.get("arm_id") != arm:
        raise ValueError(f"{arm}: arm-cal profile must have the matching arm_id")
    rule = {key: profile.get(key) for key in ("held_30mm", "gap_mm_per_unit")}
    if (any(type(value) not in (int, float) or not math.isfinite(value) for value in rule.values())
            or not 0 <= rule["held_30mm"] <= 100 or rule["gap_mm_per_unit"] <= 0):
        raise ValueError(f"{arm}: arm-cal profile needs valid held_30mm and gap_mm_per_unit")
    return rule


def read_warp(path: Path, views: dict[str, tuple[int, int]]) -> dict | None:
    """The cam_warp.json affine, checked against the trained camera and size; None without the file."""
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    camera, matrix, size = doc.get("camera"), doc.get("matrix"), doc.get("size")
    if camera not in views:
        raise ValueError(f"cam_warp camera {camera!r} is not a trained input {sorted(views)}")
    height, width = views[camera]
    if list(size or []) != [width, height]:
        raise ValueError(f"cam_warp size {size} differs from the trained {width}x{height}")
    array = np.asarray(matrix, dtype=np.float64)
    if array.shape != (2, 3) or not np.isfinite(array).all():
        raise ValueError("cam_warp matrix is not a finite 2x3 affine")
    return {"camera": camera, "matrix": array, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _has_openvino() -> bool:
    return "openvino" in sys.modules or importlib.util.find_spec("openvino") is not None


def _load_torch(root: Path, device: str):
    if device == "cpu":
        for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
            os.environ.setdefault(var, "2")
    import torch
    if device == "cpu":
        torch.set_num_threads(min(2, os.cpu_count() or 1))
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    policy = ACTPolicy.from_pretrained(str(root))
    policy.config.device = device
    policy.to(device).eval()
    pre, post = make_pre_post_processors(policy.config, pretrained_path=str(root),
                                         preprocessor_overrides={"device_processor": {"device": device}},
                                         postprocessor_overrides={"device_processor": {"device": "cpu"}})

    def predict(obs: dict) -> np.ndarray:
        batch = pre({key: torch.from_numpy(value) for key, value in obs.items()})
        with torch.inference_mode():
            chunk = policy.predict_action_chunk(batch)
        return np.asarray(post(chunk).detach().cpu().numpy(), dtype=np.float64).reshape(-1, len(JOINT_NAMES))

    return predict


def _load_lerobot(root: Path, device: str, *, policy_revision: str | None = None, onnx_sha256: str | None = None):
    """predict(obs) -> (chunk, 6) via OpenVINO pure-NumPy on CPU when valid model.onnx is present, else PyTorch."""
    backend = os.environ.get("ROSY_ACT_BACKEND", "auto").strip().lower()
    if backend not in ("auto", "torch", "openvino"):
        raise ValueError(f"unsupported ROSY_ACT_BACKEND={backend!r}: expected 'auto', 'torch', or 'openvino'")
    if backend == "torch":
        return _load_torch(root, device)
    if backend == "openvino":
        if device != "cpu":
            raise ValueError("ROSY_ACT_BACKEND='openvino' requires device='cpu'")
        import cell_lerobot_openvino as ov_backend

        return ov_backend.load_openvino(root, policy_revision, onnx_sha256=onnx_sha256, action_width=len(JOINT_NAMES))
    onnx_present = (
        (root / ONNX_MODEL).is_file()
        or (root / ONNX_MODEL).is_symlink()
        or (root / ONNX_META).is_file()
        or (root / ONNX_META).is_symlink()
    )
    if device == "cpu" and onnx_present and _has_openvino():
        import cell_lerobot_openvino as ov_backend

        return ov_backend.load_openvino(root, policy_revision, onnx_sha256=onnx_sha256, action_width=len(JOINT_NAMES))
    return _load_torch(root, device)


class LeRobotShadow:
    """One pinned LeRobot checkpoint; infer() turns cell state + BGR frames into a proposed chunk, never a command."""

    policy_environment = "real_lerobot"
    joint_names = JOINT_NAMES

    def __init__(self, root, policy_revision: str, *, loader=_load_lerobot, device: str = "cpu", cell_config=None):
        root = Path(root).expanduser().resolve(strict=True)
        self.files = checkpoint_digest(root)
        if self.files.get(WEIGHTS) != policy_revision:
            raise ValueError(f"{WEIGHTS} sha256 {self.files.get(WEIGHTS)} differs from the pinned revision {policy_revision}")
        self.policy_revision = policy_revision
        policy_config = json.loads((root / "config.json").read_text(encoding="utf-8"))
        self.image_views, _, self.goal_size = read_features(policy_config)
        self.env_names, self.belt_reference = read_env_state(root / ENV_STATE, self.goal_size)
        # the belt pose rides at the end only when the checkpoint names it so; any other naming keeps the one-hot goal
        self.belt_input = (self.env_names is not None and len(self.env_names) > len(BELT_NAMES)
                           and tuple(self.env_names[-len(BELT_NAMES):]) == BELT_NAMES)
        if self.belt_input:
            self.goal_size -= len(BELT_NAMES)
        self.n_action_steps = policy_config.get("n_action_steps")
        self.chunk_size = policy_config.get("chunk_size")
        self.sim_rule = read_sim_rule(root / UNITS, cell_config)
        self.arm_id = (cell_config or {}).get("arm_id")
        self.warp = read_warp(root / WARP, self.image_views)
        self._predict = (
            loader(root, device, policy_revision=self.policy_revision, onnx_sha256=self.files.get(ONNX_MODEL))
            if loader is _load_lerobot else loader(root, device)
        )

    def inputs(self, state, frames: dict, *, goal=None, mask_goal: bool = False, belt=None) -> tuple[dict, dict]:
        """(model observation, row metadata); a missing camera, a wrong size or a non-finite joint raises.
        `belt`: the three BELT_NAMES numbers (cell_belt_pose), required by and only by a checkpoint that names them."""
        import cv2

        positions = np.asarray([float(v) for v in state], dtype=np.float32)
        if positions.shape != (len(JOINT_NAMES),) or not np.isfinite(positions).all():
            raise ValueError(f"cell state {list(state)} is not 6 finite joints")
        if self.sim_rule is not None:
            from arm_status_bridge import JOINTS, to_radians
            from cell_act_inputs import sim_gripper

            body = to_radians(positions.tolist())
            positions = np.asarray([body[name] for name in JOINTS[:-1]] + [sim_gripper(float(positions[-1]), self.sim_rule)],
                                   dtype=np.float32)
        obs, meta = {"observation.state": positions}, {"model_frame_sha256": {}, "warp_sha256": None}
        if mask_goal and self.goal_size is None:
            raise ValueError("goal masking requires a goal-conditioned checkpoint")
        if self.goal_size is not None:
            if goal is None:
                raise ValueError(f"checkpoint requires a goal slot (0..{self.goal_size - 1})")
            if isinstance(goal, (int, np.integer)) and not isinstance(goal, bool):
                if not 0 <= goal < self.goal_size:
                    raise ValueError(f"goal slot must be 0..{self.goal_size - 1}")
                vector = np.zeros(self.goal_size, dtype=np.float32)
                vector[goal] = 1
            else:
                vector = np.asarray(goal)
                if vector.shape != (self.goal_size,) or not np.isin(vector, (0, 1)).all() or np.count_nonzero(vector) != 1:
                    raise ValueError(f"goal must be a {self.goal_size}-element one-hot vector")
                vector = vector.astype(np.float32)
            meta["goal_slot"] = int(vector.argmax())
            if mask_goal:
                meta["goal_masked"] = True
                vector.fill(0)
            obs[GOAL] = vector
        if self.belt_input:
            pose = np.asarray(belt if belt is not None else (), dtype=np.float32)
            if pose.shape != (len(BELT_NAMES),) or not np.isfinite(pose).all():
                raise ValueError(f"checkpoint requires the belt container pose {BELT_NAMES} as 3 finite numbers")
            obs[GOAL] = np.concatenate([obs[GOAL], pose])
            meta["belt_pose"] = pose.tolist()
        elif belt is not None:
            raise ValueError("checkpoint has no belt pose input")
        for view, (height, width) in self.image_views.items():
            frame = frames.get(view)
            if frame is None:
                raise ValueError(f"camera {view!r} unavailable")
            if tuple(frame.shape) != (height, width, 3):
                raise ValueError(f"camera {view!r} frame {tuple(frame.shape)} differs from the trained {height}x{width}x3")
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)  # the cell decodes BGR (cv2.imdecode); LeRobot recorded RGB
            if self.warp is not None and self.warp["camera"] == view:
                rgb = cv2.warpAffine(rgb, self.warp["matrix"], (width, height))
                meta["warp_sha256"] = self.warp["sha256"]
            meta["model_frame_sha256"][view] = hashlib.sha256(np.ascontiguousarray(rgb).tobytes()).hexdigest()
            obs[IMAGE_PREFIX + view] = np.ascontiguousarray(rgb.transpose(2, 0, 1), dtype=np.float32) / 255.0
        return obs, meta

    def infer(self, obs: dict, *, state=None) -> SimpleNamespace:
        chunk = np.asarray(self._predict(obs), dtype=np.float64)
        if chunk.ndim != 2 or not len(chunk) or chunk.shape[1] != len(JOINT_NAMES) or not np.isfinite(chunk).all():
            raise ValueError(f"policy output {chunk.shape} is not a finite (n, 6) chunk")
        if self.sim_rule is not None:
            from arm_status_bridge import TICKS
            from cell_act_inputs import real_grippers

            held, slope = self.sim_rule["held_30mm"], self.sim_rule["gap_mm_per_unit"]
            angles = chunk[:, -1]
            if np.any((angles < 0) | (angles > 1)):
                raise ValueError("policy sim jaw output is outside 0..1")
            gripper = real_grippers(angles, self.sim_rule)
            if state is not None:
                gap = 30 + (state[-1] - held) * slope
                if not 12 <= gap <= 60:
                    # An echo of the clipped input cannot recover its original position without the readback.
                    gripper[np.isclose(angles, obs["observation.state"][-1], atol=1e-6, rtol=0)] = state[-1]
            body = (chunk[:, :-1] + math.pi) * TICKS / (2 * math.pi) * 200 / (TICKS - 1) - 100
            chunk = np.column_stack((body, gripper))
        return SimpleNamespace(chunk=[tuple(map(float, row)) for row in chunk])


def main(argv=None) -> int:
    """Offline check on the cell: load the pinned checkpoint and print one chunk for zero-motion frames (no arm)."""
    import argparse

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("policy_root", type=Path)
    parser.add_argument("policy_revision")
    parser.add_argument("--state", default="18,-31,27,48,68,49", help="6 LeRobot-normalized joints")
    parser.add_argument("--config", type=Path, help="cell config for a sim-unit checkpoint")
    parser.add_argument("--goal-slot", type=int, help="zero-based checkpoint goal slot")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else None
    shadow = LeRobotShadow(args.policy_root, args.policy_revision, cell_config=config)
    frames = {view: np.zeros((h, w, 3), dtype=np.uint8) for view, (h, w) in shadow.image_views.items()}
    state = [float(v) for v in args.state.split(",")]
    obs, meta = shadow.inputs(state, frames, goal=args.goal_slot)
    chunk = shadow.infer(obs, state=state).chunk
    print(json.dumps({"views": shadow.image_views, "warp": shadow.warp and shadow.warp["camera"], "chunk_len": len(chunk),
                      "first": chunk[0], "finite": all(math.isfinite(v) for row in chunk for v in row), **meta}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
