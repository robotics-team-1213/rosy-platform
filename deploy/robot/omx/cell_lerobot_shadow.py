#!/usr/bin/env python3
"""Shadow binding for a LeRobot checkpoint trained on one real arm (arm_s pinky_v1_aug_act_100k, 2026-11-18).

The checkpoint folder is used as LeRobot wrote it (config.json, model.safetensors, policy_pre/postprocessor*), pinned by
the sha256 of model.safetensors: `act_shadow` = {"kind": "lerobot", "policy_root", "policy_revision": <that sha256>}.
Its inputs are the cell's own: the runner's joint state (`cell.act("state")`, already LeRobot-normalized like the
recording) and one BGR frame per trained camera name. A frame whose size differs from the trained size is a refusal,
not a resize. An optional cam_warp.json in the folder (2x3 affine fitted by the model owner's omx_cam_warp.py) maps the
current view of that one camera back to the training view before inference, as the owner's runner does.

The result is the proposed action chunk in the same LeRobot units. This module reads frames and numbers only; it has no
bus, runner or execution port (cell_act_shadow logs the chunk next to the real IK outcome)."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np

WEIGHTS = "model.safetensors"
WARP = "cam_warp.json"
# chunk_runner NAMES order (LeRobot omx_follower motors); the checkpoint's 6-wide state/action follow it.
JOINT_NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
IMAGE_PREFIX = "observation.images."


def checkpoint_digest(root: Path) -> dict[str, str]:
    """sha256 of every file in the folder; a link is refused (immutable files only, like deployment.py)."""
    digests = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"checkpoint link is not an immutable file: {path.name}")
        if path.is_file() and "__pycache__" not in path.parts:
            digests[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def read_features(config: dict) -> tuple[dict[str, tuple[int, int]], int]:
    """(trained camera name -> (height, width), action width) from config.json; only a 6-joint single-arm ACT."""
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
    if not views:
        raise ValueError("checkpoint has no camera input")
    return views, len(JOINT_NAMES)


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


def _load_lerobot(root: Path, device: str):
    """predict(obs) -> (chunk, 6) array through the checkpoint's own pre/post processors (LeRobot 0.4.4)."""
    import torch
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


class LeRobotShadow:
    """One pinned LeRobot checkpoint; infer() turns cell state + BGR frames into a proposed chunk, never a command."""

    policy_environment = "real_lerobot"
    joint_names = JOINT_NAMES

    def __init__(self, root, policy_revision: str, *, loader=_load_lerobot, device: str = "cpu"):
        root = Path(root).expanduser().resolve(strict=True)
        self.files = checkpoint_digest(root)
        if self.files.get(WEIGHTS) != policy_revision:
            raise ValueError(f"{WEIGHTS} sha256 {self.files.get(WEIGHTS)} differs from the pinned revision {policy_revision}")
        self.policy_revision = policy_revision
        self.image_views, _ = read_features(json.loads((root / "config.json").read_text(encoding="utf-8")))
        self.warp = read_warp(root / WARP, self.image_views)
        self._predict = loader(root, device)

    def inputs(self, state, frames: dict) -> tuple[dict, dict]:
        """(model observation, row metadata); a missing camera, a wrong size or a non-finite joint raises."""
        import cv2

        positions = np.asarray([float(v) for v in state], dtype=np.float32)
        if positions.shape != (len(JOINT_NAMES),) or not np.isfinite(positions).all():
            raise ValueError(f"cell state {list(state)} is not 6 finite joints")
        obs, meta = {"observation.state": positions}, {"model_frame_sha256": {}, "warp_sha256": None}
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

    def infer(self, obs: dict) -> SimpleNamespace:
        chunk = np.asarray(self._predict(obs), dtype=np.float64)
        if chunk.ndim != 2 or chunk.shape[1] != len(JOINT_NAMES) or not np.isfinite(chunk).all():
            raise ValueError(f"policy output {chunk.shape} is not a finite (n, 6) chunk")
        return SimpleNamespace(chunk=[tuple(map(float, row)) for row in chunk])


def main(argv=None) -> int:
    """Offline check on the cell: load the pinned checkpoint and print one chunk for zero-motion frames (no arm)."""
    import argparse

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("policy_root", type=Path)
    parser.add_argument("policy_revision")
    parser.add_argument("--state", default="18,-31,27,48,68,49", help="6 LeRobot-normalized joints")
    args = parser.parse_args(argv)
    shadow = LeRobotShadow(args.policy_root, args.policy_revision)
    frames = {view: np.zeros((h, w, 3), dtype=np.uint8) for view, (h, w) in shadow.image_views.items()}
    obs, meta = shadow.inputs([float(v) for v in args.state.split(",")], frames)
    chunk = shadow.infer(obs).chunk
    print(json.dumps({"views": shadow.image_views, "warp": shadow.warp and shadow.warp["camera"], "chunk_len": len(chunk),
                      "first": chunk[0], "finite": all(math.isfinite(v) for row in chunk for v in row), **meta}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
