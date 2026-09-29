# Perception learning loop — first thin lap (implementation plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry an externally trained lane-segmentation model (ONNX + manifest) through intake, delivery and shadow inference on the robot, and carry robot recordings back into a versioned dataset — one thin lap of the loop in [the design](2026-09-30-perception-learning-loop-design.md) (D-356, Proposed).

**Architecture:** ROS-free modules under `src/runtime/sensing/control/sensing/perception/learned/` own the model contract (manifest), pre/post-processing, the ONNX runner and the hot-swap slot; a thin ROS node publishes shadow results on `perception/learned/shadow` that no control path reads. Off-robot CLIs under `tools/perception/{dataset,model,training}/` own extract → prelabel → build → publish and export → intake → deliver. Weights never enter `src/`; artifacts live in `data/perception/` (gitignored) and `/var/lib/rosy/{models,recordings}` on the robot.

**Tech Stack:** Python 3.12 (reference; host may be newer), numpy, OpenCV, onnxruntime (optional import), onnx (tests/tools only), huggingface_hub (tools only, optional import), mcap (tools only, optional import), rclpy (node only), rosbag2 MCAP.

**Worktree:** `.worktrees/perception-learning-loop`, branch `feat/perception-learning-loop`. Other sessions commit on `main` concurrently — commit only the paths named in each task, never `git add -A`.

**Test command (from worktree root):**
`python -m pytest src/runtime/sensing/test/<file> -q` and `python -m pytest tools/perception/test/<file> -q`.
Optional-dependency tests use `pytest.importorskip("onnxruntime")` / `("onnx")`; Task 10 runs them for real in a Python 3.12 venv so they are not silently skipped evidence.

---

## File structure

| File | Responsibility |
|---|---|
| `src/runtime/sensing/control/sensing/perception/learned/__init__.py` | Package marker; no re-exports beyond `__all__` of the modules |
| `.../learned/manifest.py` | `rosy.perception.model/1` schema: dataclasses, `load_manifest`, `verify_files` |
| `.../learned/lane_mask.py` | `preprocess(bgr, spec)`, `lane_evidence(logits, classes)` → `LaneMaskEvidence` |
| `.../learned/runner.py` | `LaneSegModel` (manifest + session + infer), `ModelSlot` (pointer file hot-swap with keep-previous) |
| `.../learned/shadow.py` | `shadow_payload(...)` wire dict for `perception/learned/shadow` |
| `src/runtime/sensing/control/learned_lane_node.py` | rclpy node: camera → `ModelSlot` → shadow JSON |
| `src/runtime/sensing/control/recording.py` | ROS-free recording sessions: quota, `session.json`, bag command line |
| `src/runtime/sensing/control/record_session.py` | CLI wrapper that runs `ros2 bag record` for one session |
| `src/runtime/sensing/launch/learned_lane.launch.py` | Starts the shadow node (off unless launched) |
| `src/runtime/sensing/setup.py` | Two new console scripts |
| `tools/perception/dataset/{frames.py,extract.py,harvest.py,prelabel.py,build.py,publish.py}` | Dataset CLIs |
| `tools/perception/model/{export_onnx.py,intake.py,deliver.py,intake_gate.yaml}` | Model CLIs |
| `tools/perception/training/{README.md,check_manifest.py,export_cell.py}` | Contract for external trainers |
| `tools/perception/test/test_*.py` | Host tests for the tools |

---

### Task 1: Model manifest contract

**Files:**
- Create: `src/runtime/sensing/control/sensing/perception/learned/__init__.py`
- Create: `src/runtime/sensing/control/sensing/perception/learned/manifest.py`
- Test: `src/runtime/sensing/test/test_learned_manifest.py`

- [ ] **Step 1: Write the failing test**

```python
"""D-356 model manifest: the only contract between external training and the robot."""

import hashlib
import json

import pytest

from control.sensing.perception.learned.manifest import (
    ManifestError,
    ROLES,
    load_manifest,
    verify_files,
)


def _manifest(**over):
    doc = {
        "schema": "rosy.perception.model/1",
        "model_revision": "lane-seg-20260930-abcdef12",
        "task": "lane_seg",
        "files": [{"name": "model.onnx", "sha256": "0" * 64, "precision": "fp32"}],
        "input": {"shape": [1, 3, 240, 320], "color": "rgb", "scale": 1 / 255,
                  "mean": [0.0, 0.0, 0.0], "std": [1.0, 1.0, 1.0], "layout": "nchw"},
        "output": {"layout": "nchw_logits", "classes": [
            {"index": 0, "name": "floor", "role": "background"},
            {"index": 1, "name": "line", "role": "lane_marking"},
        ]},
        "dataset": {"repo": "org/rosy-lane-seg-data", "revision": "a" * 40},
        "camera_profile_revision": "cam-rev-1",
        "metrics": {"val_iou": {"line": 0.8}},
        "trainer": "colab:lane_unet.ipynb@2026-09-30",
    }
    doc.update(over)
    return doc


def _write(tmp_path, doc):
    p = tmp_path / "model_manifest.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_valid_manifest_loads(tmp_path):
    m = load_manifest(_write(tmp_path, _manifest()))
    assert m.model_revision == "lane-seg-20260930-abcdef12"
    assert m.input.shape == (1, 3, 240, 320)
    assert m.role_indices("lane_marking") == (1,)
    assert m.onnx_file().name == "model.onnx"


@pytest.mark.parametrize("patch", [
    {"schema": "rosy.perception.model/2"},
    {"task": "detection"},
    {"model_revision": ""},
    {"files": []},
    {"input": {"shape": [1, 3, 240], "color": "rgb", "scale": 1, "mean": [0, 0, 0],
               "std": [1, 1, 1], "layout": "nchw"}},
    {"input": {"shape": [1, 3, 240, 320], "color": "hsv", "scale": 1, "mean": [0, 0, 0],
               "std": [1, 1, 1], "layout": "nchw"}},
    {"input": {"shape": [1, 3, 240, 320], "color": "rgb", "scale": 1, "mean": [0, 0, 0],
               "std": [1, 0, 1], "layout": "nchw"}},
])
def test_invalid_top_level_rejected(tmp_path, patch):
    with pytest.raises(ManifestError):
        load_manifest(_write(tmp_path, _manifest(**patch)))


def test_unknown_role_rejected(tmp_path):
    doc = _manifest()
    doc["output"]["classes"][1]["role"] = "lane"
    with pytest.raises(ManifestError, match="role"):
        load_manifest(_write(tmp_path, doc))


def test_missing_lane_marking_rejected(tmp_path):
    doc = _manifest()
    doc["output"]["classes"][1]["role"] = "drivable"
    with pytest.raises(ManifestError, match="lane_marking"):
        load_manifest(_write(tmp_path, doc))


def test_class_indices_must_be_dense(tmp_path):
    doc = _manifest()
    doc["output"]["classes"][1]["index"] = 2
    with pytest.raises(ManifestError, match="index"):
        load_manifest(_write(tmp_path, doc))


def test_roles_are_closed():
    assert ROLES == ("background", "lane_marking", "drivable", "stop_line", "ignore")


def test_verify_files_checks_sha256(tmp_path):
    data = b"onnx-bytes"
    (tmp_path / "model.onnx").write_bytes(data)
    doc = _manifest(files=[{"name": "model.onnx",
                            "sha256": hashlib.sha256(data).hexdigest(),
                            "precision": "fp32"}])
    m = load_manifest(_write(tmp_path, doc))
    verify_files(m)  # no raise
    (tmp_path / "model.onnx").write_bytes(b"tampered")
    with pytest.raises(ManifestError, match="sha256"):
        verify_files(m)


def test_file_names_cannot_escape_the_folder(tmp_path):
    doc = _manifest(files=[{"name": "../x.onnx", "sha256": "0" * 64, "precision": "fp32"}])
    with pytest.raises(ManifestError, match="name"):
        load_manifest(_write(tmp_path, doc))
```

