"""Subject: open a learned lane model and swap it without a restart (D-356).

LaneSegModel  manifest + sha256 + session + warm-up shape check -> infer()
ModelSlot     pointer file -> current model; a failed swap keeps the old one

onnxruntime is imported lazily so the rest of sensing never needs it. On the
device it lives in its own prefix (D-373 decision 1, LEARNED_SITE), appended to
sys.path just before that import so system packages keep precedence."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .drivable_paint import drivable_target
from .lane_mask import LaneMaskEvidence, lane_evidence, lane_marking_mask, preprocess, uncrop_logits
from .manifest import MANIFEST_NAME, ManifestError, ModelManifest, load_manifest, verify_files


# learned-perception-requirements.txt is installed with pip --target here by the
# image and the bench install; ROSY_LEARNED_SITE overrides it.
LEARNED_SITE = "/opt/rosy/learned-perception/site-packages"


def add_learned_site(path: list | None = None) -> str | None:
    """Append the learned-perception prefix to `path` (sys.path) if it exists and
    is not there yet. Appended, never prepended: numpy, protobuf and packaging
    keep resolving from the system; only what the system lacks (onnxruntime)
    comes from the prefix. Returns the prefix, or None when it does not exist."""
    path = sys.path if path is None else path
    site = os.environ.get("ROSY_LEARNED_SITE") or LEARNED_SITE
    if not os.path.isdir(site):
        return None
    if site not in path:
        path.append(site)
    return site


@dataclass(frozen=True)
class InferResult:
    evidence: LaneMaskEvidence
    latency_ms: float
    model_revision: str


class _OrtSession:
    def __init__(self, path: Path, threads: int, allow_spinning: bool = True, *,
                 inter_op: int | None = None, config: dict | None = None):
        add_learned_site()
        import onnxruntime as ort  # lazy: optional on the device image
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        if not allow_spinning:
            # Idle pool threads sleep instead of busy-waiting: ~15 % less CPU on the Pi (D-408).
            opts.inter_op_num_threads = 1
            opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
            opts.add_session_config_entry("session.inter_op.allow_spinning", "0")
        if inter_op is not None:
            opts.inter_op_num_threads = inter_op
        for key, value in (config or {}).items():
            opts.add_session_config_entry(key, value)
        self._s = ort.InferenceSession(str(path), sess_options=opts,
                                       providers=["CPUExecutionProvider"])
        self._in = self._s.get_inputs()[0].name

    def run(self, x: np.ndarray) -> np.ndarray:
        return self._s.run(None, {self._in: x})[0]


class LaneSegModel:
    def __init__(self, manifest: ModelManifest, session, *, floor_gate: bool = False):
        self.manifest = manifest
        self._session = session
        self.floor_gate = floor_gate   # D-588: paint masks drop lane pixels on walls

    @property
    def model_revision(self) -> str:
        return self.manifest.model_revision

    @classmethod
    def open(cls, folder, *, session_factory: Callable | None = None,
             threads: int = 2, allow_spinning: bool = True, floor_gate: bool = False) -> "LaneSegModel":
        manifest = load_manifest(folder)
        verify_files(manifest)
        if floor_gate and not any(c.role == "wall" for c in manifest.classes):
            # D-588 fail closed: no wall class, no gated paint (the keeper uses its fallback).
            raise ManifestError("floor gate needs a wall role class; this model has none")
        factory = session_factory or (lambda p, t: _OrtSession(p, t, allow_spinning))
        try:
            if session_factory is None and manifest.backend == "ncnn":
                from .ncnn_session import NcnnSession
                session = NcnnSession(manifest, threads)
            else:
                session = factory(manifest.onnx_file(), threads)
        except ManifestError:
            raise
        except Exception as exc:
            raise ManifestError(f"session: {exc}") from exc
        model = cls(manifest, session, floor_gate=floor_gate)
        spec = manifest.input
        out = session.run(np.zeros(spec.shape, np.float32))
        expected = (1, len(manifest.classes), spec.height, spec.width)  # crop rows only, if cropped
        if tuple(out.shape) != expected:
            raise ManifestError(f"output shape {tuple(out.shape)} != {expected}")
        if not np.isfinite(out).all():
            raise ManifestError("warm-up produced non-finite logits")
        return model

    def _logits(self, bgr: np.ndarray) -> np.ndarray:
        """Logits on the full (resized) frame grid; a cropped-input model's are uncropped."""
        spec = self.manifest.input
        return uncrop_logits(self._session.run(preprocess(bgr, spec)), spec, self.manifest.classes)

    def infer(self, bgr: np.ndarray) -> InferResult:
        t0 = time.perf_counter()
        logits = self._logits(bgr)
        evidence = lane_evidence(logits, self.manifest.classes)
        return InferResult(evidence, (time.perf_counter() - t0) * 1000.0,
                           self.manifest.model_revision)

    def infer_mask(self, bgr: np.ndarray) -> tuple[np.ndarray, float]:
        """Only the lane_marking mask at the frame's size and the latency in ms: the D-408
        paint path, which has no use for lane_evidence (8.7 ms on the Pi)."""
        t0 = time.perf_counter()
        logits = self._logits(bgr)
        mask = lane_marking_mask(logits, self.manifest.classes, size=(bgr.shape[1], bgr.shape[0]),
                                 floor_gate=self.floor_gate)
        return mask, (time.perf_counter() - t0) * 1000.0

    def infer_drivable(self, bgr: np.ndarray) -> tuple[np.ndarray, str, dict, float]:
        """(mask at the frame's size, kind, info, latency ms) from one inference for keep mode with
        learned_paint_target drivable: the drivable way (drivable_paint.drivable_target, kind
        "drivable"), or the lane_marking mask (kind "lane_marking") when the model has no
        drivable class or too little of it is near; info says which and why. Rows above a
        cropped model's input (manifest input.crop) are never drivable. With a class named
        `crosswalk`, info["crosswalk_mask"] is its mask at the frame's size (the D-491 crosswalk
        extent, D-597 amendment); the paint worker takes it out of info."""
        t0 = time.perf_counter()
        logits = self._logits(bgr)
        spec, size = self.manifest.input, (bgr.shape[1], bgr.shape[0])
        way, info = drivable_target(logits, self.manifest.classes,
                                    ignore_top=spec.crop[2] if spec.crop is not None else 0)
        if way is None:
            mask, kind = lane_marking_mask(logits, self.manifest.classes, size=size), "lane_marking"
        else:
            mask, kind = cv2.resize(way.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST), "drivable"
        crosswalk = [c.index for c in self.manifest.classes if c.name == "crosswalk"]
        if crosswalk:
            info["crosswalk_mask"] = cv2.resize((logits[0].argmax(axis=0) == crosswalk[0]).astype(np.uint8),
                                                size, interpolation=cv2.INTER_NEAREST)
        return mask, kind, info, (time.perf_counter() - t0) * 1000.0

    def infer_with_mask(self, bgr: np.ndarray) -> tuple[InferResult, np.ndarray]:
        """Shadow evidence plus the lane_marking mask at the frame's size, from one
        inference: the D-408 learned paint input of the lane keeper."""
        t0 = time.perf_counter()
        logits = self._logits(bgr)
        evidence = lane_evidence(logits, self.manifest.classes)
        mask = lane_marking_mask(logits, self.manifest.classes, size=(bgr.shape[1], bgr.shape[0]),
                                 floor_gate=self.floor_gate)
        return (InferResult(evidence, (time.perf_counter() - t0) * 1000.0, self.manifest.model_revision),
                mask)


