"""Subject: open a learned lane model and swap it without a restart (D-356).

LaneSegModel  manifest + sha256 + session + warm-up shape check -> infer()
ModelSlot     pointer file -> current model; a failed swap keeps the old one

onnxruntime is imported lazily so the rest of sensing never needs it."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .lane_mask import LaneMaskEvidence, lane_evidence, preprocess
from .manifest import MANIFEST_NAME, ManifestError, ModelManifest, load_manifest, verify_files


@dataclass(frozen=True)
class InferResult:
    evidence: LaneMaskEvidence
    latency_ms: float
    model_revision: str


class _OrtSession:
    def __init__(self, path: Path, threads: int):
        import onnxruntime as ort  # lazy: optional on the device image
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
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
            return self.current
        self._key = key
        try:
            self.current = self._opener(Path(target))
            self.last_error = None
        except Exception as exc:  # keep the previous model on any failure
            self.last_error = str(exc)
            self._key = None  # retry on the next poll
        return self.current
