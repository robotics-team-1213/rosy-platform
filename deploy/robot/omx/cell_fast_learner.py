#!/usr/bin/env python3
"""90-Minute Fast Learning Module: 20-D Residual Failure Classifier, Safety Sovereignty, and IWR Policy Decorator.

Implements the Round 2 consensus architecture:
  1. 20-D low-dimensional geometric/load residual feature vector (`extract_feature_vector_20d`).
  2. Physical Rule Guard with Unidirectional Safety Sovereignty (`rule_guard_verdict`, `combine_verdicts`):
     final_verdict = max_severity(rule_out, model_out) over PASS (0) < UNKNOWN (1) < FAIL (2).
  3. Asymmetric cost-sensitive 20-D residual classifier (`ResidualFailureClassifier`, w_FP = 5.0).
  4. Intervention-Weighted Regression (`InterventionWeightedLearner`, w_human = 5.0, w_normal = 1.0)
     with bounded residual pose decorator (|dx|, |dy| <= 8 mm, |dyaw| <= 10 deg).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

FEATURE_NAMES_20D: tuple[str, ...] = (
    "is_c1", "is_c2", "is_c3", "tier_k",
    "x_hat_mm", "sigma_x_mm", "dy_mm", "yaw_err_deg",
    "r_k_mm", "dz_top_side_mm", "area_ratio", "tilt_deg",
    "valid_depth_ratio",
    "clear_pos_x_mm", "clear_neg_x_mm", "clear_pos_y_mm", "clear_neg_y_mm",
    "temp_slot_free", "gripper_pos", "gripper_current_ma",
)

SEVERITY_ORDER: dict[str, int] = {"PASS": 0, "UNKNOWN": 1, "FAIL": 2}

CLASSES: tuple[str, ...] = (
    "PASS",
    "S1_POSE_OFFSET_OR_YAW",
    "S2_TOPPLED_OR_SLUMPED",
    "S3_PACKED_NO_CLEARANCE",
    "S4_EMPTY_OR_SHALLOW",
    "S5_VIEW_OR_GATE_MISMATCH",
    "S6_UNSEATED_CONE",
)

SKILLS: tuple[str, ...] = (
    "proceed", "reobserve_shift", "wrist_yaw_servo", "push_align_side",
    "push_align_end", "free_push", "seat_nudge", "reinsert_pick",
    "recenter_on_temp", "clear_neighbor_then_pick", "abort_safe_hold",
)

RESIDUAL_BOUNDS: dict[str, tuple[float, float]] = {
    "dx_mm": (-8.0, 8.0),
    "dy_mm": (-8.0, 8.0),
    "dyaw_deg": (-10.0, 10.0),
}


def extract_feature_vector_20d(obs: dict[str, Any]) -> np.ndarray:
    """Extract the canonical 20-dimensional residual feature vector from an observation dictionary."""
    spec_id = str(obs.get("spec_id", "C3")).upper()
    is_c1, is_c2 = (1.0 if spec_id == "C1" else 0.0), (1.0 if spec_id == "C2" else 0.0)
    is_c3 = 1.0 if (spec_id == "C3" or (is_c1 == 0.0 and is_c2 == 0.0)) else 0.0
    dz_default = abs(float(obs.get("z_top_mm", 0.0)) - float(obs.get("z_side_mm", 0.0)))
    vec = [
        is_c1, is_c2, is_c3, float(obs.get("tier_k", 1.0)),
        float(obs.get("x_hat_mm", 0.0)), float(obs.get("sigma_x_mm", 1.0)),
        float(obs.get("dy_mm", 0.0)), float(obs.get("yaw_err_deg", 0.0)),
        float(obs.get("r_k_mm", 0.0)), float(obs.get("dz_top_side_mm", dz_default)),
        float(obs.get("area_ratio", 1.0)), float(obs.get("tilt_deg", 0.0)),
        float(obs.get("valid_depth_ratio", 1.0)),
        float(obs.get("clear_pos_x_mm", 20.0)), float(obs.get("clear_neg_x_mm", 20.0)),
        float(obs.get("clear_pos_y_mm", 20.0)), float(obs.get("clear_neg_y_mm", 20.0)),
        1.0 if bool(obs.get("temp_slot_free", True)) else 0.0,
        float(obs.get("gripper_pos", 54.0)), float(obs.get("gripper_current_ma", 120.0)),
    ]
    return np.asarray(vec, dtype=np.float64)


def rule_guard_verdict(obs: dict[str, Any]) -> dict[str, Any]:
    """Deterministic physical invariant check before or alongside any learned model."""
    r_k_mm = float(obs.get("r_k_mm", 0.0))
    tilt_deg = float(obs.get("tilt_deg", 0.0))
    if bool(obs.get("contact", False)) or r_k_mm <= -4.0 or tilt_deg > 10.0:
        code = "S2_TOPPLED_OR_SLUMPED" if (r_k_mm <= -4.0 or tilt_deg > 10.0) else "S7_CONTACT"
        return {"verdict": "FAIL", "failure_code": code, "source": "rule_guard"}

    dz_default = abs(float(obs.get("z_top_mm", 0.0)) - float(obs.get("z_side_mm", 0.0)))
    dz_top_side_mm = float(obs.get("dz_top_side_mm", dz_default))
    if (
        float(obs.get("valid_depth_ratio", 1.0)) < 0.80
        or dz_top_side_mm > 8.0
        or float(obs.get("area_ratio", 1.0)) < 0.65
        or 2.0 * float(obs.get("sigma_x_mm", 1.0)) > 5.0
    ):
        return {"verdict": "UNKNOWN", "failure_code": "S5_VIEW_OR_GATE_MISMATCH", "source": "rule_guard"}

    if 1.0 <= r_k_mm <= 3.0:
        return {"verdict": "FAIL", "failure_code": "S6_UNSEATED_CONE", "source": "rule_guard"}

    if bool(obs.get("at_lift", False)):
        if float(obs.get("gripper_current_ma", 120.0)) < 75.0 or not (51.8 <= float(obs.get("gripper_pos", 54.0)) <= 56.8):
            return {"verdict": "FAIL", "failure_code": "S4_EMPTY_OR_SHALLOW", "source": "rule_guard"}

    return {"verdict": "PASS", "failure_code": None, "source": "rule_guard"}


def combine_verdicts(rule_out: dict[str, Any], model_out: dict[str, Any]) -> dict[str, Any]:
    """Unidirectional Safety Sovereignty: model can escalate PASS -> UNKNOWN/FAIL, never downgrade FAIL/UNKNOWN -> PASS."""
    r_verdict = str(rule_out.get("verdict", "PASS"))
    m_verdict = str(model_out.get("verdict", "PASS"))
    if SEVERITY_ORDER.get(r_verdict, 1) >= SEVERITY_ORDER.get(m_verdict, 1):
        return {
            "verdict": r_verdict,
            "failure_code": rule_out.get("failure_code") or model_out.get("failure_code"),
            "authority": "rule_guard",
            "rule_verdict": r_verdict,
            "model_verdict": m_verdict,
        }
    return {
        "verdict": m_verdict,
        "failure_code": model_out.get("failure_code") or rule_out.get("failure_code"),
        "authority": "model_escalation",
        "rule_verdict": r_verdict,
        "model_verdict": m_verdict,
    }


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=-1, keepdims=True)
    exps = np.exp(np.clip(shifted, -40.0, 40.0))
    return exps / np.sum(exps, axis=-1, keepdims=True)


class ResidualFailureClassifier:
    """Asymmetric cost-sensitive 20-D classifier that penalizes False-PASS by w_FP = 5.0."""

    def __init__(self, classes: tuple[str, ...] = CLASSES, pass_threshold: float = 0.70):
        self.classes = tuple(classes)
        self.pass_threshold = float(pass_threshold)
        self.mean = np.zeros(len(FEATURE_NAMES_20D), dtype=np.float64)
        self.scale = np.ones(len(FEATURE_NAMES_20D), dtype=np.float64)
        self.W = np.zeros((len(FEATURE_NAMES_20D), len(self.classes)), dtype=np.float64)
        self.b = np.zeros(len(self.classes), dtype=np.float64)
        self.fitted = False

    def _to_matrix(self, X: Any) -> np.ndarray:
        if isinstance(X, dict):
            return extract_feature_vector_20d(X)[None, :]
        if isinstance(X, list) and X and isinstance(X[0], dict):
            return np.vstack([extract_feature_vector_20d(row) for row in X])
        arr = np.asarray(X, dtype=np.float64)
        return arr[None, :] if arr.ndim == 1 else arr

    def fit(
        self,
        X: Any,
        y: list[str | int] | np.ndarray,
        sample_weight: np.ndarray | list[float] | None = None,
        false_pass_weight: float = 5.0,
        epochs: int = 120,
        lr: float = 0.12,
        l2: float = 1e-3,
    ) -> "ResidualFailureClassifier":
        X_mat = self._to_matrix(X)
        n = X_mat.shape[0]
        self.mean = np.mean(X_mat, axis=0)
        std = np.std(X_mat, axis=0)
        self.scale = np.where(std > 1e-6, std, 1.0)
        Z = (X_mat - self.mean) / self.scale

        c2i = {c: i for i, c in enumerate(self.classes)}
        y_idx = np.array([c2i[c] if isinstance(c, str) else int(c) for c in y], dtype=np.int64)
        Y_onehot = np.eye(len(self.classes), dtype=np.float64)[y_idx]

        w = np.ones(n, dtype=np.float64) if sample_weight is None else np.asarray(sample_weight, dtype=np.float64).copy()
        is_fail = y_idx != 0
        w = np.where(is_fail, w * float(false_pass_weight), w)
        w = w / max(np.mean(w), 1e-8)

        self.W = np.zeros((Z.shape[1], len(self.classes)), dtype=np.float64)
        self.b = np.zeros(len(self.classes), dtype=np.float64)
        if np.any(is_fail):
            self.b[0] = -np.log(max(float(false_pass_weight), 1.0))

        for _ in range(int(epochs)):
            probs = _softmax(Z @ self.W + self.b)
            diff = (probs - Y_onehot) * w[:, None]
            fp_push = np.where(is_fail, probs[:, 0] * (float(false_pass_weight) - 1.0), 0.0)
            diff[:, 0] += fp_push
            for c_idx in range(1, len(self.classes)):
                mask_c = y_idx == c_idx
                diff[mask_c, c_idx] -= fp_push[mask_c]
            self.W -= lr * ((Z.T @ diff) / n + l2 * self.W)
            self.b -= lr * np.mean(diff, axis=0)

        self.fitted = True
        return self

    def predict(self, obs_or_x: dict[str, Any] | np.ndarray | list[float]) -> dict[str, Any]:
        x = self._to_matrix(obs_or_x)[0]
        z = (x - self.mean) / self.scale
        probs = _softmax((z @ self.W + self.b)[None, :])[0]
        prob_map = {c: float(round(probs[i], 6)) for i, c in enumerate(self.classes)}
        pass_prob = float(probs[0])
        best_fail_class = self.classes[int(np.argmax(probs[1:]) + 1)]
        if pass_prob >= self.pass_threshold and int(np.argmax(probs)) == 0:
            verdict, failure_code = "PASS", None
        elif best_fail_class == "S5_VIEW_OR_GATE_MISMATCH":
            verdict, failure_code = "UNKNOWN", best_fail_class
        else:
            verdict, failure_code = "FAIL", best_fail_class
        return {
            "verdict": verdict,
            "failure_code": failure_code,
            "probs": prob_map,
            "false_pass_prob": float(round(pass_prob, 6)),
        }

    def evaluate_with_guard(self, obs: dict[str, Any]) -> dict[str, Any]:
        rule_out = rule_guard_verdict(obs)
        model_out = self.predict(obs) if self.fitted else {"verdict": "PASS", "failure_code": None}
        return combine_verdicts(rule_out, model_out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "classes": list(self.classes), "pass_threshold": self.pass_threshold,
            "mean": self.mean.tolist(), "scale": self.scale.tolist(),
            "W": self.W.tolist(), "b": self.b.tolist(), "fitted": self.fitted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResidualFailureClassifier":
        obj = cls(classes=tuple(data.get("classes", CLASSES)), pass_threshold=float(data.get("pass_threshold", 0.70)))
        obj.mean = np.asarray(data["mean"], dtype=np.float64)
        obj.scale = np.asarray(data["scale"], dtype=np.float64)
        obj.W = np.asarray(data["W"], dtype=np.float64)
        obj.b = np.asarray(data["b"], dtype=np.float64)
        obj.fitted = bool(data.get("fitted", True))
        return obj

    def save(self, path: Path | str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path | str) -> "ResidualFailureClassifier":
        return cls.from_dict(json.loads(Path(path).read_text()))


class InterventionWeightedLearner:
    """HG-DAgger / Intervention-Weighted Regression (IWR) + Bounded Residual Policy Decorator."""

    def __init__(self, skills: tuple[str, ...] = SKILLS, human_weight: float = 5.0, normal_weight: float = 1.0):
        self.skills = tuple(skills)
        self.human_weight = float(human_weight)
        self.normal_weight = float(normal_weight)
        self.mean = np.zeros(len(FEATURE_NAMES_20D), dtype=np.float64)
        self.scale = np.ones(len(FEATURE_NAMES_20D), dtype=np.float64)
        self.W_skill = np.zeros((len(FEATURE_NAMES_20D), len(self.skills)), dtype=np.float64)
        self.b_skill = np.zeros(len(self.skills), dtype=np.float64)
        self.W_res = np.zeros((len(FEATURE_NAMES_20D), 3), dtype=np.float64)
        self.b_res = np.zeros(3, dtype=np.float64)
        self.buffer_X: list[np.ndarray] = []
        self.buffer_skill: list[int] = []
        self.buffer_res: list[np.ndarray] = []
        self.buffer_w: list[float] = []
        self.fitted = False

    def record_episode(
        self,
        obs_or_x: dict[str, Any] | np.ndarray | list[float],
        skill: str,
        residual_offset: tuple[float, float, float] | list[float] = (0.0, 0.0, 0.0),
        human_intervention: bool = False,
        weight: float | None = None,
    ) -> None:
        x = extract_feature_vector_20d(obs_or_x) if isinstance(obs_or_x, dict) else np.asarray(obs_or_x, dtype=np.float64)
        s_idx = self.skills.index(skill) if skill in self.skills else 0
        dx = float(np.clip(residual_offset[0], *RESIDUAL_BOUNDS["dx_mm"]))
        dy = float(np.clip(residual_offset[1], *RESIDUAL_BOUNDS["dy_mm"]))
        dyaw = float(np.clip(residual_offset[2], *RESIDUAL_BOUNDS["dyaw_deg"]))
        w = float(weight) if weight is not None else (self.human_weight if human_intervention else self.normal_weight)
        self.buffer_X.append(x)
        self.buffer_skill.append(s_idx)
        self.buffer_res.append(np.array([dx, dy, dyaw], dtype=np.float64))
        self.buffer_w.append(w)

    def fit(self, epochs: int = 100, lr: float = 0.10, l2: float = 1e-3, huber_delta: float = 2.0) -> "InterventionWeightedLearner":
        if not self.buffer_X:
            return self
        X_mat = np.vstack(self.buffer_X)
        n = X_mat.shape[0]
        self.mean = np.mean(X_mat, axis=0)
        std = np.std(X_mat, axis=0)
        self.scale = np.where(std > 1e-6, std, 1.0)
        Z = (X_mat - self.mean) / self.scale

        Y_onehot = np.eye(len(self.skills), dtype=np.float64)[np.asarray(self.buffer_skill, dtype=np.int64)]
        Y_res = np.vstack(self.buffer_res)
        w = np.asarray(self.buffer_w, dtype=np.float64)
        w_norm = w / max(np.mean(w), 1e-8)

        self.W_skill = np.zeros((Z.shape[1], len(self.skills)), dtype=np.float64)
        self.b_skill = np.zeros(len(self.skills), dtype=np.float64)
        self.W_res = np.zeros((Z.shape[1], 3), dtype=np.float64)
        self.b_res = np.zeros(3, dtype=np.float64)

        for _ in range(int(epochs)):
            probs = _softmax(Z @ self.W_skill + self.b_skill)
            diff_s = (probs - Y_onehot) * w_norm[:, None]
            self.W_skill -= lr * ((Z.T @ diff_s) / n + l2 * self.W_skill)
            self.b_skill -= lr * np.mean(diff_s, axis=0)

            err_r = (Z @ self.W_res + self.b_res) - Y_res
            huber_grad = np.where(np.abs(err_r) <= huber_delta, err_r, huber_delta * np.sign(err_r)) * w_norm[:, None]
            self.W_res -= lr * ((Z.T @ huber_grad) / n + l2 * self.W_res)
            self.b_res -= lr * np.mean(huber_grad, axis=0)

        self.fitted = True
        return self

    def predict(
        self,
        obs_or_x: dict[str, Any] | np.ndarray | list[float],
        allowed_skills: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        x = extract_feature_vector_20d(obs_or_x) if isinstance(obs_or_x, dict) else np.asarray(obs_or_x, dtype=np.float64)
        z = (x - self.mean) / self.scale
        probs = _softmax((z @ self.W_skill + self.b_skill)[None, :])[0]
        allowed = set(allowed_skills) if allowed_skills else set(self.skills)
        scored = [(probs[i], s) for i, s in enumerate(self.skills) if s in allowed]
        best_skill = max(scored, key=lambda item: item[0])[1] if scored else self.skills[0]

        raw_res = z @ self.W_res + self.b_res
        dx_mm = float(np.clip(raw_res[0], *RESIDUAL_BOUNDS["dx_mm"]))
        dy_mm = float(np.clip(raw_res[1], *RESIDUAL_BOUNDS["dy_mm"]))
        dyaw_deg = float(np.clip(raw_res[2], *RESIDUAL_BOUNDS["dyaw_deg"]))
        return {
            "skill": best_skill,
            "skill_probs": {s: float(round(probs[i], 6)) for i, s in enumerate(self.skills)},
            "dx_mm": round(dx_mm, 4),
            "dy_mm": round(dy_mm, 4),
            "dyaw_deg": round(dyaw_deg, 4),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "skills": list(self.skills), "human_weight": self.human_weight, "normal_weight": self.normal_weight,
            "mean": self.mean.tolist(), "scale": self.scale.tolist(),
            "W_skill": self.W_skill.tolist(), "b_skill": self.b_skill.tolist(),
            "W_res": self.W_res.tolist(), "b_res": self.b_res.tolist(), "fitted": self.fitted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InterventionWeightedLearner":
        obj = cls(
            skills=tuple(data.get("skills", SKILLS)),
            human_weight=float(data.get("human_weight", 5.0)),
            normal_weight=float(data.get("normal_weight", 1.0)),
        )
        obj.mean = np.asarray(data["mean"], dtype=np.float64)
        obj.scale = np.asarray(data["scale"], dtype=np.float64)
        obj.W_skill = np.asarray(data["W_skill"], dtype=np.float64)
        obj.b_skill = np.asarray(data["b_skill"], dtype=np.float64)
        obj.W_res = np.asarray(data["W_res"], dtype=np.float64)
        obj.b_res = np.asarray(data["b_res"], dtype=np.float64)
        obj.fitted = bool(data.get("fitted", True))
        return obj

    def save(self, path: Path | str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path | str) -> "InterventionWeightedLearner":
        return cls.from_dict(json.loads(Path(path).read_text()))
