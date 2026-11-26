"""Policy start gate: a policy sees only states its checkpoint was trained on (2026-11-26).

The ACT checkpoint normalises observation.state with MEAN_STD, so a state outside the trained range is extrapolated
silently. Real arm_a/arm_b read shoulder_lift -1.96 rad (trained min -1.76) from the idle park and arm_b parked its
wrist_roll at -47 (trained min -1.114 rad). The learning first frame is the end of the entry chunk (canonical start,
+-start_jitter_rad), not the folded home. Every refusal here sends no policy command; the caller keeps its own
retreat/park/hold path. Folded poses before the entry chunk are not gated (except arm_b's wrist_roll branch).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from cell_control_core import norm_to_rad
from cell_lerobot_shadow import JOINT_NAMES

MARGIN_RAD, MARGIN_UNITS = 0.05, 1.6  # slack past the trained min/max; 1.6 units = 0.05 rad (200 units per turn)
ROLL = JOINT_NAMES.index("wrist_roll")
RANGE_CODE, START_CODE, STATS_CODE = "POLICY_STATE_OUT_OF_RANGE", "POLICY_START_POSE_MISMATCH", "POLICY_STATE_STATS_MISSING"


def read_state_range(policy_root) -> dict[str, np.ndarray]:
    """observation.state min/max (and q01/q99 when present) from the normalizer file policy_preprocessor.json names, else the
    policy_preprocessor_step_*_normalizer_processor.safetensors beside it (all 17 installed cell checkpoints, 2026-11-26)."""
    root = Path(policy_root)

    def missing(why: str) -> ValueError:
        return ValueError(f"{STATS_CODE}: {root} {why}; put the checkpoint's normalizer file (policy_preprocessor_step_N_normalizer_processor.safetensors, "
                          "as named in policy_preprocessor.json) in that folder, or re-export the checkpoint with it")

    names: list[str] = []
    try:
        steps = json.loads((root / "policy_preprocessor.json").read_text(encoding="utf-8"))["steps"]
        names = [s["state_file"] for s in steps if s.get("registry_name") == "normalizer_processor" and isinstance(s.get("state_file"), str)]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    path = next((root / n for n in names if Path(n).name == n and (root / n).is_file()), None)
    path = path or next(iter(sorted(root.glob("policy_preprocessor_step_*_normalizer_processor.safetensors"))), None)
    if path is None:
        raise missing("has no normalizer statistics file")
    try:
        from safetensors.numpy import load_file

        stats = load_file(str(path))
        out = {k: np.asarray(stats[f"observation.state.{k}"], dtype=float) for k in ("min", "max", "q01", "q99")
               if f"observation.state.{k}" in stats}
    except Exception as error:  # unreadable file, missing library: the gate cannot judge, so it refuses
        raise missing(f"{path.name} cannot be read ({type(error).__name__})") from error
    if not {"min", "max"} <= set(out) or any(v.shape != (len(JOINT_NAMES),) for v in out.values()):
        raise missing(f"{path.name} has no 6-joint observation.state min and max")
    return out


def canonical_start(arm_id) -> tuple[list[float], float] | None:
    """(canonical_start sim_rad for joints 0..4, start_jitter_rad) for arm_a/arm_b; None for arms without one."""
    from rosy.contracts.learning.omx_canonical import default_canonical_spec

    spec = default_canonical_spec()
    pose = (spec["canonical_start"] if arm_id in spec["canonical_start"] else {}).get(arm_id)
    return None if pose is None else (list(pose["sim_rad"][:5]), float(spec["start_jitter_rad"]))


def library_entry_error(library: dict, arm_id) -> str | None:
    """Refuse a library whose entry chunk ends away from the canonical start the checkpoint was trained from."""
    chunks = library.get("chunks") if isinstance(library, dict) else None
    canon = canonical_start(arm_id)
    if not isinstance(chunks, dict) or not chunks.get("entry") or canon is None:
        return None
    end = [norm_to_rad(float(v)) for v in chunks["entry"][-1][:5]]
    off = max(abs(a - b) for a, b in zip(end, canon[0]))
    return None if off <= canon[1] else f"{START_CODE}: library entry ends {off:.3f} rad from the canonical start (limit {canon[1]})"


class StateGate:
    def __init__(self, stats: dict, *, arm_id=None, sim_rule=None, offset=None, margin=None):
        self.stats, self.arm_id, self.sim_rule = stats, arm_id, sim_rule
        self.offset = np.zeros(len(JOINT_NAMES)) if offset is None else np.asarray(offset, dtype=float)
        default = MARGIN_RAD if sim_rule is not None else MARGIN_UNITS
        self.margin = default * (1.0 if margin is None else min(float(margin), 1.0))  # policy.state_margin_frac: the schema allows 0..1, only tighter
        self.canon = canonical_start(arm_id) if sim_rule is not None else None

    def model_state(self, state) -> np.ndarray:
        """The state the model sees: sim radians and sim jaw for a sim-unit checkpoint, else cell units plus the offset."""
        if self.sim_rule is None:
            return np.asarray(state, dtype=float) + self.offset
        from arm_status_bridge import JOINTS, to_radians
        from cell_act_inputs import sim_gripper

        body = to_radians([float(v) for v in state])
        return np.asarray([body[n] for n in JOINTS[:-1]] + [sim_gripper(float(state[-1]), self.sim_rule)], dtype=float)

    def _outside(self, state, joints) -> str | None:
        model = self.model_state(state)
        for j in joints:
            lo, hi = self.stats["min"][j] - self.margin, self.stats["max"][j] + self.margin
            if not lo <= model[j] <= hi:
                return f"{JOINT_NAMES[j]} {model[j]:.3f} outside the checkpoint state range [{lo:.3f}, {hi:.3f}]"
        return None

    def roll_error(self, state) -> str | None:
        """arm_b before the entry chunk: a wrist_roll on the untrained branch needs the existing home/rehome task first."""
        if self.arm_id != "arm_b" or not (why := self._outside(state, (ROLL,))):
            return None
        return f"{START_CODE}: {why}; run the existing home/rehome task before the policy"

    def start_error(self, state) -> str | None:
        if self.canon is None:
            return None
        rad = [norm_to_rad(float(v)) for v in state[:5]]
        off = [abs(a - b) for a, b in zip(rad, self.canon[0])]
        return None if max(off) <= self.canon[1] else (
            f"{START_CODE}: {JOINT_NAMES[int(np.argmax(off))]} is {max(off):.3f} rad from the canonical start (limit {self.canon[1]})")

    def verdict(self, state, *, after_entry: bool) -> str | None:
        """Why no policy command may be sent from this measured state, else None."""
        if after_entry and (why := self.start_error(state)):
            return why
        return f"{RANGE_CODE}: {why}" if (why := self._outside(state, range(len(JOINT_NAMES)))) else None

    def warnings(self, state) -> list[str]:
        """Joints inside min/max but outside the trained q01..q99 (logged only)."""
        if "q01" not in self.stats or "q99" not in self.stats:
            return []
        model = self.model_state(state)
        return [JOINT_NAMES[j] for j in range(len(JOINT_NAMES)) if not self.stats["q01"][j] <= model[j] <= self.stats["q99"][j]]


def build_gate(policy_root, library: dict, shadow, offset, margin=None) -> StateGate:
    """Raises ValueError (refused at load) when the checkpoint has no state range or the library entry misses the canonical start."""
    arm_id = getattr(shadow, "arm_id", None)
    if why := library_entry_error(library, arm_id) if getattr(shadow, "sim_rule", None) is not None else None:
        raise ValueError(why)
    return StateGate(read_state_range(policy_root), arm_id=arm_id, sim_rule=getattr(shadow, "sim_rule", None), offset=offset, margin=margin)