- [ ] **Step 2: Run it and see it fail**

Run: `python -m pytest src/runtime/sensing/test/test_learned_manifest.py -q`
Expected: FAIL, `ModuleNotFoundError: control.sensing.perception.learned`.

- [ ] **Step 3: Implement**

`__init__.py`:

```python
"""D-356 learned perception backend: model contract, pre/post-processing,
ONNX runner. ROS-free. Weights never live in src/ (D-209)."""
```

`manifest.py`:

```python
"""Subject: the rosy.perception.model/1 manifest (D-356).

The only contract between an external trainer and the robot. A model folder
holds model_manifest.json plus the files it names; anything that does not
validate is refused (fail-closed, D-199)."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "rosy.perception.model/1"
TASKS = ("lane_seg",)
ROLES = ("background", "lane_marking", "drivable", "stop_line", "ignore")
COLORS = ("rgb", "bgr")
PRECISIONS = ("fp32", "int8")
MANIFEST_NAME = "model_manifest.json"


class ManifestError(ValueError):
    """The manifest or a file it names is not acceptable."""


@dataclass(frozen=True)
class ModelFile:
    name: str
    sha256: str
    precision: str


@dataclass(frozen=True)
class InputSpec:
    shape: tuple[int, int, int, int]
    color: str
    scale: float
    mean: tuple[float, float, float]
    std: tuple[float, float, float]

    @property
    def height(self) -> int:
        return self.shape[2]

    @property
    def width(self) -> int:
        return self.shape[3]


@dataclass(frozen=True)
class ClassSpec:
    index: int
    name: str
    role: str


@dataclass(frozen=True)
class ModelManifest:
    folder: Path
    model_revision: str
    task: str
    files: tuple[ModelFile, ...]
    input: InputSpec
    classes: tuple[ClassSpec, ...]
    dataset_repo: str
    dataset_revision: str
    camera_profile_revision: str
    raw: dict

    def role_indices(self, role: str) -> tuple[int, ...]:
        return tuple(c.index for c in self.classes if c.role == role)

    def onnx_file(self, precision: str = "fp32") -> Path:
        for f in self.files:
            if f.precision == precision and f.name.endswith(".onnx"):
                return self.folder / f.name
        raise ManifestError(f"no {precision} onnx file in manifest")


def _req(doc: dict, key: str, kind):
    value = doc.get(key)
    if not isinstance(value, kind) or isinstance(value, bool):
        raise ManifestError(f"{key}: missing or wrong type")
    return value


def _finite(values, key: str, n: int) -> tuple[float, ...]:
    if not isinstance(values, list) or len(values) != n:
        raise ManifestError(f"{key}: expected {n} numbers")
    out = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ManifestError(f"{key}: non-finite value")
        out.append(float(v))
    return tuple(out)


def _parse_input(doc: dict) -> InputSpec:
    shape = doc.get("shape")
    if (not isinstance(shape, list) or len(shape) != 4
            or not all(isinstance(s, int) and not isinstance(s, bool) and s > 0 for s in shape)
            or shape[0] != 1 or shape[1] != 3):
        raise ManifestError("input.shape: expected [1, 3, H, W]")
    if doc.get("layout") != "nchw":
        raise ManifestError("input.layout: only nchw")
    color = doc.get("color")
    if color not in COLORS:
        raise ManifestError(f"input.color: one of {COLORS}")
    (scale,) = _finite([doc.get("scale")], "input.scale", 1)
    if scale <= 0:
        raise ManifestError("input.scale must be > 0")
    mean = _finite(doc.get("mean"), "input.mean", 3)
    std = _finite(doc.get("std"), "input.std", 3)
    if any(s <= 0 for s in std):
        raise ManifestError("input.std must be > 0")
    return InputSpec(tuple(shape), color, scale, mean, std)


def _parse_classes(doc: dict) -> tuple[ClassSpec, ...]:
    if doc.get("layout") != "nchw_logits":
        raise ManifestError("output.layout: only nchw_logits")
    items = doc.get("classes")
    if not isinstance(items, list) or len(items) < 2:
        raise ManifestError("output.classes: at least two classes")
    classes = []
    for item in items:
        if not isinstance(item, dict):
            raise ManifestError("output.classes: objects only")
        index = _req(item, "index", int)
        name = _req(item, "name", str)
        role = item.get("role")
        if role not in ROLES:
            raise ManifestError(f"output.classes[{index}].role: one of {ROLES}")
        classes.append(ClassSpec(index, name, role))
    if sorted(c.index for c in classes) != list(range(len(classes))):
        raise ManifestError("output.classes: index must be dense 0..N-1")
    if not any(c.role == "lane_marking" for c in classes):
        raise ManifestError("output.classes: no lane_marking role")
    return tuple(sorted(classes, key=lambda c: c.index))


def _parse_files(items) -> tuple[ModelFile, ...]:
    if not isinstance(items, list) or not items:
        raise ManifestError("files: at least one file")
    files = []
    for item in items:
        name = _req(item, "name", str)
        if Path(name).name != name or name in ("", ".", ".."):
            raise ManifestError(f"files: bad name {name!r}")
        sha = _req(item, "sha256", str).lower()
        if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            raise ManifestError(f"files[{name}].sha256: 64 hex chars")
        precision = item.get("precision")
        if precision not in PRECISIONS:
            raise ManifestError(f"files[{name}].precision: one of {PRECISIONS}")
        files.append(ModelFile(name, sha, precision))
    return tuple(files)


def load_manifest(path: str | Path) -> ModelManifest:
    """Parse and validate. `path` is the manifest file or its folder."""
    path = Path(path)
    if path.is_dir():
        path = path / MANIFEST_NAME
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read manifest: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ManifestError(f"schema: expected {SCHEMA}")
    revision = _req(doc, "model_revision", str).strip()
    if not revision:
        raise ManifestError("model_revision: empty")
    task = doc.get("task")
    if task not in TASKS:
        raise ManifestError(f"task: one of {TASKS}")
    dataset = _req(doc, "dataset", dict)
    return ModelManifest(
        folder=path.parent,
        model_revision=revision,
        task=task,
        files=_parse_files(doc.get("files")),
        input=_parse_input(_req(doc, "input", dict)),
        classes=_parse_classes(_req(doc, "output", dict)),
        dataset_repo=_req(dataset, "repo", str),
        dataset_revision=_req(dataset, "revision", str),
        camera_profile_revision=_req(doc, "camera_profile_revision", str),
        raw=doc,
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_files(manifest: ModelManifest) -> None:
    """Every named file exists and matches its sha256."""
    for f in manifest.files:
        p = manifest.folder / f.name
        if not p.is_file():
            raise ManifestError(f"{f.name}: missing")
        if sha256_file(p) != f.sha256:
            raise ManifestError(f"{f.name}: sha256 mismatch")
```

