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

import numpy as np

from .lane_mask import LaneMaskEvidence, lane_evidence, lane_marking_mask, preprocess
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
    def __init__(self, path: Path, threads: int, *, inter_op: int | None = None,
                 config: dict | None = None):
        add_learned_site()
        import onnxruntime as ort  # lazy: optional on the device image
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
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
    def __init__(self, manifest: ModelManifest, session):
        self.manifest = manifest
        self._session = session

    @property
    def model_revision(self) -> str:
        return self.manifest.model_revision

    @classmethod
    def open(cls, folder, *, session_factory: Callable | None = None,
             threads: int = 2) -> "LaneSegModel":
        manifest = load_manifest(folder)
        verify_files(manifest)
        factory = session_factory or (lambda p, t: _OrtSession(p, t))
        try:
            session = factory(manifest.onnx_file(), threads)
        except ManifestError:
            raise
        except Exception as exc:
            raise ManifestError(f"session: {exc}") from exc
        model = cls(manifest, session)
        spec = manifest.input
        out = session.run(np.zeros(spec.shape, np.float32))
        expected = (1, len(manifest.classes), spec.height, spec.width)
        if tuple(out.shape) != expected:
            raise ManifestError(f"output shape {tuple(out.shape)} != {expected}")
        if not np.isfinite(out).all():
            raise ManifestError("warm-up produced non-finite logits")
        return model

    def infer(self, bgr: np.ndarray) -> InferResult:
        t0 = time.perf_counter()
        logits = self._session.run(preprocess(bgr, self.manifest.input))
        evidence = lane_evidence(logits, self.manifest.classes)
        return InferResult(evidence, (time.perf_counter() - t0) * 1000.0,
                           self.manifest.model_revision)

    def infer_with_mask(self, bgr: np.ndarray) -> tuple[InferResult, np.ndarray]:
        """Shadow evidence plus the lane_marking mask at the frame's size, from one
        inference: the D-408 learned paint input of the lane keeper."""
        t0 = time.perf_counter()
        logits = self._session.run(preprocess(bgr, self.manifest.input))
        evidence = lane_evidence(logits, self.manifest.classes)
        mask = lane_marking_mask(logits, self.manifest.classes, size=(bgr.shape[1], bgr.shape[0]))
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
