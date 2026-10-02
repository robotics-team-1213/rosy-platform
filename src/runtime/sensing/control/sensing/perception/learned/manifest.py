"""Subject: the rosy.perception.model/1 manifest (D-356; object_det task D-423).

The only contract between an external trainer and the robot. A model folder
holds model_manifest.json plus the files it names; anything that does not
validate is refused (fail-closed, D-199)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "rosy.perception.model/1"
TASKS = ("lane_seg", "object_det")
ROLES = ("background", "lane_marking", "drivable", "stop_line", "ignore", "wall")  # D-373 d9
OBJECT_ROLE = "object"  # D-423: the one role of every object_det class (lane ROLES stay closed)
# D-423 §2.2 class contract v1 (user-chosen 2026-10-02): names and order are fixed;
# a different list is a new contract, not a new model.
OBJECT_CLASSES = ("robot", "obstacle_box", "cone", "traffic_light", "sign", "person_feet")
# Output layout per task. yolo_cxcywh_scores: [1, 4 + C, A], centre-size boxes in
# model-input pixels then C class scores in 0..1 (an ultralytics export; NMS outside).
LAYOUTS = {"lane_seg": "nchw_logits", "object_det": "yolo_cxcywh_scores"}
COLORS = ("rgb", "bgr")
PRECISIONS = ("fp32", "int8")
MANIFEST_NAME = "model_manifest.json"
REVISION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


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
    output_layout: str = "nchw_logits"

    def role_indices(self, role: str) -> tuple[int, ...]:
        return tuple(c.index for c in self.classes if c.role == role)

    def onnx_file(self, precision: str | None = None) -> Path:
        """The onnx file of that precision; None: the only onnx file, else the fp32 one."""
        onnx = [f for f in self.files if f.name.endswith(".onnx")]
        if precision is None:
            if len(onnx) == 1:
                return self.folder / onnx[0].name
            precision = "fp32"
        for f in onnx:
            if f.precision == precision:
                return self.folder / f.name
        raise ManifestError(f"no {precision} onnx file in manifest")


def check_revision(revision) -> str:
    """model_revision names a folder and a remote path: one safe token, no quoting needed."""
    if not isinstance(revision, str) or not REVISION_PATTERN.fullmatch(revision):
        raise ManifestError(f"model_revision {revision!r}: expected [A-Za-z0-9][A-Za-z0-9._-]*")
    return revision


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


def _parse_classes(doc: dict, task: str = "lane_seg") -> tuple[ClassSpec, ...]:
    if doc.get("layout") != LAYOUTS[task]:
        raise ManifestError(f"output.layout: {task} needs {LAYOUTS[task]}")
    items = doc.get("classes")
    if not isinstance(items, list) or len(items) < 2:
        raise ManifestError("output.classes: at least two classes")
    classes = []
    names = set()
    for item in items:
        if not isinstance(item, dict):
            raise ManifestError("output.classes: objects only")
        index = _req(item, "index", int)
        name = _req(item, "name", str)
        if name in names:
            raise ManifestError(f"output.classes: duplicate name {name!r}")
        names.add(name)
        role = item.get("role")
        allowed = (OBJECT_ROLE,) if task == "object_det" else ROLES
        if role not in allowed:
            raise ManifestError(f"output.classes[{index}].role: one of {allowed}")
        classes.append(ClassSpec(index, name, role))
    if sorted(c.index for c in classes) != list(range(len(classes))):
        raise ManifestError("output.classes: index must be dense 0..N-1")
    classes = tuple(sorted(classes, key=lambda c: c.index))
    if task == "object_det":
        if tuple(c.name for c in classes) != OBJECT_CLASSES:
            raise ManifestError(f"output.classes: object_det needs {OBJECT_CLASSES} in order, role object")
    elif not any(c.role == "lane_marking" for c in classes):
        raise ManifestError("output.classes: no lane_marking role")
    return classes


def _parse_files(items) -> tuple[ModelFile, ...]:
    if not isinstance(items, list) or not items:
        raise ManifestError("files: at least one file")
    files = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ManifestError("files: objects only")
        name = _req(item, "name", str)
        if name in seen:
            raise ManifestError(f"files: duplicate name {name!r}")
        seen.add(name)
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


def _req_text(doc: dict, key: str) -> str:
    value = _req(doc, key, str)
    if not value.strip():
        raise ManifestError(f"{key}: empty")
    return value


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
    revision = check_revision(doc.get("model_revision"))
    task = doc.get("task")
    if task not in TASKS:
        raise ManifestError(f"task: one of {TASKS}")
    dataset = _req(doc, "dataset", dict)
    spec = _parse_input(_req(doc, "input", dict))
    if task == "object_det" and (spec.height % 32 or spec.width % 32):
        raise ManifestError("input.shape: object_det H and W must be a multiple of 32 (stride)")
    return ModelManifest(
        folder=path.parent,
        model_revision=revision,
        task=task,
        files=_parse_files(doc.get("files")),
        input=spec,
        classes=_parse_classes(_req(doc, "output", dict), task),
        dataset_repo=_req_text(dataset, "repo"),
        dataset_revision=_req_text(dataset, "revision"),
        camera_profile_revision=_req_text(doc, "camera_profile_revision"),
        raw=doc,
        output_layout=LAYOUTS[task],
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
        if not p.resolve().is_relative_to(manifest.folder.resolve()):
            raise ManifestError(f"{f.name}: resolves outside the model folder")
        if not p.is_file():
            raise ManifestError(f"{f.name}: missing")
        if sha256_file(p) != f.sha256:
            raise ManifestError(f"{f.name}: sha256 mismatch")