- [ ] **Step 4: Run it and see it pass**

Run: `python -m pytest src/runtime/sensing/test/test_learned_manifest.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/runtime/sensing/control/sensing/perception/learned/__init__.py src/runtime/sensing/control/sensing/perception/learned/manifest.py src/runtime/sensing/test/test_learned_manifest.py
git commit -m "feat(perception): D-356 model manifest contract"
```

---

### Task 2: Pre-processing and lane evidence from a mask

**Files:**
- Create: `src/runtime/sensing/control/sensing/perception/learned/lane_mask.py`
- Test: `src/runtime/sensing/test/test_learned_lane_mask.py`

Evidence rule (documented in the module docstring): use the bottom 40 % of rows (near field). Target pixels are `drivable` if the manifest has that role and it covers ≥ 2 % of the band, else `lane_marking`. `error = (centroid_x − W/2) / (W/2)` clipped to [−1, 1] — positive means the lane is right of centre, the `LaneObservation` sign convention in `lane.py`. `confidence = row_coverage × mean_max_softmax_on_target`, where `row_coverage` is the fraction of band rows holding any target pixel. No target pixels → `visible=False`, `error=None`, `confidence=0`.

- [ ] **Step 1: Write the failing test**

```python
"""D-356 learned lane evidence: logits to the LaneObservation sign convention."""

import numpy as np
import pytest

from control.sensing.perception.learned.lane_mask import (
    LaneMaskEvidence,
    lane_evidence,
    preprocess,
)
from control.sensing.perception.learned.manifest import ClassSpec, InputSpec

CLASSES = (ClassSpec(0, "floor", "background"), ClassSpec(1, "line", "lane_marking"))
SPEC = InputSpec((1, 3, 240, 320), "rgb", 1 / 255, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5))


def _logits(mask: np.ndarray, n_classes: int = 2) -> np.ndarray:
    out = np.full((1, n_classes, *mask.shape), -5.0, np.float32)
    for c in range(n_classes):
        out[0, c][mask == c] = 5.0
    return out


def test_preprocess_shape_color_and_normalisation():
    bgr = np.zeros((240, 320, 3), np.uint8)
    bgr[..., 2] = 255  # red in BGR
    x = preprocess(bgr, SPEC)
    assert x.shape == (1, 3, 240, 320) and x.dtype == np.float32
    assert x[0, 0].max() == pytest.approx(1.0)   # R channel first for rgb
    assert x[0, 2].min() == pytest.approx(-1.0)  # B channel empty


def test_preprocess_resizes_other_frame_sizes():
    x = preprocess(np.zeros((480, 640, 3), np.uint8), SPEC)
    assert x.shape == (1, 3, 240, 320)


def test_centred_lane_gives_zero_error():
    mask = np.zeros((240, 320), np.int64)
    mask[:, 150:170] = 1
    ev = lane_evidence(_logits(mask), CLASSES)
    assert ev.visible and abs(ev.error) < 0.02 and ev.confidence > 0.9


def test_lane_right_of_centre_is_positive():
    mask = np.zeros((240, 320), np.int64)
    mask[:, 260:280] = 1
    ev = lane_evidence(_logits(mask), CLASSES)
    assert ev.error > 0.5


def test_no_lane_pixels_is_not_visible():
    ev = lane_evidence(_logits(np.zeros((240, 320), np.int64)), CLASSES)
    assert ev == LaneMaskEvidence(False, None, 0.0, ev.class_fractions)
    assert ev.class_fractions["floor"] == pytest.approx(1.0)


def test_only_far_field_lane_is_not_visible():
    mask = np.zeros((240, 320), np.int64)
    mask[:100, 150:170] = 1  # top rows only
    assert not lane_evidence(_logits(mask), CLASSES).visible


def test_drivable_role_preferred_when_present():
    classes = CLASSES + (ClassSpec(2, "road", "drivable"),)
    mask = np.zeros((240, 320), np.int64)
    mask[:, 0:20] = 1          # a boundary line far left
    mask[:, 200:300] = 2       # drivable area right of centre
    ev = lane_evidence(_logits(mask, 3), classes)
    assert ev.error > 0.3


def test_non_finite_logits_raise():
    bad = _logits(np.zeros((240, 320), np.int64))
    bad[0, 0, 0, 0] = np.nan
    with pytest.raises(ValueError):
        lane_evidence(bad, CLASSES)
```

- [ ] **Step 2: Run it and see it fail**