class ModelSlot:
    """Pointer file (text: a model folder path) -> the current model."""

    def __init__(self, pointer: str | Path, *, opener: Callable = LaneSegModel.open,
                 clock: Callable[[], float] = time.monotonic, poll_s: float = 2.0):
        self._pointer = Path(pointer)
        self._opener = opener
        self._clock = clock
        self._poll_s = poll_s
        self._next_poll = float("-inf")
        self._key: tuple | None = None
        self._failed: tuple[tuple, float] | None = None  # (key, retry not before)
        self.current: LaneSegModel | None = None
        self.last_error: str | None = None

    def poll(self) -> LaneSegModel | None:
        now = self._clock()
        if now < self._next_poll:
            return self.current
        self._next_poll = now + self._poll_s
        try:
            target = self._pointer.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return self.current
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            self.last_error = f"pointer: {exc}"
            return self.current
        if not target:
            return self.current
        try:
            mtime = (Path(target) / MANIFEST_NAME).stat().st_mtime_ns
        except (OSError, ValueError):
            mtime = None
        key = (target, mtime)
        if key == self._key:
            if self.last_error and self.last_error.startswith("pointer:"):
                self.last_error = None  # the pointer reads fine again
            return self.current
        if self._failed and self._failed[0] == key and now < self._failed[1]:
            return self.current  # same target still backing off
        self._key = key
        try:
            self.current = self._opener(Path(target))
            self.last_error = None
            self._failed = None
        except Exception as exc:  # keep the previous model on any failure
            self.last_error = str(exc)
            self._key = None  # retry, but not before the back-off
            self._failed = (key, now + self._poll_s * 5)
        return self.current
