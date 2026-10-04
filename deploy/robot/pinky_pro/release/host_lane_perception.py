"""Fixed-path observer configuration, admitted only by fresh stopped evidence."""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

PAINT_SOURCES = frozenset({"threshold", "denoise", "learned"})
MODEL_POINTER = "/var/lib/rosy/models/shadow"
NODE_KEY = "/**/line_observer_node"


def _installed_control() -> None:
    # Native isolated and merged colcon layouts; system numpy keeps precedence.
    for root in (Path("/opt/rosy/current/install/control"), Path("/opt/rosy/current/install")):
        for site in (*root.glob("lib/python*/site-packages"), *root.glob("local/lib/python*/dist-packages")):
            if str(site) not in sys.path:
                sys.path.append(str(site))


def installed_model_revision() -> str:
    _installed_control()
    from control.sensing.perception.learned.manifest import load_manifest, verify_files
    from control.sensing.perception.learned.signature import verify_manifest_signature
    pointer = Path(MODEL_POINTER)
    if pointer.stat().st_size > 4096:
        raise ValueError("model pointer too large")
    folder = Path(pointer.read_text(encoding="utf-8").strip()).resolve()
    if not folder.is_relative_to(Path("/var/lib/rosy/models")):
        raise ValueError("model pointer is outside model store")
    manifest = load_manifest(folder)
    if manifest.task != "lane_seg":
        raise ValueError("model is not lane segmentation")
    verify_manifest_signature(folder)
    verify_files(manifest)
    return manifest.model_revision


def installed_overlay_problem(data: dict) -> str | None:
    _installed_control()
    from control.ir_overlay import operator_overlay_problem
    return operator_overlay_problem(data)


def stopped_problem(data: dict) -> str | None:
    try:
        at = datetime.fromisoformat(data["written_at"])
        age = (datetime.now(timezone.utc) - at).total_seconds()
        if not 0 <= age <= 3 or data.get("schema", 0) < 2:
            return "stationary evidence is stale or unsupported"
        expected = {"robot_mode": ("IDLE",), "nav_state": ("IDLE", "ARRIVED", "CANCELED", "FAILED"),
                    "line_follow_mode": ("OFF",), "line_follow_state": ("OFF",),
                    "docking_state": (None, "UNDOCKED", "DOCKED", "CHARGING"),
                    "swarm_role": (None, "none"), "activity_kind": (None,)}
        for key, allowed in expected.items():
            if key not in data or data[key] not in allowed:
                return f"robot is busy or {key} is unknown"
        for key in ("swarm_active", "estop", "calibration_active"):
            if data.get(key) is not False:
                return f"{key} is active or unknown"
        for key, limit in (("velocity_linear", 0.01), ("velocity_angular", 0.02)):
            value = data.get(key)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or abs(value) >= limit):
                return "robot velocity is moving or unavailable"
    except (ValueError, TypeError, KeyError):
        return "stationary evidence is invalid"
    return None


@dataclass
class LanePerceptionConfig:
    overlay: Path = Path("/etc/rosy/line_observer_overrides.yaml")
    status_inputs: Path = Path("/run/rosy/status-inputs.json")
    restart: Callable[[], None] = lambda: None
    model_check: Callable[[], str] = installed_model_revision
    overlay_check: Callable[[dict], str | None] = installed_overlay_problem

    def _overlay(self) -> dict:
        if not self.overlay.exists():
            return {NODE_KEY: {"ros__parameters": {}}}
        if self.overlay.is_symlink() or self.overlay.stat().st_size > 16384:
            raise ValueError("observer overlay is unsafe or too large")
        import yaml  # python3-yaml is an explicit native-image apt dependency
        data = yaml.safe_load(self.overlay.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get(NODE_KEY, {}).get("ros__parameters"), dict):
            raise ValueError("observer overlay is invalid")
        return data

    def get(self) -> dict:
        params = self._overlay()[NODE_KEY]["ros__parameters"]
        revision, reason = None, "configuration readback; live inference source requires camera evidence"
        try:
            revision = self.model_check()
        except Exception as exc:
            reason = f"learned model unavailable: {exc}"
        return dict(paint_source=params.get("paint_source", "threshold"),
                    camera_lane_mode=params.get("camera_lane_mode", "line"),
                    model_ready=revision is not None, model_revision=revision,
                    applied=False, applied_paint_source=None, reason=reason)

    def _check_stopped(self) -> None:
        if self.status_inputs.stat().st_size > 16384:
            raise ValueError("stationary evidence too large")
        problem = stopped_problem(json.loads(self.status_inputs.read_text(encoding="utf-8")))
        if problem:
            raise ValueError(problem)

    def _replace(self, content: bytes) -> None:
        self.overlay.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".lane-perception-", dir=self.overlay.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(name, 0o644)
            os.replace(name, self.overlay)
            if hasattr(os, "O_DIRECTORY"):
                directory = os.open(self.overlay.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def set(self, paint_source: str) -> dict:
        import yaml
        if paint_source not in PAINT_SOURCES:
            raise ValueError("unknown paint_source")
        self._check_stopped()
        data = self._overlay()
        params = data[NODE_KEY]["ros__parameters"]
        # Keep is the metric lane path; preserve accepted device ground geometry.
        if paint_source != "threshold" and params.get("camera_lane_mode") != "keep":
            raise ValueError("accepted keep-mode geometry is required")
        revision = self.model_check() if paint_source == "learned" else None
        params["paint_source"] = paint_source
        if paint_source == "learned":
            params.update(learned_lane_pointer=MODEL_POINTER, learned_paint_every_n=2, learned_paint_threads=2)
        problem = self.overlay_check(data)
        if problem:
            raise ValueError(problem)
        before = self.overlay.read_bytes() if self.overlay.exists() else None
        self._check_stopped()  # after model hashing, immediately before mutation
        self._replace(yaml.safe_dump(data, sort_keys=False).encode("utf-8"))
        try:
            self.restart()
        except Exception:
            if before is None:
                self.overlay.unlink(missing_ok=True)
            else:
                self._replace(before)
            self.restart()  # restore runtime too; failure remains visible to caller
            raise
        result = self.get()
        result.update(applied=True, model_revision=revision or result["model_revision"])
        return result
