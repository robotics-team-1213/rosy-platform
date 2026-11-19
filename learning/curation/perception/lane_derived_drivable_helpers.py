"""Mask derivation, union dataset assembly, and review sheet tile rendering for D-554."""

import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

_ROOT = Path(__file__).resolve().parents[3]
for _p in (_ROOT / "middleware" / "perception", _ROOT / "integrations" / "perception", _ROOT / "contracts" / "foundation"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from perception_runtime.perception.learned.lane_mask import beyond_boundary  # noqa: E402  D-576

SCHEMA = "rosy.lane-derived-drivable/1"
ORIGIN = "derived_from_reviewed_lanes"
ADR = "D-554"
SOURCE_SCHEMA = "pinky-lane-dataset-v1"
# Schemas verify_dataset (and so sheets, import-verdicts, finalize, train_job) admits: this one and
# D-563 map-projected labels (map_projected_drivable.py), each with its own origin and ADR.
ADMITTED = {SCHEMA: (ORIGIN, ADR), "rosy.map-projected-drivable/1": ("map_projected", "D-563")}
# A union of finalized ADMITTED datasets (union command): parts copied whole under parts/pN/, each
# re-verified with its own schema; frames keep their part's annotation_origin and adr.
UNION_SCHEMA = "rosy.drivable-union/1"
IGNORE = 255
DRIVABLE = 5
# Parent v11 output order and roles (lane-seg-20261006-5f5ddcd9) + one final drivable class,
# as train_job.validate_drivable_parent requires.
CLASSES = [{"index": 0, "name": "background", "role": "background"},
           {"index": 1, "name": "lane_left", "role": "lane_marking"},
           {"index": 2, "name": "lane_right", "role": "lane_marking"},
           {"index": 3, "name": "crosswalk", "role": "ignore"},
           {"index": 4, "name": "speed_bump", "role": "ignore"},
           {"index": 5, "name": "drivable", "role": "drivable"}]
# Wall knobs, tuned on arena frames 2026-10-09 (white walls vs grey carpet). Shadowed walls
# read ~130 grey; carpet stays below ~120 or has local std > 12 over a 7x7 window.
WALL = {"min_gray": 125, "max_std": 12.0, "window": 7, "min_area": 200}
# Between-lane pixels this bright are unlabelled paint, not road (28 arena frames 2026-10-09:
# 150 removes <1.5% of the band; 130 also cut lit carpet, up to 21%).
STRIPE_MIN = 150
# Near-field extension: fit window (rows), max RMS fit residual (px), min road width (px).
NEAR = {"fit_rows": 30, "max_resid": 3.0, "min_width": 20}
# Coloured mats / kerbs are not road (sheets4 review 2026-10-09: 302 tiles "green on coloured mats").
# 226 derived frames: drivable carpet saturation median 46, p90 112, with a separate tail from red/
# blue/orange mats and yellow kerbs; 110 with value >= 50 (dark carpet has noisy saturation).
MAT = {"min_sat": 110, "min_val": 50}
APPROVAL_KEYS = ("approved", "approval", "mask_decision", "review_approved")
VERDICTS = ("ok", "concern", "uncertain")

# Wall pixels above ignore_top are not in the mask, so a wall canary would hide in the label-0
# band; drivable_over_offroad paints that band and everything out to the frame edge instead.
CANARY_KINDS = ("drivable_over_offroad", "wall_over_road", "drivable_outside_lines", "drivable_removed")
# BGR; label 0 is saturated cyan so "not drivable" reads apart from the grey carpet (sheets2:
# reviewers caught 136/181 canaries with a grey overlay).
SHEET_COLORS = {DRIVABLE: (0, 255, 0), 0: (255, 255, 0), 1: (255, 0, 0), 2: (0, 0, 255),
                3: (0, 255, 255), 4: (0, 128, 255)}
SHEET_ALPHA = {0: .6}
LEGEND = ("green drivable | cyan = NOT drivable (wall / off-road floor) | magenta unlabelled | "
          "blue lane_left | red lane_right | yellow crosswalk | orange speed_bump")
# A canary must change at least this many pixels: max(floor, fraction of labelled pixels).
CANARY_MIN_PX, CANARY_MIN_FRACTION = 800, 0.15


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _run(stops):
    """Pixels walked before the first stop in an outward-ordered slice."""
    hit = np.flatnonzero(stops)
    return int(hit[0]) if hit.size else stops.size


def _near_fits(rows, near):
    """Linear x(row) for max(L) and min(R) over the lowest qualifying rows, or None."""
    rows = rows[-near["fit_rows"]:] if near["fit_rows"] else []
    if len(rows) < 2:
        return None
    y = np.array([r[0] for r in rows], float)
    fits = []
    for column in (1, 2):
        x = np.array([r[column] for r in rows], float)
        coef = np.polyfit(y, x, 1)
        if np.sqrt(np.mean((np.polyval(coef, y) - x) ** 2)) > near["max_resid"]:
            return None
        fits.append(coef)
    return fits


def derive_mask(src, image, *, ignore_top=110, wall=WALL, stripe_min=STRIPE_MIN, outside_k=math.inf,
                near=NEAR, mat=MAT):
    """Source 5-class mask + BGR image -> (6-class mask, both_rows)."""
    out = np.full(src.shape, IGNORE, np.uint8)
    lane = (src >= 1) & (src <= 4)
    out[lane] = src[lane]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    stop = lane | (gray >= stripe_min)
    band = np.zeros(src.shape, bool)
    outside = np.zeros(src.shape, bool)
    height, width_px = src.shape

    def fill(row, xl, xr, left, right, outer=True):
        band[row, max(xl + 1, 0):max(xr, 0)] = True
        if not outer:
            return
        width = width_px if math.isinf(outside_k) else round(outside_k * (xr - xl - 1))
        if left.size:
            edge = left.min()
            n = _run(stop[row, max(edge - width, 0):edge][::-1])
            outside[row, edge - n:edge] = True
        if right.size:
            edge = right.max() + 1
            n = _run(stop[row, edge:edge + width])
            outside[row, edge:edge + n] = True

    qualifying = []
    for row in range(ignore_top, height):
        left, right = np.flatnonzero(src[row] == 1), np.flatnonzero(src[row] == 2)
        if left.size and right.size and left.max() < right.min():
            qualifying.append((row, left.max(), right.min()))
            fill(row, left.max(), right.min(), left, right)
    both = len(qualifying)
    fits = _near_fits(qualifying, near)
    for row in range(qualifying[-1][0] + 1 if fits else height, height):
        left, right = np.flatnonzero(src[row] == 1), np.flatnonzero(src[row] == 2)
        # Clip to just outside the frame so an off-frame line leaves column 0 / W-1 as road.
        xl = int(np.clip(left.max() if left.size else round(np.polyval(fits[0], row)), -1, width_px))
        xr = int(np.clip(right.min() if right.size else round(np.polyval(fits[1], row)), -1, width_px))
        if xr - xl - 1 < near["min_width"]:
            break
        # D-576: unbounded outside only on both-line rows; a finite k keeps item 10 behaviour.
        fill(row, xl, xr, left, right, outer=not math.isinf(outside_k))
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mat_mask = (hsv[..., 1] >= mat["min_sat"]) & (hsv[..., 2] >= mat["min_val"])
    out[band & (src == 0) & (gray < stripe_min) & ~mat_mask] = DRIVABLE
    out[outside & (src == 0)] = 0
    k = (wall["window"], wall["window"])
    mean = cv2.blur(gray, k)
    std = np.sqrt(np.maximum(cv2.blur(gray * gray, k) - mean * mean, 0))
    candidate = (src == 0) & ~band & (gray >= wall["min_gray"]) & (std <= wall["max_std"])
    candidate[:ignore_top] = False
    _, labels, stats, _ = cv2.connectedComponentsWithStats(candidate.astype(np.uint8), connectivity=8)
    touching = set(np.unique(labels[ignore_top][candidate[ignore_top]]).tolist()) - {0}
    walls = [i for i in touching if stats[i, cv2.CC_STAT_AREA] >= wall["min_area"]]
    # Floor beyond a lane line can be bright and flat too; a wall only stands above the lines.
    # 28 arena frames 2026-10-09: this removed one floor patch inside a circle line, no wall pixel.
    top_lane = np.where(lane.any(axis=0), lane.argmax(axis=0), src.shape[0])
    above = np.arange(src.shape[0])[:, None] < top_lane[None, :]
    out[np.isin(labels, walls) & above] = 0
    out[:ignore_top] = IGNORE
    return out, both


def _session(item, split):
    group = item.get("source_group")
    if isinstance(group, str) and group:
        return group.split(":", 1)[1] if group.startswith("rosy:") else group.replace(":", "-")
    video = item.get("source_video_sha256")
    return f"video-{video[:16]}" if isinstance(video, str) and video else f"data-v13-{split}"


def _write_manifest(out, doc):
    raw = (json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    (out / "manifest.json").write_bytes(raw)
    return _sha(raw)


def derive_dataset(src, out, *, git_commit_fn, min_both_rows=20, ignore_top=110, wall=WALL,
                   stripe_min=STRIPE_MIN, outside_k=math.inf, near=NEAR, tool_commit=None):
    src, out = Path(src), Path(out)
    if out.exists():
        raise ValueError("new output directory required")
    tool_commit = git_commit_fn(tool_commit)
    source_raw = (src / "manifest.json").read_bytes()
    source = json.loads(source_raw)
    if source.get("schema_version") != SOURCE_SCHEMA or source.get("classes") != [
            c["name"] for c in CLASSES[:-1]]:
        raise ValueError(f"source must be {SOURCE_SCHEMA} with v11 class order")
    by_hash = {(i["split"], i["image_sha256"], i["mask_sha256"]): i for i in source["items"]}
    frames, skipped = [], 0
    (out / "images").mkdir(parents=True)
    (out / "masks").mkdir()
    for split in ("train", "val", "test"):
        for image_path in sorted((src / split / "images").glob("*")):
            mask_path = src / split / "masks" / (image_path.stem + ".png")
            image_raw, mask_raw = image_path.read_bytes(), mask_path.read_bytes()
            item = by_hash.get((split, _sha(image_raw), _sha(mask_raw)))
            if item is None:
                raise ValueError(f"{split}/{image_path.name}: not a reviewed source manifest item")
            image = cv2.imdecode(np.frombuffer(image_raw, np.uint8), cv2.IMREAD_COLOR)
            source_mask = cv2.imdecode(np.frombuffer(mask_raw, np.uint8), cv2.IMREAD_UNCHANGED)
            if image is None or source_mask is None or source_mask.shape != image.shape[:2]:
                raise ValueError(f"{split}/{image_path.name}: unreadable or mismatched frame")
            mask, both = derive_mask(source_mask, image, ignore_top=ignore_top, wall=wall,
                                     stripe_min=stripe_min, outside_k=outside_k, near=near)
            if both < min_both_rows:
                skipped += 1
                continue
            name = f"{split}-{image_path.stem}"
            image_rel = f"images/{name}{image_path.suffix}"
            mask_rel = f"masks/{name}.png"
            (out / image_rel).write_bytes(image_raw)
            encoded = cv2.imencode(".png", mask)[1].tobytes()
            (out / mask_rel).write_bytes(encoded)
            frames.append({"split": split, "session": _session(item, split),
                           "image": image_rel, "image_sha256": _sha(image_raw),
                           "mask": mask_rel, "mask_sha256": _sha(encoded), "both_rows": both,
                           "drivable_px": int((mask == DRIVABLE).sum()),
                           "wall_px": int((mask == 0).sum())})
    doc = {"schema": SCHEMA, "annotation_origin": ORIGIN, "adr": ADR,
           "evaluation_use": "training_val_only",
           "source": {"schema": SOURCE_SCHEMA, "manifest_sha256": _sha(source_raw),
                      "dataset_revision": source.get("dataset_revision")},
           "tool": {"name": "lane_derived_drivable.py", "git_commit": tool_commit},
           "params": {"min_both_rows": min_both_rows, "ignore_top": ignore_top, "wall": dict(wall),
                      "stripe_min": stripe_min, "outside_k": None if math.isinf(outside_k) else outside_k,
                      "outside_rows": "both lines visible (D-576)", "mat": dict(MAT),
                      "near": dict(near)},
           "classes": CLASSES, "ignore_index": IGNORE, "skipped_frames": skipped, "frames": frames}
    return _write_manifest(out, doc), doc


def _in_val_block(frame, part, blocks):
    return any(b["part"] == part and b["t0"] <= frame.get("t", float("nan")) <= b["t1"] for b in blocks)


def _union_frames(folder, parts, val_blocks=(), *, verify_fn):
    """(frames, part docs) rebuilt from the parts, each verified finalized under its own schema;
    frames inside a recorded val block (part, t0..t1 of the frame's "t") become split "val"."""
    frames, docs = [], []
    for i, part in enumerate(parts):
        path = folder / part["dir"]
        if part["dir"] != f"parts/p{i}" or _sha((path / "manifest.json").read_bytes()) != part["manifest_sha256"]:
            raise ValueError(f"union part {i} manifest differs")
        doc = verify_fn(path, finalized=True)
        if doc["schema"] not in ADMITTED:
            raise ValueError("a union part must be a D-554 or D-563 dataset")
        docs.append(doc)
        frames += [dict(f, image=f"{part['dir']}/{f['image']}", mask=f"{part['dir']}/{f['mask']}", part=i,
                        annotation_origin=doc["annotation_origin"], adr=doc["adr"],
                        **({"split": "val"} if _in_val_block(f, i, val_blocks) else {}))
                   for f in doc["frames"]]
    return frames, docs


def _union_label(docs):
    pairs = sorted({(d["annotation_origin"], d["adr"]) for d in docs})
    return "+".join(p[0] for p in pairs), "+".join(p[1] for p in pairs)


def _verify_union(folder, doc, *, verify_fn):
    frames, docs = _union_frames(folder, doc.get("parts") or [], doc.get("val_blocks") or [],
                                 verify_fn=verify_fn)
    if len(docs) < 2 or doc.get("frames") != frames:
        raise ValueError("union frames differ from their parts")
    if any(d["params"]["ignore_top"] != doc["params"]["ignore_top"] for d in docs):
        raise ValueError("union parts disagree on ignore_top")
    if ((doc.get("annotation_origin"), doc.get("adr")) != _union_label(docs) or doc.get("classes") != CLASSES
            or doc.get("ignore_index") != IGNORE or doc.get("evaluation_use") != "training_val_only"):
        raise ValueError("not a drivable union dataset")
    return doc


def union_datasets(parts, out, *, git_commit_fn, verify_fn, tool_commit=None, val_last=0.0):
    """Finalized datasets -> one store-ready folder: parts copied under parts/pN/, frames concatenated."""
    out = Path(out)
    if out.exists():
        raise ValueError("new output directory required")
    if len(parts) < 2:
        raise ValueError("a union needs two or more datasets")
    entries = []
    for i, part in enumerate(parts):
        verify_fn(part, finalized=True)
        shutil.copytree(part, out / f"parts/p{i}")
        entries.append({"dir": f"parts/p{i}", "manifest_sha256": _sha((Path(part) / "manifest.json").read_bytes())})
    blocks = []
    if val_last > 0:
        for i, entry in enumerate(entries):
            ts = sorted(f["t"] for f in verify_fn(out / entry["dir"])["frames"] if "t" in f)
            if ts:
                blocks.append({"part": i, "t0": ts[int(len(ts) * (1 - val_last))], "t1": ts[-1]})
    frames, docs = _union_frames(out, entries, blocks, verify_fn=verify_fn)
    tops = {d["params"]["ignore_top"] for d in docs}
    if len(tops) != 1:
        raise ValueError(f"parts disagree on ignore_top {sorted(tops)}")
    origin, adr = _union_label(docs)
    doc = {"schema": UNION_SCHEMA, "annotation_origin": origin, "adr": adr, "evaluation_use": "training_val_only",
           "parts": entries, "val_blocks": blocks, "source": [d["source"] for d in docs],
           "tool": {"name": "lane_derived_drivable.py union", "git_commit": git_commit_fn(tool_commit)},
           "params": {"ignore_top": tops.pop()},
           "judge": {"parts": [{k: v for k, v in d["judge"].items() if k != "dropped"} for d in docs]},
           "classes": CLASSES, "ignore_index": IGNORE, "frames": frames}
    return _write_manifest(out, doc), doc


def _corrupt(mask, kind, ignore_top):
    """A known-wrong copy of mask for a canary tile, or None when this frame cannot show that error
    on at least max(CANARY_MIN_PX, CANARY_MIN_FRACTION of its labelled pixels)."""
    bad, below = mask.copy(), np.arange(mask.shape[0])[:, None] >= ignore_top
    road = mask == DRIVABLE
    # Green canaries paint only over real label 0 (cyan): a 255 pixel can be real green in the
    # near-extension rows, so reviewers could not tell those canaries apart (sheets5 review).
    beyond = (mask == 0) & below & beyond_boundary(mask, 1, 2)
    if kind == "drivable_over_offroad":  # label-0 floor/wall that is not beyond a line
        bad[(mask == 0) & below & ~beyond] = DRIVABLE
    elif kind == "drivable_outside_lines":  # beyond the lines on both-line rows
        bad[beyond] = DRIVABLE
    elif kind == "wall_over_road":
        xs = np.nonzero(road)[1]
        bad[road & (np.arange(mask.shape[1])[None, :] <= (np.median(xs) if xs.size else -1))] = 0
    else:
        bad[road] = 0  # drivable_removed
    need = max(CANARY_MIN_PX, CANARY_MIN_FRACTION * int((mask != IGNORE).sum()))
    return bad if int((bad != mask).sum()) >= need else None


def _tile(image, mask, label, ignore_top):
    view = image.copy()
    for value, color in SHEET_COLORS.items():
        pixels, alpha = mask == value, SHEET_ALPHA.get(value, .55)
        view[pixels] = (image[pixels] * (1 - alpha) + np.asarray(color) * alpha).astype(np.uint8)
    unknown = (mask == IGNORE) & (np.arange(mask.shape[0])[:, None] >= ignore_top)
    view[unknown] = (image[unknown] * .45 + np.asarray((255, 0, 255)) * .55).astype(np.uint8)
    head = np.full((40, image.shape[1] * 2, 3), 255, np.uint8)
    cv2.putText(head, label, (8, 31), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 2, cv2.LINE_AA)
    return np.vstack([head, np.hstack([image, view])])


def _only_cleared(old_mask, new_mask):
    """True when the new mask equals the reviewed one except labels turned 255."""
    old = cv2.imread(str(old_mask), cv2.IMREAD_UNCHANGED)
    new = cv2.imread(str(new_mask), cv2.IMREAD_UNCHANGED)
    return old is not None and new is not None and old.shape == new.shape and bool(
        np.all((new == old) | (new == IGNORE)))