Run: `python -m pytest src/runtime/sensing/test/test_learned_lane_mask.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `lane_mask.py`**

```python
"""Subject: learned lane-segmentation logits to lane evidence (D-356).

preprocess   BGR frame -> NCHW float32 per the manifest InputSpec
lane_evidence  logits -> (visible, error, confidence, class fractions)

Evidence rule: bottom 40 % of rows (near field). Target pixels are the
`drivable` role when it covers >= 2 % of that band, else `lane_marking`.
error = (target centroid x - W/2) / (W/2), clipped to [-1, 1]; positive means
the lane is right of centre, the LaneObservation convention in lane.py.
confidence = fraction of band rows with a target pixel x mean max-softmax on
target pixels. Shadow evidence only: nothing here commands motion (D-209)."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .manifest import ClassSpec, InputSpec

NEAR_FIELD_FRACTION = 0.40
DRIVABLE_MIN_FRACTION = 0.02


@dataclass(frozen=True)
class LaneMaskEvidence:
    visible: bool
    error: float | None
    confidence: float
    class_fractions: dict


def preprocess(bgr: np.ndarray, spec: InputSpec) -> np.ndarray:
    if bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ValueError("expected an HxWx3 BGR frame")
    if bgr.shape[:2] != (spec.height, spec.width):
        bgr = cv2.resize(bgr, (spec.width, spec.height), interpolation=cv2.INTER_AREA)
    img = bgr[..., ::-1] if spec.color == "rgb" else bgr
    x = img.astype(np.float32) * np.float32(spec.scale)
    x = (x - np.asarray(spec.mean, np.float32)) / np.asarray(spec.std, np.float32)
    return np.ascontiguousarray(x.transpose(2, 0, 1)[None])


def _softmax(logits: np.ndarray) -> np.ndarray:
    z = logits - logits.max(axis=0, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=0, keepdims=True)


def lane_evidence(logits: np.ndarray, classes: tuple[ClassSpec, ...]) -> LaneMaskEvidence:
    if logits.ndim != 4 or logits.shape[0] != 1 or logits.shape[1] != len(classes):
        raise ValueError(f"logits shape {logits.shape} does not match {len(classes)} classes")
    if not np.isfinite(logits).all():
        raise ValueError("non-finite logits")
    probs = _softmax(logits[0].astype(np.float32))
    labels = probs.argmax(axis=0)
    total = labels.size
    fractions = {c.name: float((labels == c.index).sum()) / total for c in classes}

    h, w = labels.shape
    band = slice(int(h * (1 - NEAR_FIELD_FRACTION)), h)
    band_labels = labels[band]
    band_conf = probs.max(axis=0)[band]

    def _target(role: str) -> np.ndarray:
        idx = [c.index for c in classes if c.role == role]
        return np.isin(band_labels, idx) if idx else np.zeros_like(band_labels, bool)

    target = _target("drivable")
    if target.mean() < DRIVABLE_MIN_FRACTION:
        target = _target("lane_marking")
    if not target.any():
        return LaneMaskEvidence(False, None, 0.0, fractions)

    _, xs = np.nonzero(target)
    half = w / 2.0
    error = float(np.clip((xs.mean() - half) / half, -1.0, 1.0))
    row_coverage = float(target.any(axis=1).mean())
    confidence = float(np.clip(row_coverage * band_conf[target].mean(), 0.0, 1.0))
    return LaneMaskEvidence(True, error, confidence, fractions)
```

- [ ] **Step 4: Run it and see it pass** (same command).
- [ ] **Step 5: Commit** `lane_mask.py` and its test: `feat(perception): D-356 lane evidence from segmentation logits`.

---

### Task 3: ONNX runner and hot-swap slot

**Files:**
- Create: `src/runtime/sensing/control/sensing/perception/learned/runner.py`
- Test: `src/runtime/sensing/test/test_learned_runner.py`

Design: `LaneSegModel.open(folder, session_factory=None)` loads the manifest, verifies sha256, builds the session (default factory imports `onnxruntime` lazily, CPU EP, `intra_op_num_threads` from arg, default 2), checks the declared input/output shapes on one zero frame, and exposes `infer(bgr) -> InferResult(evidence, latency_ms, model_revision)`. `ModelSlot(pointer_path, opener=LaneSegModel.open, clock=time.monotonic)` reads a pointer file whose text is a model folder path; `poll()` re-reads it at most every `poll_s` (default 2.0 s); a changed path opens the new model and swaps only on success; failure keeps the current model and records `last_error`. `current` is the active model or None.

- [ ] **Step 1: Write the failing test**

```python
"""D-356 runner: sha-verified open, shape check, keep-previous hot swap."""

import hashlib
import json

import numpy as np
import pytest

from control.sensing.perception.learned.manifest import ManifestError
from control.sensing.perception.learned.runner import LaneSegModel, ModelSlot


class FakeSession:
    def __init__(self, n_classes=2, lane_col=160, nan=False):
        self.n, self.col, self.nan = n_classes, lane_col, nan

    def run(self, x):
        out = np.full((1, self.n, x.shape[2], x.shape[3]), -5.0, np.float32)
        out[0, 0] = 5.0
        out[0, 0, :, self.col - 5:self.col + 5] = -5.0
        out[0, 1, :, self.col - 5:self.col + 5] = 5.0
        if self.nan:
            out[0, 0, 0, 0] = np.nan
        return out


def _model_dir(tmp_path, name="m1", revision="lane-seg-20260930-00000001"):
    d = tmp_path / name
    d.mkdir()
    (d / "model.onnx").write_bytes(b"fake-" + name.encode())
    sha = hashlib.sha256((d / "model.onnx").read_bytes()).hexdigest()
    (d / "model_manifest.json").write_text(json.dumps({
        "schema": "rosy.perception.model/1", "model_revision": revision, "task": "lane_seg",
        "files": [{"name": "model.onnx", "sha256": sha, "precision": "fp32"}],
        "input": {"shape": [1, 3, 240, 320], "color": "rgb", "scale": 1 / 255,
                  "mean": [0, 0, 0], "std": [1, 1, 1], "layout": "nchw"},
        "output": {"layout": "nchw_logits", "classes": [
            {"index": 0, "name": "floor", "role": "background"},
            {"index": 1, "name": "line", "role": "lane_marking"}]},
        "dataset": {"repo": "org/d", "revision": "a" * 40},
        "camera_profile_revision": "cam-1"}), encoding="utf-8")
    return d


def _factory(**kw):
    return lambda path, threads: FakeSession(**kw)


def test_open_and_infer(tmp_path):
    m = LaneSegModel.open(_model_dir(tmp_path), session_factory=_factory())
    r = m.infer(np.zeros((240, 320, 3), np.uint8))
    assert r.model_revision == "lane-seg-20260930-00000001"
    assert r.evidence.visible and abs(r.evidence.error) < 0.05
    assert r.latency_ms >= 0


def test_open_refuses_tampered_file(tmp_path):
    d = _model_dir(tmp_path)
    (d / "model.onnx").write_bytes(b"other")
    with pytest.raises(ManifestError):
        LaneSegModel.open(d, session_factory=_factory())


def test_open_refuses_wrong_class_count(tmp_path):
    with pytest.raises(ManifestError, match="output"):
        LaneSegModel.open(_model_dir(tmp_path), session_factory=_factory(n_classes=3))


def test_open_refuses_nan_warmup(tmp_path):
    with pytest.raises(ManifestError, match="warm-up"):
        LaneSegModel.open(_model_dir(tmp_path), session_factory=_factory(nan=True))


def test_slot_swaps_and_keeps_previous_on_failure(tmp_path):
    good = _model_dir(tmp_path, "m1", "lane-seg-20260930-00000001")
    good2 = _model_dir(tmp_path, "m2", "lane-seg-20260930-00000002")
    bad = _model_dir(tmp_path, "m3", "lane-seg-20260930-00000003")
    (bad / "model.onnx").write_bytes(b"tampered")
    pointer = tmp_path / "shadow"
    now = [0.0]
    slot = ModelSlot(pointer, opener=lambda p: LaneSegModel.open(p, session_factory=_factory()),
                     clock=lambda: now[0], poll_s=1.0)

    assert slot.poll() is None and slot.current is None       # no pointer yet
    pointer.write_text(str(good), encoding="utf-8")
    now[0] = 1.0
    assert slot.poll().model_revision.endswith("01")
    pointer.write_text(str(bad), encoding="utf-8")
    now[0] = 2.0
    assert slot.poll().model_revision.endswith("01")           # kept
    assert "sha256" in slot.last_error
    pointer.write_text(str(good2), encoding="utf-8")
    now[0] = 2.5
    assert slot.poll().model_revision.endswith("01")           # rate-limited
    now[0] = 3.0
    assert slot.poll().model_revision.endswith("02")
    assert slot.last_error is None


def test_real_onnxruntime_roundtrip(tmp_path):
    ort = pytest.importorskip("onnxruntime")
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper
    # 1x1 conv 3->2 channels: class 1 logit = R channel, class 0 = constant 0.5
    w = np.zeros((2, 3, 1, 1), np.float32)
    w[1, 0, 0, 0] = 1.0
    b = np.array([0.5, 0.0], np.float32)
    graph = helper.make_graph(
        [helper.make_node("Conv", ["x", "w", "b"], ["y"])], "g",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, 240, 320])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 2, 240, 320])],
        [helper.make_tensor("w", TensorProto.FLOAT, w.shape, w.flatten()),
         helper.make_tensor("b", TensorProto.FLOAT, b.shape, b)])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    d = _model_dir(tmp_path)
    onnx.save(model, d / "model.onnx")
    doc = json.loads((d / "model_manifest.json").read_text())
    doc["files"][0]["sha256"] = hashlib.sha256((d / "model.onnx").read_bytes()).hexdigest()
    (d / "model_manifest.json").write_text(json.dumps(doc))
    m = LaneSegModel.open(d)
    frame = np.zeros((240, 320, 3), np.uint8)
    frame[:, 250:270, 2] = 255  # red stripe right of centre
    assert m.infer(frame).evidence.error > 0.5
```

- [ ] **Step 2: Run it and see it fail** → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `runner.py`**

```python
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
from .manifest import ManifestError, ModelManifest, load_manifest, verify_files


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
        self._target: str | None = None
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
        if not target or target == self._target:
            return self.current
        self._target = target
        try:
            self.current = self._opener(Path(target))
            self.last_error = None
        except Exception as exc:  # keep the previous model on any failure
            self.last_error = str(exc)
        return self.current
```

- [ ] **Step 4: Run it and see it pass.** (`test_real_onnxruntime_roundtrip` skips when onnx/onnxruntime are absent on this host; Task 10 runs it for real.)
- [ ] **Step 5: Commit** `runner.py` and its test: `feat(perception): D-356 ONNX runner with keep-previous hot swap`.

---

### Task 4: Shadow payload and the shadow node

**Files:**
- Create: `src/runtime/sensing/control/sensing/perception/learned/shadow.py`
- Create: `src/runtime/sensing/control/learned_lane_node.py`
- Create: `src/runtime/sensing/launch/learned_lane.launch.py`
- Modify: `src/runtime/sensing/setup.py` (console_scripts: add `'learned_lane_node = control.learned_lane_node:main',`)
- Test: `src/runtime/sensing/test/test_learned_shadow.py`

- [ ] **Step 1: Write the failing test**

```python
"""D-356 shadow wire shape: evidence only, never a command."""

import json

from control.sensing.perception.learned.lane_mask import LaneMaskEvidence
from control.sensing.perception.learned.runner import InferResult
from control.sensing.perception.learned.shadow import SHADOW_SCHEMA, shadow_payload


def test_payload_fields_and_json_roundtrip():
    r = InferResult(LaneMaskEvidence(True, 0.25, 0.8, {"floor": 0.9, "line": 0.1}),
                    87.5, "lane-seg-20260930-00000001")
    p = shadow_payload(r, stamp=12.5, rule_error=0.1)
    assert p == {
        "schema": SHADOW_SCHEMA, "stamp": 12.5, "model_revision": "lane-seg-20260930-00000001",
        "visible": True, "error": 0.25, "confidence": 0.8, "latency_ms": 87.5,
        "class_fractions": {"floor": 0.9, "line": 0.1},
        "rule_error": 0.1, "error_delta": 0.15,
    }
    json.dumps(p)


def test_payload_without_rule_or_lane():
    r = InferResult(LaneMaskEvidence(False, None, 0.0, {}), 90.0, "rev")
    p = shadow_payload(r, stamp=1.0, rule_error=None)
    assert p["error"] is None and p["error_delta"] is None and p["rule_error"] is None


def test_payload_has_no_command_fields():
    r = InferResult(LaneMaskEvidence(True, 0.0, 1.0, {}), 1.0, "rev")
    keys = set(shadow_payload(r, stamp=0.0, rule_error=None))
    assert not keys & {"linear", "angular", "cmd_vel", "twist"}
```

- [ ] **Step 2: Run it and see it fail.**

- [ ] **Step 3: Implement `shadow.py`**

```python
"""Subject: the perception/learned/shadow wire shape (D-356).

