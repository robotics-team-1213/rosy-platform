"""Fixed-set perception scoring; registry retains artifact admission and publication."""
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
for holder in ('learning/registry/perception', 'middleware/perception', 'contracts/foundation'):
    path = str(ROOT / holder)
    if path not in sys.path:
        sys.path.insert(0, path)

from control.sensing.perception.learned.lane_mask import preprocess
from control.sensing.perception.learned.manifest import ManifestError, validate_label_semantic
from intake_dataset import EvalSetError, _verified_manifest, _sessions
from intake_eval_gate import evaluation_semantics

DEFAULT_IGNORE_INDEX = 255


def even_stride(total: int, max_frames: int) -> int:
    return max(1, total // max_frames) if total > 0 and max_frames > 0 else 1


def model_logits(model, bgr: np.ndarray) -> np.ndarray:
    """(1, C, H, W) logits at the model input size, the path LaneSegModel.infer uses."""
    return model._session.run(preprocess(bgr, model.manifest.input))


def _read_eval_set(path: Path) -> dict:
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvalSetError(f"eval set {path}: no readable manifest.json ({exc})") from exc
    if manifest.get("purpose") != "eval":
        raise EvalSetError(f"eval set {path}: manifest purpose is not 'eval'")
    return manifest


def evaluate(model, eval_dir, max_frames: int, *, verify_content=False) -> dict:
    """Per-class IoU of the model on a fixed eval set (D-379 d3).

    The prediction is argmax of the logits at the model input size; the label mask
    is resized to that size with nearest neighbour (preprocess resizes the frame
    the same way, so pixels line up and no class value is invented). Pixels equal
    to the set's ignore_index are left out. Classes are matched by name; a class on
    one side only is listed under "unmatched" and left out. "miou" (the gated number)
    is the mean over matched classes whose union is > 0 and whose eval-set role is not
    "background" ("miou_classes"); "miou_all" includes background. "source_groups"
    shows the same counts by each frame's declared label sources without changing
    the gate score. Frames with non-finite logits are skipped and counted (the replay gate already fails NaN
    models). An eval set without frames is a setup error (EvalSetError)."""
    eval_dir = Path(eval_dir)
    manifest = _verified_manifest(eval_dir) if verify_content else _read_eval_set(eval_dir)
    if manifest.get("purpose") != "eval":
        raise EvalSetError(f"eval set {eval_dir}: manifest purpose is not 'eval'")
    try:
        for c in manifest.get("classes", []):
            validate_label_semantic(c)
    except ManifestError as exc:
        raise EvalSetError(f"eval set {eval_dir}: {exc}") from exc
    model_classes = model.manifest.classes
    set_classes = {c["name"]: int(c["index"]) for c in manifest.get("classes", [])}
    set_roles = {c["name"]: c.get("role") for c in manifest.get("classes", [])}
    frames = manifest.get("frames") or []
    if not frames:
        raise EvalSetError(f"eval set {eval_dir}: no frames")
    model_names = {c.name: c.index for c in model_classes}
    model_roles = {c.name: c.role for c in model_classes}
    matched = sorted(set(set_classes) & set(model_names))
    result = {"set": {"path": str(eval_dir), "content_sha": eval_dir.name}, "frames": 0,
              "sessions": sorted(_sessions(manifest)),
              "nonfinite_frames": 0, "iou": {}, "miou": None, "miou_all": None, "miou_classes": [],
              "matched_classes": matched,
              "role_mismatches": {n: {"model": model_roles[n], "eval": set_roles[n]}
                                  for n in matched if model_roles[n] != set_roles[n]},
              "unmatched": {"model_only": sorted(set(model_names) - set(set_classes)),
                            "eval_only": sorted(set(set_classes) - set(model_names))},
              "lane_marking_iou": {}, "source_groups": []}
    model_class_docs = (((getattr(model.manifest, "raw", None) or {}).get("output") or {}).get("classes") or
                        [{"name": c.name, "role": c.role} for c in model_classes])
    result.update(evaluation_semantics(model_class_docs, manifest.get("classes", []), matched))
    if not matched:
        return result
    ignore = manifest.get("ignore_index", DEFAULT_IGNORE_INDEX)
    frames = frames[::even_stride(len(frames), max_frames)][:max_frames]
    inter = dict.fromkeys(matched, 0)
    union = dict.fromkeys(matched, 0)
    groups = {}  # per class: intersection, union, truth pixels, predicted pixels
    for f in frames:
        bgr = cv2.imread(str(eval_dir / f["image"]), cv2.IMREAD_COLOR)
        mask = cv2.imread(str(eval_dir / f["mask"]), cv2.IMREAD_UNCHANGED)
        if bgr is None or mask is None or mask.ndim != 2:
            raise EvalSetError(f"eval set {eval_dir}: unreadable frame {f['image']} / {f['mask']}")
        logits = model_logits(model, bgr)
        if not np.isfinite(logits).all():
            result["nonfinite_frames"] += 1
            continue
        pred = np.argmax(logits[0], axis=0)
        if mask.shape != pred.shape:
            mask = cv2.resize(mask, (pred.shape[1], pred.shape[0]), interpolation=cv2.INTER_NEAREST)
        valid = mask != ignore
        raw_sources = f.get("sources")
        sources = (tuple(sorted(set(raw_sources)))
                   if isinstance(raw_sources, list) and all(isinstance(s, str) for s in raw_sources)
                   else ())
        group = groups.setdefault(sources, {"frames": 0, "valid_pixels": 0,
                                            "counts": {name: [0, 0, 0, 0] for name in matched}})
        group["frames"] += 1
        group["valid_pixels"] += int(valid.sum())
        for name in matched:
            p = (pred == model_names[name]) & valid
            g = (mask == set_classes[name]) & valid
            hit, area = int((p & g).sum()), int((p | g).sum())
            inter[name] += hit
            union[name] += area
            counts = group["counts"][name]
            counts[0] += hit
            counts[1] += area
            counts[2] += int(g.sum())
            counts[3] += int(p.sum())
        result["frames"] += 1
    result["source_groups"] = [
        {"sources": list(sources), "frames": group["frames"],
         "valid_pixels": group["valid_pixels"],
         "classes": {name: {"truth_pixels": counts[2], "pred_pixels": counts[3],
                            "iou": counts[0] / counts[1] if counts[1] else None}
                     for name, counts in group["counts"].items()}}
        for sources, group in sorted(groups.items())]
    result["iou"] = {n: inter[n] / union[n] for n in matched if union[n] > 0}
    if result["iou"]:
        result["miou_all"] = float(np.mean(list(result["iou"].values())))
    result["miou_classes"] = [n for n in result["iou"] if set_roles.get(n) != "background"]
    if result["miou_classes"]:
        result["miou"] = float(np.mean([result["iou"][n] for n in result["miou_classes"]]))
    result["lane_marking_iou"] = {c.name: result["iou"].get(c.name) for c in model_classes
                                  if c.role == "lane_marking" and c.name in set_classes}
    if verify_content:
        _verified_manifest(eval_dir)
        result["content_verified"] = True
    return result
