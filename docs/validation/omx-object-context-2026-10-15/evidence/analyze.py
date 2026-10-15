"""Replay frozen response diagnostics; no images, model calls, or robot access."""
import json
from pathlib import Path


def decode(answer):
    text = answer.strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:-1])
    return json.loads(text)


def pixel_box(box, convention):
    if convention != "normalized_1000":
        raise ValueError("Explicit provider coordinate convention required")
    if len(box) != 4 or any(type(v) is not int for v in box):
        raise ValueError("Four integer coordinates required")
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
        raise ValueError("Invalid normalized box")
    return [x1 * .64, y1 * .48, x2 * .64, y2 * .48]


def iou(a, b):
    area = lambda x: (x[2] - x[0]) * (x[3] - x[1])
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1]))
    return overlap / (area(a) + area(b) - overlap)


def analyze(row, reference):
    out = {k: row[k] for k in ("phase", "role", "view", "elapsed_s")}
    if row["phase"] == "baseline":
        return dict(out, status="free_text_not_geometry_contract")
    try:
        data = decode(row["answer"])
    except json.JSONDecodeError as error:
        return dict(out, status="invalid_json", error=str(error))
    if row["phase"] == "critique":
        required = {"corrections", "task_assessment", "agreed_facts", "unresolved", "can_localize_for_grasp"}
        return dict(out, status="missing_requested_fields" if required - data.keys() else "shape_present",
                    missing=sorted(required - data.keys()), task_assessment=data["task_assessment"])
    if row["phase"] == "context_v3_task":
        return dict(out, status="constrained_task_readback", parsed=data,
                    note="Schema fixes abstention values; not independent task-state evaluation")
    try:
        boxes = []
        for obj in data["targets"]:
            box = obj["bbox_xyxy"]
            if row["phase"] == "structured":
                x1, y1, x2, y2 = box
                if not (0 <= x1 < x2 <= 640 and 0 <= y1 < y2 <= 480):
                    raise ValueError("Outside requested 640x480 pixel coordinate bounds")
                boxes.append(box)
            else:
                boxes.append(pixel_box(box, data["coordinate_system"]))
    except (ValueError, KeyError, TypeError) as error:
        return dict(out, status="coordinate_contract_rejected", error=str(error))
    matches, used = [], set()
    if row["view"] == "top":
        for obj, box in zip(data["targets"], boxes):
            candidates = [(iou(box, ref["bbox_xyxy"]), n, ref) for n, ref in enumerate(reference)
                          if n not in used and ref["label"] == obj["label"]]
            if not candidates:
                continue
            score, n, ref = max(candidates, key=lambda item: item[0])
            if score >= .5:
                used.add(n)
                matches.append({"id": obj["id"], "reference_id": ref["id"], "iou": round(score, 3),
                                "visibility_agrees": obj["visibility"] == ref["visibility"]})
    return dict(out, status="selected_geometry_checks_pass", target_count=len(boxes),
                provisional_matches=matches,
                visibility_agreements=sum(m["visibility_agrees"] for m in matches),
                note="Assistant provisional reference; no accuracy or physical acceptance claim")


def self_check():
    assert pixel_box([0, 0, 1000, 1000], "normalized_1000") == [0, 0, 640, 480]
    assert iou([0, 0, 2, 2], [0, 0, 2, 2]) == 1
    assert iou([0, 0, 1, 1], [2, 2, 3, 3]) == 0
    for box, convention in [([945], "normalized_1000"), ([0, 0, 1, 1], "pixels"),
                            ([0, 0, 1001, 10], "normalized_1000")]:
        try:
            pixel_box(box, convention)
        except ValueError:
            continue
        raise AssertionError("Invalid contract accepted")


if __name__ == "__main__":
    self_check()
    root = Path(__file__).parent
    rows = json.loads((root / "responses.json").read_text(encoding="utf-8"))
    reference = json.loads((root / "provisional-reference.json").read_text(encoding="utf-8"))["targets"]
    report = [analyze(row, reference) for row in rows]
    print(json.dumps(report, ensure_ascii=False, indent=2))