Shadow evidence has no consumer in the control path. It carries the model's
lane error next to the rule-based one so disagreement can be logged and later
used as a recording trigger and as replay-gate input (D-205)."""

from __future__ import annotations

from .runner import InferResult

SHADOW_SCHEMA = "rosy.perception.learned_shadow/1"
TOPIC = "perception/learned/shadow"


def shadow_payload(result: InferResult, *, stamp: float, rule_error: float | None) -> dict:
    ev = result.evidence
    delta = (round(ev.error - rule_error, 6)
             if ev.visible and ev.error is not None and rule_error is not None else None)
    return {
        "schema": SHADOW_SCHEMA,
        "stamp": float(stamp),
        "model_revision": result.model_revision,
        "visible": ev.visible,
        "error": ev.error,
        "confidence": ev.confidence,
        "latency_ms": round(result.latency_ms, 3),
        "class_fractions": dict(ev.class_fractions),
        "rule_error": rule_error,
        "error_delta": delta,
    }
```

- [ ] **Step 4: Implement `learned_lane_node.py`** (not host-testable; keep it thin and mirror `line_observer_node.py` for Image decoding — read that file's `_on_camera` for the exact `sensor_msgs/Image` → BGR conversion helper already used there and reuse it).

```python
"""learned_lane_node — shadow inference of a learned lane model (D-356).

