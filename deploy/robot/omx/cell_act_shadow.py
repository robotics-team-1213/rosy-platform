#!/usr/bin/env python3
"""ACT shadow inference beside the real IK carry (VLA pipeline handoff 2026-11-13, slice 5).

Config `act_shadow` = {"policy_root", "policy_revision"} turns it on, absent = off. On the top
observation each carry in `cell_auto_pick.run_auto` is planned from, one row per carry goes to
`act-shadow.jsonl` next to attempts.jsonl (`rosy.omx-act-shadow.v1`): the pinned policy's
proposed joint-target chunk, the observation id/time, the policy id and environment, any
inference error, and the same carry's real IK outcome. Shadow output has no execution port
(this module only reads `cell.frame` and `cell.act("state")`; a test pins that), and an inference error is a field
in the row, never a change to the IK path.

`kind: "two_arm"` in the config binds the sim-trained two-arm policy instead: four cameras, both arms' twelve joints and the goal
vector, assembled by `cell_act_inputs` in the trained order. An input the cell cannot read (a camera, the peer arm in
`act_shadow.peer` = {"io", "cameras"}, a goal) is a row `error` naming it, never a blank or copied substitute."""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_act_inputs as inputs  # noqa: E402

SCHEMA = "rosy.omx-act-shadow.v1"


def load(config: dict, work: Path):
    """The real-observation shadow binding (ACTShadowInference) from config; None when the flag is off."""
    spec = config.get("act_shadow")
    if not spec:
        return None
    try:
        learning = Path(__file__).resolve().parents[3] / "learning" / "training" / "omx"
        if str(learning) not in sys.path:
            sys.path.insert(0, str(learning))
        if spec.get("kind") == "two_arm":
            import act_two_arm_shadow

            binding = act_two_arm_shadow.TwoArmShadowInference(
                Path(spec["policy_root"]).expanduser(), spec["policy_revision"], Path(spec["steps_file"]).expanduser(),
                joint_names=inputs.JOINT_NAMES)
            return Shadow(binding, work, None, spec=spec)
        import act_inference

        binding = act_inference.ACTShadowInference(Path(spec["policy_root"]).expanduser(), spec["policy_revision"])
        return Shadow(binding, work, act_inference.ShadowObservation)
    except Exception as error:
        return Shadow(None, work, None, error=f"{type(error).__name__}: {error}",
                      policy_id=spec.get("policy_revision") if isinstance(spec, dict) else None)


def record(shadow, row, attempt_id, outcome, at) -> None:
    """Joins the carry's shadow row to its IK outcome; a no-op without a binding or a carry row."""
    if shadow is not None and row is not None:
        try:
            shadow.record(row, attempt_id, outcome, at)
        except Exception as error:  # shadow logging has no authority over the IK carry
            print(f"ACT shadow log failed: {error}", file=sys.stderr)


class Shadow:
    """Asks the pinned policy on the carry's observation; the proposal is logged, never executed."""

    def __init__(self, binding, work: Path, observation, *, error=None, policy_id=None, spec=None, peer=None):
        self._binding, self._path, self._observation = binding, Path(work) / "act-shadow.jsonl", observation
        self._error, self._policy_id, self._spec, self._peer = error, policy_id, spec, peer

    def _peer_cell(self):
        """The other arm's cell for its wrist frame and state: opened once, read only (frame and state), None without config."""
        if self._peer is None and (self._spec or {}).get("peer"):
            import cell_pipeline as cp

            peer = self._spec["peer"]
            self._peer = cp.FifoCell(Path(peer["io"]).expanduser(), peer["cameras"])
        return self._peer

    def _two_arm(self, row, cell, config, source, dest):
        row["observation"].pop("camera_identity", None)  # the single-wrist field; the four cameras are in `camera_sources`
        try:
            taken = inputs.assemble(cell, config, self._peer_cell(), self._spec, self._binding, source, dest)
        except inputs.Unavailable as error:
            row["error"], row["missing"] = f"inputs_unavailable: {error}", error.missing
            return row
        row["observation"].update(taken["meta"])
        row["proposed"] = [list(map(float, q)) for q in self._binding.infer(taken).chunk]
        return row

    def capture(self, cell, config: dict, attempt: int, obs_img, source=None, dest=None) -> dict | None:
        """One inference on the observation the IK plan came from; never raises, never moves the arm."""
        row = {"schema": SCHEMA, "policy_id": self._binding.policy_revision if self._binding else self._policy_id,
               "policy_environment": self._binding.policy_environment if self._binding else None, "attempt": attempt}
        try:
            camera = config.get("cameras", {}).get("wrist", {})
            row["observation"] = {"t_ns": time.time_ns(), "top_frame_sha256": _sha(obs_img),
                                  "camera_identity": camera.get("url", "wrist"),
                                  "joint_names": list(self._binding.joint_names) if self._binding else None}
            row["observation"]["id"] = f"{row['observation']['t_ns']}-{row['observation']['top_frame_sha256'][:12]}"
            if self._error:
                raise ValueError(self._error)
            if self._spec is not None:
                return self._two_arm(row, cell, config, source, dest)
            state = cell.act("state")["state"]
            frame = cell.frame("wrist")
            observation = self._observation(
                joint_names=self._binding.joint_names, positions=state,
                observed_at_ns=row["observation"]["t_ns"], camera_identity=row["observation"]["camera_identity"],
                camera_shape=(3, *frame.shape[:2]), camera_received_at_ns=time.time_ns(), rgb=frame.tobytes(),
            )
            row["observation"]["wrist_frame_sha256"] = _sha(frame)
            row["observation"]["positions"] = list(state)
            row["proposed"] = [list(q) for q in self._binding.infer(observation).chunk]
        except Exception as error:  # an inference fault is data in the row, never a stop (handoff 4-2)
            row["error"] = f"{type(error).__name__}: {error}"
        return row

    def record(self, row: dict, attempt_id, outcome, at) -> None:
        row = {**row, "attempt_id": attempt_id, "ik": {"outcome": outcome, "at": at}}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, default=str) + "\n")


def _sha(img) -> str:
    return hashlib.sha256(np.ascontiguousarray(img).tobytes()).hexdigest()
