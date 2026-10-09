"""Pure quality judgments for fixed perception evaluation (D-379). No I/O."""

import re

import numpy as np

V13_ANNOTATION = {"annotation_origin": "derived_from_reviewed_lanes", "adr": "D-554"}


def v13_lineage_error(doc: dict) -> str | None:
    """D-554: a v13-drivable manifest may pass intake and reach the lane_seg shadow slot only with
    parent lane model lineage, a content-addressed dataset and derived-lane annotation; else refuse."""
    parent, dataset = doc.get("parent_lane_model"), doc.get("dataset")
    if (doc.get("task") != "lane_seg" or not isinstance(parent, dict) or not isinstance(dataset, dict)
            or not re.fullmatch(r"lane-seg-[A-Za-z0-9._-]+", str(parent.get("model_revision")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(parent.get("onnx_sha256")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(dataset.get("revision")))
            or any(dataset.get(key) != value for key, value in V13_ANNOTATION.items())):
        return ("v13-drivable needs lane_seg parent_lane_model lineage, a 64-hex dataset revision and "
                "dataset annotation_origin derived_from_reviewed_lanes with adr D-554")
    return None



def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v)


def compare_to_champion(ev: dict, champion: dict | None):
    """Both means over the classes both reports scored (champion and candidate may
    differ in classes): {"classes", "miou", "champion_miou"}, "no shared classes",
    or None without a champion."""
    if champion is None:
        return None
    classes = sorted(set(ev["miou_classes"]) & set(champion["iou"]))
    if not classes:
        return "no shared classes"
    return {"classes": classes,
            "miou": float(np.mean([ev["iou"][c] for c in classes])),
            "champion_miou": float(np.mean([champion["iou"][c] for c in classes]))}


def judge_eval(ev: dict, gate: dict) -> list[str]:
    if gate.get("require_eval"):
        if ev.get("disjoint") is not True:
            return ["eval: deployment requires a verified training dataset disjoint from evaluation"]
        if ev.get("role_mismatches"):
            return [f"eval: class roles differ between model and evaluation: {ev['role_mismatches']}"]
    if ev.get("disjoint") is False:
        return [f"eval: training dataset {ev['training_dataset']} shares sessions "
                f"{ev['shared_sessions']} with the eval set (D-379 d3: must be disjoint)"]
    if not ev["matched_classes"]:
        return ["eval: no class name shared by the model and the eval set "
                f"(model only {ev['unmatched']['model_only']}, eval only {ev['unmatched']['eval_only']})"]
    if ev["miou"] is None:
        return [f"eval: no IoU over {ev['frames']} eval frames (no matched non-background class present)"]
    reasons = []
    lane_floor = gate.get("min_lane_marking_iou")
    if lane_floor is not None:
        if not ev["lane_marking_iou"]:
            reasons.append("eval: no lane_marking class matched, min_lane_marking_iou is set")
        for name, v in ev["lane_marking_iou"].items():
            if v is None or v < lane_floor:
                reasons.append(f"eval lane_marking IoU {name} "
                               f"{'none' if v is None else f'{v:.4f}'} < min_lane_marking_iou {lane_floor}")
    floor = gate.get("min_eval_miou")
    if floor is not None and ev["miou"] < floor:
        reasons.append(f"eval mIoU {ev['miou']:.4f} < min_eval_miou {floor}")
    champ, cmp = ev.get("champion"), ev.get("champion_comparison")
    drop = gate.get("max_eval_miou_drop") or 0.0
    if isinstance(cmp, dict) and cmp["miou"] < cmp["champion_miou"] - drop:
        reasons.append(f"eval mIoU {cmp['miou']:.4f} < champion {champ['model_revision']} "
                       f"{cmp['champion_miou']:.4f} - {drop} (over {cmp['classes']})")
    return reasons


def _eval_gate_error(gate: dict) -> str | None:
    required = gate.get("require_eval", False)
    if not isinstance(required, bool):
        return "require_eval must be a boolean"
    if required:
        if not isinstance(gate.get("eval_set"), str) or not gate["eval_set"].strip():
            return "require_eval needs a fixed eval_set"
        floor = gate.get("min_lane_marking_iou")
        if not _number(floor) or not 0 < floor <= 1:
            return "require_eval needs min_lane_marking_iou in (0, 1]"
        floor = gate.get("min_eval_miou")
        if floor is not None and (not _number(floor) or not 0 < floor <= 1):
            return "min_eval_miou must be in (0, 1]"
    return None