Subscribes camera/front (sensor_msgs/Image) and line/observation (rule-based
CAMERA_LINE error for comparison). Publishes perception/learned/shadow
(std_msgs/String JSON). No consumer in the control path reads it; this node
never publishes cmd_vel (D-2, D-209). The model comes from the pointer file
/var/lib/rosy/models/shadow (parameter `pointer`) and swaps without restart."""

import json

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

from .sensing.perception.learned.runner import ModelSlot
from .sensing.perception.learned.shadow import TOPIC, shadow_payload


class LearnedLaneNode(Node):
    def __init__(self):
        super().__init__('learned_lane_node')
        pointer = self.declare_parameter('pointer', '/var/lib/rosy/models/shadow').value
        self._slot = ModelSlot(pointer)
        self._busy = False
        self._rule_error = None
        self._missing_logged = False
        self._pub = self.create_publisher(String, TOPIC, 10)
        self.create_subscription(Image, 'camera/front', self._on_camera, 1)
        self.create_subscription(String, 'line/observation', self._on_rule, 10)

    def _on_rule(self, msg: String) -> None:
        try:
            doc = json.loads(msg.data)
        except ValueError:
            return
        if doc.get('source') == 'CAMERA_LINE':
            self._rule_error = doc.get('error') if doc.get('visible') else None

    def _on_camera(self, msg: Image) -> None:
        if self._busy:
            return  # drop frames while inferring
        model = self._slot.poll()
        if model is None:
            if not self._missing_logged:
                self.get_logger().warn(
                    f'no shadow model ({self._slot.last_error or "pointer empty"}); idle')
                self._missing_logged = True
            return
        self._missing_logged = False
        self._busy = True
        try:
            bgr = _image_to_bgr(msg)
            result = model.infer(bgr)
            stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            payload = shadow_payload(result, stamp=stamp, rule_error=self._rule_error)
            self._pub.publish(String(data=json.dumps(payload, sort_keys=True)))
        except Exception as exc:
            self.get_logger().warn(f'shadow inference failed: {exc}',
                                   throttle_duration_sec=5.0)
        finally:
            self._busy = False


def main():
    rclpy.init()
    node = LearnedLaneNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
```

`_image_to_bgr` must be the same conversion `line_observer_node.py` uses; import it from where that node gets it, or, if it is a private method there, move it into a small shared ROS-free helper module and import it from both (no behaviour change for `line_observer_node`).

`launch/learned_lane.launch.py`: a single `Node(package='control', executable='learned_lane_node', parameters=[{'pointer': LaunchConfiguration('pointer')}])` with `DeclareLaunchArgument('pointer', default_value='/var/lib/rosy/models/shadow')`. Copy the import/boilerplate style from `launch/line_follow.launch.py`. Check `setup.py` `data_files` already globs `launch/*.launch.py`; if it lists files explicitly, add this one.

- [ ] **Step 5: Run** `python -m pytest src/runtime/sensing/test/test_learned_shadow.py -q` → pass; `python -c "import ast,sys; ast.parse(open('src/runtime/sensing/control/learned_lane_node.py').read())"` → no error.
- [ ] **Step 6: Commit** the four files plus `setup.py`: `feat(perception): D-356 shadow node publishes learned lane evidence`.

---

### Task 5: Recording sessions

**Files:**
- Create: `src/runtime/sensing/control/recording.py`
- Create: `src/runtime/sensing/control/record_session.py`
- Modify: `src/runtime/sensing/setup.py` (add `'record_session = control.record_session:main',`)
- Test: `src/runtime/sensing/test/test_recording.py`

Behaviour of `recording.py` (ROS-free):
- `RECORD_TOPICS = ("camera/front/compressed", "cmd_vel", "line/observation", "perception/learned/shadow", "odom")`. Before writing it, grep the sensing and camera packages for the actual compressed front-camera topic name (`CompressedImage` publishers) and use that exact name; note the source file in a comment.
- `new_session(root, *, device, camera_profile_revision, model_revision, task_id, reason, now) -> Path`: creates `root/<YYYYmmddTHHMMSSZ>_<device>/` with `session.json` `{"schema": "rosy.recording.session/1", "device", "camera_profile_revision", "model_revision", "task_id", "reason", "started_at", "ended_at": null, "harvested": false, "topics": [...]}`. `reason` and `device` must be non-empty.
- `finish_session(folder, now)`: sets `ended_at`.
- `mark_harvested(folder)`: sets `harvested: true`.
- `enforce_quota(root, quota_bytes) -> list[Path]`: while total size > quota, delete the oldest session with `harvested: true` and a non-null `ended_at`; returns deleted folders. `can_record(root, quota_bytes) -> bool` is False when total size ≥ quota after enforcement (only unharvested sessions left).
- `bag_command(folder) -> list[str]`: `["ros2", "bag", "record", "--storage", "mcap", "--storage-preset-profile", "zstd_fast", "--max-bag-duration", "30", "-o", str(folder / "bag"), *RECORD_TOPICS]`.

`record_session.py`: argparse `--root /var/lib/rosy/recordings --quota-gib 4 --device <hostname default> --reason <required> --task-id --camera-profile-revision --model-revision`; runs `enforce_quota`, refuses with exit code 2 and a message when `can_record` is False, creates the session, runs `subprocess.run(bag_command(folder))`, and calls `finish_session` in `finally` (Ctrl-C ends the recording).

- [ ] **Step 1: Write the failing test** covering: session.json fields; empty reason rejected (`ValueError`); `finish_session` sets `ended_at`; quota deletes only harvested+ended sessions, oldest first; `can_record` False when only unharvested data exceeds quota; `bag_command` contains `mcap`, `zstd_fast` and every `RECORD_TOPICS` entry. Use `tmp_path` with sessions made by `new_session` and a filler file of known size (`(folder / "bag" / "x.mcap").write_bytes(b"0" * n)`).
- [ ] **Step 2: Run it and see it fail.**
- [ ] **Step 3: Implement both files as specified.**
- [ ] **Step 4: Run it and see it pass.**
- [ ] **Step 5: Commit**: `feat(sensing): D-356 recording sessions with harvest-aware quota`.

---

### Task 6: Frame extraction and harvest

**Files:**
- Create: `tools/perception/__init__.py` (empty, only if the tools tree needs it for imports; check `tools/perception/prototype` first and follow the same import style)
- Create: `tools/perception/dataset/frames.py`, `tools/perception/dataset/extract.py`, `tools/perception/dataset/harvest.py`
- Test: `tools/perception/test/test_dataset_extract.py`, `tools/perception/test/test_dataset_harvest.py`

`frames.py`:
- `dhash(gray: np.ndarray) -> int` (9×8 resize, horizontal gradient, 64-bit).
- `FrameSelector(min_interval_s=0.5, max_hamming=4)`: `accept(t, bgr) -> bool` rejects frames closer than `min_interval_s` to the last accepted frame or within `max_hamming` of it.

`extract.py` CLI: `extract.py <source> --out data/perception/frames/<name>` where `<source>` is an `.mp4` or a session folder containing `bag/*.mcap`.
- MP4: OpenCV `VideoCapture`, timestamps from `CAP_PROP_POS_MSEC`, frames re-encoded to JPEG q=95 (MP4 has no JPEG to keep).
- MCAP: lazy `import mcap` + `mcap_ros2.decoder` (tell the user to `pip install mcap mcap-ros2-support` if missing); read the compressed camera topic, write the JPEG bytes unchanged; keep the latest `cmd_vel`, `line/observation` and `perception/learned/shadow` messages seen before each frame as side data.
- Writes `frames/<index:06d>.jpg` and `frames.jsonl` rows `{"index", "t", "source", "session", "side": {...}}`; copies `session.json` next to them when present.

`harvest.py` CLI: `harvest.py <host> [--user pinky] [--remote-root /var/lib/rosy/recordings] [--dest data/perception/raw]`.
- Uses `ssh`/`scp` subprocesses (same as `deploy/robot/pinky_pro/rosy-release-push.ps1` relies on operator SSH). Pure helpers are testable: `sessions_to_fetch(listing: list[dict]) -> list[str]` picks sessions with non-null `ended_at` and `harvested == false`; `verify_tree(local, remote_sums: dict[str,str])` compares sha256 per relative path.
- Flow: remote `cat */session.json` listing → fetch each chosen session with `scp -r` → remote `sha256sum` vs local → on match, remote mark via `python3 -c` that sets `harvested: true` (reuse the JSON key names from `recording.py`).

- [ ] **Step 1: Tests**: `FrameSelector` accepts first frame, rejects a frame 0.1 s later, rejects an identical frame 1 s later, accepts a different frame 1 s later; `extract` on a synthetic 3-second 8 fps MP4 written with `cv2.VideoWriter` (moving white bar) produces ≤ 7 frames and a matching `frames.jsonl`; `sessions_to_fetch` filter; `verify_tree` detects one changed file.
- [ ] **Step 2: Fail. Step 3: Implement. Step 4: Pass.**
- [ ] **Step 5: Commit**: `feat(tools): D-356 frame extraction and robot harvest`.

---

### Task 7: Pre-label and dataset build

**Files:**
- Create: `tools/perception/dataset/prelabel.py`, `tools/perception/dataset/build.py`
- Test: `tools/perception/test/test_dataset_build.py`

`prelabel.py <frames_dir> --model <model_folder> --out <dir>`:
- Opens `LaneSegModel` (import from `src/runtime/sensing/control/sensing/perception/learned/runner.py` by inserting `src/runtime/sensing` on `sys.path`, the way the prototype tools reach sensing code — check `tools/perception/prototype/realrun/replay.py` and copy its approach).
- For each frame: argmax mask → palette PNG `masks/<index>.png` (mode "P" via OpenCV + palette is not supported, so write the index mask with `cv2.imwrite` as 8-bit grey and also a colour preview `preview/<index>.png`); score = `(1 − confidence) + |error_delta|` when side data has `rule_error`, else `1 − confidence`; `ranking.csv` sorted by score desc.
- Writes a CVAT "Segmentation mask 1.1" import zip `cvat_import.zip` (`SegmentationClass/<name>.png` colour masks + `labelmap.txt` built from the manifest classes with a fixed palette; `ImageSets/Segmentation/default.txt`).

`build.py <cvat_export.zip | dir> --frames <frames_dir>... --classes classes.yaml --out data/perception/datasets/<name>`:
- `classes.yaml`: `classes: [{index, name, role, color: [r,g,b]}]` — same roles as the manifest.
- Reads CVAT Segmentation mask 1.1 colour PNGs, maps colours to indices via `classes.yaml`; any unknown colour → error naming the file.
- Output: `images/<session>/<index>.jpg`, `masks/<session>/<index>.png` (8-bit class index), `manifest.json` `{"schema": "rosy.perception.dataset/1", "classes": [...], "frames": [{"image", "mask", "session", "split"}], "deleted_indexes": [], "sources": [<session.json contents>]}`.
- Split by **session**: sorted session ids, every 5th session (by sorted order) is `val`, the rest `train`; with fewer than 2 sessions, error "need at least 2 sessions for a session-level split".

- [ ] **Step 1: Tests**: colour→index mapping round trip; unknown colour raises; two sessions produce both splits and no session appears in both; one session raises; `deleted_indexes` frames are excluded from `frames`.
- [ ] **Step 2–4: Fail, implement, pass.**
- [ ] **Step 5: Commit**: `feat(tools): D-356 prelabel and session-split dataset build`.

---

### Task 8: Publish to Hugging Face and the trainer contract

**Files:**
- Create: `tools/perception/dataset/publish.py`
- Create: `tools/perception/training/README.md`, `tools/perception/training/check_manifest.py`, `tools/perception/training/export_cell.py`
- Test: `tools/perception/test/test_training_contract.py`

`publish.py <dataset_dir> --repo <org/name> [--tag ds-YYYY.MM.DD]`: lazy `from huggingface_hub import HfApi`; `create_repo(repo, repo_type="dataset", private=True, exist_ok=True)`; `upload_folder(...)` with `images/` and `masks/` sharded into subfolders of ≤ 1000 files (`shard_0000/`) — sharding is a pure function `shard_paths(paths, size=1000)` that is unit-tested; prints the resulting commit SHA (`CommitInfo.oid`) and creates the tag when given. Token comes from `HF_TOKEN` or the huggingface-cli login cache; never from a repo file.

`check_manifest.py <model_folder>`: runs `load_manifest` + `verify_files` and, if `onnxruntime` is importable, `LaneSegModel.open`; prints `OK <revision>` or the error and exits 1.

`export_cell.py`: a copy-paste Colab cell (as a Python module with a `export(model, out_dir, *, classes, color, scale, mean, std, dataset_repo, dataset_revision, camera_profile_revision, trainer, val_iou)` function) that calls `torch.onnx.export(model.eval(), torch.zeros(1,3,240,320), out_dir/"model.onnx", opset_version=17, input_names=["x"], output_names=["logits"])`, computes sha256, derives `model_revision = f"lane-seg-{date}-{sha[:8]}"` and writes `model_manifest.json` in the D-356 schema. `torch` is imported inside the function.

`README.md` (Korean prose, English identifiers): input (dataset repo + commit SHA, layout of `manifest.json`), output (`model.onnx` + `model_manifest.json` fields table copied from the design doc), the closed role list, "push the model folder to the HF model repo and hand over the commit SHA", and "run `check_manifest.py` before handing over".

- [ ] **Step 1: Tests**: `shard_paths` sizes and stable order; `check_manifest.py` exit code 0 on a valid folder (fake onnx bytes, with onnxruntime absent or monkeypatched) and 1 on a tampered file; `export_cell` module imports without torch installed (import inside function).
- [ ] **Step 2–4: Fail, implement, pass.**
- [ ] **Step 5: Commit**: `feat(tools): D-356 dataset publish and trainer contract`.

---

### Task 9: Export, intake and delivery

**Files:**
- Create: `tools/perception/model/export_onnx.py`, `tools/perception/model/intake.py`, `tools/perception/model/intake_gate.yaml`, `tools/perception/model/deliver.py`
- Test: `tools/perception/test/test_model_intake.py`, `tools/perception/test/test_model_deliver.py`

`export_onnx.py <model.torchscript.pt> --out <dir> --classes classes.yaml --color rgb --scale 0.00392156862745098 --mean 0 0 0 --std 1 1 1 --dataset-repo <r> --dataset-revision <sha> --camera-profile-revision <rev> --trainer <id>`: `torch.jit.load` → `torch.onnx.export` (opset 17, fixed shape from the traced input `1×3×240×320`); parity check: same random input through TorchScript and onnxruntime, print and store `max_abs_diff`, fail if > 1e-3; writes the manifest via the same writer as `export_cell.py` (import it, no copy). Refuses to run without `--classes` — the class roles cannot be guessed.

`intake_gate.yaml`:

```yaml
# D-356 intake: shadow-deployment eligibility only. Not the D-205 selection gate.
max_host_latency_ms_p50: 400      # dev-PC CPU; Pi numbers are measured on device
max_nan_frames: 0
min_visible_fraction: 0.30        # of replay frames with visible lane evidence
replay_sources: ["data/teleop/learning/*.mp4"]
max_frames_per_source: 200
```

`intake.py <model_folder | hf:org/repo@<40-hex sha>> --out data/perception/models`:
- `hf:` source: lazy `huggingface_hub.snapshot_download(repo_id, revision=sha)`; a revision that is not 40 hex characters is refused (tags move).
- Steps: `load_manifest` → `verify_files` → `LaneSegModel.open` → replay up to `max_frames_per_source` frames per MP4 through `infer` and, for the same frames, the rule-based `detect_lane_error` from `control.sensing.perception.lane` → report `intake_report.json` `{"model_revision", "verdict": "pass"|"fail", "reasons": [...], "latency_ms": {"p50","p95"}, "nan_frames", "visible_fraction", "error_delta": {"median","p95"}, "class_fractions_mean", "frames", "gate": <yaml contents>, "tool_commit": <git rev-parse HEAD>}`.
- On pass: copy the model folder to `<out>/<model_revision>/` together with the report. On fail: write the report next to the source and exit 1.
- Pure function `judge(stats: dict, gate: dict) -> tuple[str, list[str]]` holds the verdict logic and is unit-tested.

`deliver.py`:
- `deliver.py push <host> <model_revision> [--user pinky] [--models data/perception/models]`: refuses unless `<models>/<rev>/intake_report.json` has `verdict == "pass"`; `scp -r` to `/var/lib/rosy/models/<rev>.partial`, remote `sha256sum -c` against the manifest, remote `mv` to `/var/lib/rosy/models/<rev>`, then atomic pointer update: remote `cp shadow shadow.previous 2>/dev/null; printf %s <path> > shadow.tmp && mv shadow.tmp shadow`.
- `deliver.py rollback <host>`: remote `mv shadow.previous shadow` (refuse if absent).
- `deliver.py status <host>`: prints the pointer and installed revisions.
- Pure helper `remote_script(action, rev, root="/var/lib/rosy/models") -> str` builds the shell text and is unit-tested (quoting via `shlex.quote`, no unquoted revision).

- [ ] **Step 1: Tests**: `judge` pass/fail reasons for latency, NaN and visible-fraction; `hf:` source with a tag is refused; `remote_script("push", ...)` contains the `.partial` → final `mv` and pointer temp-file swap, and `shlex.quote`s a revision with a space; `deliver push` refuses a folder whose report verdict is `fail` (call the CLI entry function with a fake runner that records commands; assert nothing was run).
- [ ] **Step 2–4: Fail, implement, pass.**
- [ ] **Step 5: Commit**: `feat(tools): D-356 ONNX export, intake report and model delivery`.

---

### Task 10: Real-model evidence in a Python 3.12 venv

Not a code task. Produces evidence for the design's validation line.

- [ ] **Step 1:** Create the venv outside F: — `py -3.12 -m venv X:\DevTemp\rosy-ml-venv` (if 3.12 is not installed, use the newest Python that has `torch`, `onnxruntime` and `onnx` wheels and record which). Install `numpy opencv-python-headless onnx onnxruntime pyyaml pytest` and CPU `torch` (`--index-url https://download.pytorch.org/whl/cpu`).
- [ ] **Step 2:** Run every new test file in the venv; the `importorskip` tests must now run and pass. Record the pass counts.
- [ ] **Step 3:** Export the real model with a **provisional** classes file in `X:\DevTemp\rosy-ml-work\classes.provisional.yaml` (`class_0..class_3`, role `lane_marking` on the class whose mean pixel fraction on teleop frames is small but non-zero — determine it by running the TorchScript model on 20 teleop frames and printing per-class fractions). Record `max_abs_diff`. The provisional manifest stays in `X:\DevTemp`; it is not committed and not delivered.
- [ ] **Step 4:** Run `intake.py` on that folder with `--out X:\DevTemp\rosy-ml-work\models`; keep `intake_report.json`. Record host latency p50/p95 and visible fraction.
- [ ] **Step 5:** Write the numbers into the design doc's new section "첫 실행 증거 (호스트)" (host, Python version, parity diff, latency, visible fraction, per-class fractions) with the explicit note that class roles are provisional until the notebook's class list arrives. Commit the doc only.

---

### Task 11: Records

**Files:**
- Modify: `src/runtime/sensing/control/sensing/perception/AGENTS.md` (add `learned/` row), `src/runtime/sensing/AGENTS.md` (new node + CLI), `tools/perception/prototype/README.md` only if it claims tools/perception has no other tools
- Create: `tools/perception/AGENTS.md` (dataset/model/training subfolders, "weights never in src/", artifacts in `data/perception/`)
- Modify: `src/runtime/sensing/logs.md` and `progress.md` per the module harness format (read `docs/plans/2026-09-15-module-harness-design.md` and copy the entry format used by the latest entries in those files)
- Modify: `docs/logs.md` (one entry, same style as the latest entries)

- [ ] **Step 1:** Update the records.
- [ ] **Step 2:** `python tools/harness/rosy_harness.py generate` then `python tools/harness/rosy_harness.py lint` → 0 errors (run in background; it takes > 2 min).
- [ ] **Step 3:** Full new-test run: `python -m pytest src/runtime/sensing/test/test_learned_manifest.py src/runtime/sensing/test/test_learned_lane_mask.py src/runtime/sensing/test/test_learned_runner.py src/runtime/sensing/test/test_learned_shadow.py src/runtime/sensing/test/test_recording.py -q` and `python -m pytest tools/perception/test -q`; then the sensing suite once: `python -m pytest src/runtime/sensing/test -q -p no:cacheprovider` to prove nothing regressed.
- [ ] **Step 4:** Commit the records and generated files: `docs(sensing): D-356 learned loop records`.

---

## Self-review

- Spec coverage: recorder (T5), harvest (T6), extract (T6), prelabel (T7), build (T7), publish (T8), trainer contract (T8), export (T9), intake (T9), deliver + rollback (T9), shadow node + hot swap (T3, T4), evidence (T10), records (T11). Deferred items stay deferred (design "이번 바퀴에서 하지 않는 것").
- Names used across tasks: `load_manifest`, `verify_files`, `ManifestError`, `ROLES`, `InputSpec`, `ClassSpec`, `LaneMaskEvidence`, `preprocess`, `lane_evidence`, `LaneSegModel.open`, `InferResult`, `ModelSlot`, `shadow_payload`, `SHADOW_SCHEMA`, `TOPIC`, `RECORD_TOPICS`, `new_session`, `finish_session`, `mark_harvested`, `enforce_quota`, `can_record`, `bag_command`, `judge`, `remote_script`, `shard_paths`.
- Safety invariants pinned by tests: no command fields in shadow payload; sha256 and shape refusal; keep-previous on failed swap; unharvested data never deleted; delivery refuses a failed intake; tags refused for HF revisions.
