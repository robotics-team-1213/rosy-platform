"""D-554: v13 drivable training labels derived from human-reviewed lane masks.

Source: a pinky-lane-dataset-v1 folder <src>/{train,val,test}/{images,masks}, masks 320x240
uint8 (0 background, 1 lane_left, 2 lane_right, 3 crosswalk, 4 speed_bump, 255 ignore).
Output: a store-ready dataset folder (manifest.json + images/ + masks/) with one extra final
class 5 drivable. Labels are derived, never approved: evaluation_use is training_val_only,
so these masks are never D-475 evaluation truth.

  derive   --src DIR --out DIR [--min-both-rows 20] [--ignore-top 110] [--stripe-min 150]
           [--outside-k inf] [--near-fit 30] [--near-max-resid 3] [--near-min-width 20]
           [--tool-commit SHA]   (required outside a git checkout, e.g. a git archive snapshot)
  sheets   --out DIR --dest DIR --key FILE [--per-sheet 20] [--seed S] [--canaries 0.1]
           numbered review sheets of every frame; canary tiles (known corruptions) listed only in
           --key, which must lie outside --dest
  import-verdicts --out DIR --sheets DIR --key FILE --verdicts FILE --judge-name NAME
           --instructions FILE [--reviewed-manifest OLD/manifest.json [--drop-unreviewed]]
           reviewer jsonl {tile, verdict ok|concern|uncertain, reason}; refused below 0.9 canary concern
  finalize --out DIR   (drops concern/unreviewed frames, writes the judge block training requires)

Verdicts come only from import-verdicts: finalize, verify_dataset(finalized=True) and train_job
require its canary block (count >= MIN_CANARIES, count/frames >= MIN_CANARY_FRACTION, rate >= 0.9).

Per frame: everything starts 255; source lane classes 1..4 are copied; on each row >= ignore_top
where lane_left and lane_right both exist and max(L) < min(R), source-0 pixels strictly between
become 5, except bright ones (gray >= stripe_min: unlabelled paint) which stay 255.
Outside band negatives (0, D-554 item 9): on those rows, with W = min(R) - max(L) - 1, up to
round(outside_k * W) pixels left of min(L) and right of max(R), walking outward and stopping at the
first lane-class or bright pixel; only source-0 pixels become 0. D-576: outside_k defaults to inf
(recorded as null): beyond a visible line runs to the frame edge or the next lane/paint pixel, on
every row where that line is visible; then drivable not reachable from the bottom centre inside
lane_left / lane_right closed to the frame edge (lane_mask.lane_bounded_drivable) becomes 0.
Near extension (D-554 item 10): below the lowest qualifying row, where a line has left the frame,
max(L) and min(R) are extrapolated from a linear fit over the lowest near_fit qualifying rows
(skipped when either fit's RMS residual > near_max_resid px); an observed edge wins in its row.
Source-0 non-bright pixels strictly between become 5 down to the last row, stopping where the
road width falls below near_min_width. The outside band runs there only beside a visible line.
Wall negatives (0): bright, low-texture source-0 regions connected to row ignore_top,
outside the drivable band and above the topmost lane-class pixel of their column (floor beyond a
line is never wall). Rows above ignore_top are 255 for every class. Everything else stays 255.
"""
import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

_ROOT = Path(__file__).resolve().parents[4]
for _p in (_ROOT / "middleware" / "perception", _ROOT / "contracts" / "foundation"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from control.sensing.perception.learned import lane_mask  # noqa: E402  D-576 closed walls

SCHEMA = "rosy.lane-derived-drivable/1"
ORIGIN = "derived_from_reviewed_lanes"
ADR = "D-554"
SOURCE_SCHEMA = "pinky-lane-dataset-v1"
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
APPROVAL_KEYS = ("approved", "approval", "mask_decision", "review_approved")
VERDICTS = ("ok", "concern", "uncertain")
MIN_CANARIES, MIN_CANARY_FRACTION, MIN_CANARY_RATE = 20, 0.08, 0.9


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
                near=NEAR):
    """Source 5-class mask + BGR image -> (6-class mask, both_rows)."""
    out = np.full(src.shape, IGNORE, np.uint8)
    lane = (src >= 1) & (src <= 4)
    out[lane] = src[lane]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    stop = lane | (gray >= stripe_min)
    band = np.zeros(src.shape, bool)
    outside = np.zeros(src.shape, bool)
    height, width_px = src.shape

    def fill(row, xl, xr, left, right):
        band[row, max(xl + 1, 0):max(xr, 0)] = True
        filled.add(row)
        width = width_px if math.isinf(outside_k) else round(outside_k * (xr - xl - 1))
        if left.size:
            edge = left.min()
            n = _run(stop[row, max(edge - width, 0):edge][::-1])
            outside[row, edge - n:edge] = True
        if right.size:
            edge = right.max() + 1
            n = _run(stop[row, edge:edge + width])
            outside[row, edge:edge + n] = True

    filled = set()
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
        fill(row, xl, xr, left, right)
    if math.isinf(outside_k):  # D-576: beyond a visible line on every row, not only band rows
        for row in sorted(set(range(ignore_top, height)) - filled):
            left, right = np.flatnonzero(src[row] == 1), np.flatnonzero(src[row] == 2)
            if left.size:
                outside[row, left.min() - _run(stop[row, :left.min()][::-1]):left.min()] = True
            if right.size:
                edge = right.max() + 1
                outside[row, edge:edge + _run(stop[row, edge:])] = True
    out[band & (src == 0) & (gray < stripe_min)] = DRIVABLE
    out[outside & (src == 0)] = 0
    own = lane_mask.lane_bounded_drivable(out, DRIVABLE, (1, 2), ignore_top=ignore_top, through_idxs=(3, 4),
                                          boundary=(1, 2))
    out[(out == DRIVABLE) & ~own] = 0  # D-576: drivable beyond a closed boundary line is blocked
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


def _git_commit(given=None):
    """Checkout HEAD, or --tool-commit for a git archive snapshot; never 'unknown'."""
    try:
        found = subprocess.run(["git", "-C", str(Path(__file__).parent), "rev-parse", "HEAD"],
                               capture_output=True, text=True).stdout.strip() or None
    except OSError:
        found = None
    if given is not None and found is not None and given != found:
        raise ValueError(f"--tool-commit {given} differs from checkout HEAD {found}")
    commit = given or found
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("tool commit unknown: run from a git checkout or pass --tool-commit <40-hex>")
    return commit


def _write_manifest(out, doc):
    raw = (json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    (out / "manifest.json").write_bytes(raw)
    return _sha(raw)


def derive(src, out, *, min_both_rows=20, ignore_top=110, wall=WALL, stripe_min=STRIPE_MIN,
           outside_k=math.inf, near=NEAR, tool_commit=None):
    src, out = Path(src), Path(out)
    if out.exists():
        raise ValueError("new output directory required")
    tool_commit = _git_commit(tool_commit)
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
                      "boundary_walls": {"end_px": lane_mask.END_PX, "wall_px": lane_mask.WALL_PX,
                                         "min_line_px": lane_mask.MIN_LINE_PX,
                                         "max_row_growth": lane_mask.MAX_ROW_GROWTH,
                                         "clamp_rows": lane_mask.CLAMP_ROWS},
                      "near": dict(near)},
           "classes": CLASSES, "ignore_index": IGNORE, "skipped_frames": skipped, "frames": frames}
    return _write_manifest(out, doc), doc


def verify_dataset(folder, *, finalized=False):
    """D-554 admission: schema/origin/adr/classes match and every image/mask hash verifies.
    finalized (training): finalize wrote the judge block and every train/val frame was judged
    ok or uncertain."""
    folder = Path(folder)
    doc = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if (doc.get("schema") != SCHEMA or doc.get("annotation_origin") != ORIGIN
            or doc.get("adr") != ADR or doc.get("evaluation_use") != "training_val_only"
            or doc.get("classes") != CLASSES or doc.get("ignore_index") != IGNORE):
        raise ValueError("not a D-554 lane-derived drivable dataset")
    frames = doc.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("D-554 dataset has no frames")
    for frame in frames:
        if any(key in frame for key in APPROVAL_KEYS):
            raise ValueError("D-554 derived labels never carry approval fields")
        for key in ("image", "mask"):
            path = (folder / frame[key]).resolve()
            if not path.is_relative_to(folder.resolve()) or _sha(path.read_bytes()) != frame[key + "_sha256"]:
                raise ValueError(f"D-554 {frame[key]} hash differs from manifest")
    if finalized:
        block = doc.get("judge")
        if (not isinstance(block, dict)
                or not {"model", "endpoint", "prompt_sha256", "counts", "dropped", "sha256",
                        "canaries"} <= set(block)
                or any(f["split"] in ("train", "val") and f.get("judge") not in ("ok", "uncertain")
                       for f in frames)):
            raise ValueError("D-554 dataset is not finalized: import reviewer verdicts, then finalize")
        _check_canaries(block["canaries"], len(frames) + len(block["dropped"]))
    return doc


def _check_canaries(block, frames):
    """Reviewer verdicts count only with enough hidden canaries caught (D-554)."""
    if (not isinstance(block, dict) or set(block) != {"count", "caught", "rate"}
            or type(block["count"]) is not int or type(block["caught"]) is not int
            or not 0 <= block["caught"] <= block["count"] or block["rate"] != (
                block["caught"] / block["count"] if block["count"] else None)):
        raise ValueError("invalid canary block")
    _check_canary_count(block["count"], frames)
    if block["rate"] < MIN_CANARY_RATE:
        raise ValueError(f"canary concern rate {block['rate']:.2f} < {MIN_CANARY_RATE}")


def _check_canary_count(count, frames):
    need = max(MIN_CANARIES, math.ceil(MIN_CANARY_FRACTION * frames))
    if count < need:
        raise ValueError(f"{count} canaries for {frames} frames; at least {need} required")


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


def _corrupt(mask, kind, ignore_top):
    """A known-wrong copy of mask for a canary tile, or None when this frame cannot show that error
    on at least max(CANARY_MIN_PX, CANARY_MIN_FRACTION of its labelled pixels)."""
    bad, below = mask.copy(), np.arange(mask.shape[0])[:, None] >= ignore_top
    road = mask == DRIVABLE
    if kind == "drivable_over_offroad":
        for row in np.flatnonzero((mask == 0).any(axis=1) & road.any(axis=1) & below[:, 0]):
            cols, zeros = np.flatnonzero(road[row]), np.flatnonzero(mask[row] == 0)
            lane = (mask[row] >= 1) & (mask[row] <= 4)
            for span in ((slice(0, zeros[zeros < cols.min()].max() + 1) if (zeros < cols.min()).any() else None),
                         (slice(zeros[zeros > cols.max()].min(), mask.shape[1]) if (zeros > cols.max()).any() else None)):
                if span is not None:
                    bad[row, span][~lane[span]] = DRIVABLE
    elif kind == "wall_over_road":
        xs = np.nonzero(road)[1]
        bad[road & (np.arange(mask.shape[1])[None, :] <= (np.median(xs) if xs.size else -1))] = 0
    else:
        source = {"drivable_outside_lines": (mask == IGNORE) & below, "drivable_removed": road}[kind]
        bad[source] = {"drivable_outside_lines": DRIVABLE, "drivable_removed": 0}[kind]
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


def sheets(out, dest, key, *, per_sheet=20, seed=0, canaries=0.1):
    """Numbered review sheets of every frame plus secret canary tiles (known corruptions)."""
    out, dest, key = Path(out), Path(dest), Path(key)
    if dest.exists() or key.exists():
        raise ValueError("new sheets directory and new key file required")
    if key.resolve().is_relative_to(dest.resolve()):
        raise ValueError("the canary key must lie outside the sheets directory")
    raw = (out / "manifest.json").read_bytes()
    doc = verify_dataset(out)
    ignore_top = doc["params"]["ignore_top"]
    rng = np.random.default_rng(seed)
    frames = doc["frames"]
    load = lambda f: (cv2.imread(str(out / f["image"])),  # noqa: E731
                      cv2.imread(str(out / f["mask"]), cv2.IMREAD_UNCHANGED))
    items = [(f, None) for f in frames]
    wanted, secret, turn = round(len(frames) * canaries), [], 0
    for index in rng.permutation(len(frames)):
        if len(secret) >= wanted:
            break
        mask = load(frames[index])[1]
        # Kinds rotate; a frame too small for this turn's kind is tried with the next ones.
        for step in range(len(CANARY_KINDS)):
            kind = CANARY_KINDS[(turn + step) % len(CANARY_KINDS)]
            if _corrupt(mask, kind, ignore_top) is not None:
                secret.append(len(items))
                items.append((frames[index], kind))
                turn += step + 1
                break
    _check_canary_count(len(secret), len(frames))
    order = rng.permutation(len(items))
    dest.mkdir(parents=True)
    index, hidden, page, tiles = {}, {}, [], []
    for position, item_number in enumerate(order, 1):
        frame, kind = items[item_number]
        tile_id = f"T{position:04d}"
        image, mask = load(frame)
        if kind is not None:
            mask = _corrupt(mask, kind, ignore_top)
            hidden[tile_id] = {"kind": kind, "image": frame["image"]}
        sheet_name = f"sheet-{(position - 1) // per_sheet + 1:03d}.png"
        index[tile_id] = {"image": frame["image"], "sheet": sheet_name}
        tiles.append(_tile(image, mask, tile_id, ignore_top))
        if len(tiles) == per_sheet or position == len(order):
            tiles += [np.full_like(tiles[0], 255)] * (len(tiles) % 2)
            grid = np.vstack([np.hstack(tiles[i:i + 2]) for i in range(0, len(tiles), 2)])
            legend = np.full((50, grid.shape[1], 3), 255, np.uint8)
            cv2.putText(legend, f"{sheet_name}  {LEGEND}", (8, 33), cv2.FONT_HERSHEY_SIMPLEX, .75,
                        (0, 0, 0), 2, cv2.LINE_AA)
            cv2.imwrite(str(dest / sheet_name), np.vstack([legend, grid]))
            page.append(sheet_name)
            tiles = []
    (dest / "index.json").write_text(json.dumps({"dataset_manifest_sha256": _sha(raw), "seed": seed,
                                                 "per_sheet": per_sheet, "sheets": page, "tiles": index},
                                                indent=1) + "\n", encoding="utf-8")
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_text(json.dumps(hidden, indent=1) + "\n", encoding="utf-8")
    return {"sheets": len(page), "tiles": len(index), "canaries": len(hidden)}


def _only_cleared(old_mask, new_mask):
    """True when the new mask equals the reviewed one except labels turned 255."""
    old = cv2.imread(str(old_mask), cv2.IMREAD_UNCHANGED)
    new = cv2.imread(str(new_mask), cv2.IMREAD_UNCHANGED)
    return old is not None and new is not None and old.shape == new.shape and bool(
        np.all((new == old) | (new == IGNORE)))


def import_verdicts(out, sheets_dir, key, verdicts, judge_name, instructions, *,
                    reviewed_manifest=None, drop_unreviewed=False):
    """Reviewer tile verdicts -> judge.jsonl + judge-run.json; refuses a reviewer who misses canaries.

    reviewed_manifest: the manifest the sheets were drawn from, when the masks were re-derived since.
    A verdict carries over only for the same image whose new mask only turned labels into 255;
    other frames are unreviewed (refused, or with drop_unreviewed recorded and dropped by finalize)."""
    out, sheets_dir = Path(out), Path(sheets_dir)
    doc = verify_dataset(out)
    reviewed = Path(reviewed_manifest) if reviewed_manifest else out / "manifest.json"
    index = json.loads((sheets_dir / "index.json").read_text(encoding="utf-8"))
    hidden = json.loads(Path(key).read_text(encoding="utf-8"))
    if index["dataset_manifest_sha256"] != _sha(reviewed.read_bytes()):
        raise ValueError("sheets were made from a different dataset manifest")
    if not set(hidden) <= set(index["tiles"]):
        raise ValueError("canary key does not belong to these sheets")
    _check_canary_count(len(hidden), len(index["tiles"]) - len(hidden))
    answers = {}
    for line in Path(verdicts).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if (row.get("tile") not in index["tiles"] or row.get("verdict") not in VERDICTS
                or not isinstance(row.get("reason", ""), str) or row["tile"] in answers):
            raise ValueError(f"bad or duplicate verdict row: {line[:120]}")
        answers[row["tile"]] = row
    caught = sum(answers.get(tile, {}).get("verdict") == "concern" for tile in hidden)
    canary_block = {"count": len(hidden), "caught": caught, "rate": caught / len(hidden)}
    if canary_block["rate"] < MIN_CANARY_RATE:
        raise ValueError(f"canary concern rate {canary_block['rate']:.2f} < {MIN_CANARY_RATE}: "
                         "reviewer verdicts refused")
    missing = sorted(tile for tile in index["tiles"] if tile not in hidden and tile not in answers)
    if missing:
        raise ValueError(f"{len(missing)} tiles lack a verdict, e.g. {missing[:5]}")
    by_image = {index["tiles"][tile]["image"]: (tile, answers[tile]) for tile in index["tiles"]
                if tile not in hidden}
    old = {f["image"]: f for f in json.loads(reviewed.read_text(encoding="utf-8"))["frames"]}
    rows, unreviewed = [], []
    for frame in doc["frames"]:
        tile, answer = by_image.get(frame["image"], (None, None))
        before = old.get(frame["image"])
        carried = (answer is not None and before is not None
                   and before["image_sha256"] == frame["image_sha256"]
                   and (before["mask_sha256"] == frame["mask_sha256"] or (
                       _sha((reviewed.parent / before["mask"]).read_bytes()) == before["mask_sha256"]
                       and _only_cleared(reviewed.parent / before["mask"], out / frame["mask"]))))
        if carried:
            rows.append({"item": frame["image"], "mask_sha256": frame["mask_sha256"], "tile": tile,
                         "verdict": answer["verdict"], "reason": answer.get("reason", "")})
        else:
            unreviewed.append(frame["image"])
            rows.append({"item": frame["image"], "mask_sha256": frame["mask_sha256"], "tile": tile,
                         "verdict": "unreviewed", "reason": "no verdict for this mask"})
    if unreviewed and not drop_unreviewed:
        raise ValueError(f"{len(unreviewed)} frames have no verdict for their current mask, "
                         f"e.g. {unreviewed[:3]}; pass drop_unreviewed to drop them")
    (out / "judge.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (out / "judge-run.json").write_text(json.dumps({
        "model": judge_name, "endpoint": "sheets:" + sheets_dir.name,
        "prompt_sha256": _sha(Path(instructions).read_bytes()), "splits": ["train", "val", "test"],
        "seconds": 0, "canaries": canary_block, "reviewed_manifest_sha256": index["dataset_manifest_sha256"],
        "unreviewed": unreviewed}) + "\n", encoding="utf-8")
    return {"frames": len(rows), "canaries": canary_block, "unreviewed": len(unreviewed),
            "counts": {v: sum(r["verdict"] == v for r in rows) for v in (*VERDICTS, "unreviewed")}}


def finalize(out):
    """Drop concern/unreviewed frames; record verdicts and the judge block; rewrite and rehash the manifest."""
    out = Path(out)
    doc = verify_dataset(out)
    if "judge" in doc:
        raise ValueError("already finalized")
    judge_raw = (out / "judge.jsonl").read_bytes()
    run = json.loads((out / "judge-run.json").read_text(encoding="utf-8"))
    _check_canaries(run.get("canaries"), len(doc["frames"]))
    rows = [json.loads(line) for line in judge_raw.decode("utf-8").splitlines() if line.strip()]
    verdicts = {(r["item"], r["mask_sha256"]): r["verdict"] for r in rows}
    keep, dropped = [], []
    for frame in doc["frames"]:
        verdict = verdicts.get((frame["image"], frame["mask_sha256"]))
        if verdict in ("concern", "unreviewed"):
            dropped.append(dict(frame, judge=verdict))
            continue
        if verdict is not None:
            frame["judge"] = verdict
        keep.append(frame)
    for frame in dropped:  # unreferenced files would still change the store content hash
        (out / frame["image"]).unlink()
        (out / frame["mask"]).unlink()
    doc["frames"] = keep
    doc["judge"] = {"file": "judge.jsonl", "sha256": _sha(judge_raw), "judged": len(rows),
                    **{key: run[key] for key in ("model", "endpoint", "prompt_sha256", "splits", "seconds",
                                                 "canaries")},
                    "counts": {v: sum(r["verdict"] == v for r in rows) for v in (*VERDICTS, "unreviewed")},
                    "dropped": [{"image": f["image"], "image_sha256": f["image_sha256"],
                                 "mask_sha256": f["mask_sha256"], "verdict": f["judge"]} for f in dropped]}
    return _write_manifest(out, doc), doc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("derive")
    p.add_argument("--src", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--min-both-rows", type=int, default=20)
    p.add_argument("--ignore-top", type=int, default=110)
    p.add_argument("--stripe-min", type=int, default=STRIPE_MIN)
    p.add_argument("--outside-k", type=float, default=math.inf, help="inf (default, D-576): to the edge")
    p.add_argument("--near-fit", type=int, default=NEAR["fit_rows"], help="0 disables near extension")
    p.add_argument("--near-max-resid", type=float, default=NEAR["max_resid"])
    p.add_argument("--near-min-width", type=int, default=NEAR["min_width"])
    p.add_argument("--tool-commit")
    p = sub.add_parser("sheets")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--dest", type=Path, required=True)
    p.add_argument("--key", type=Path, required=True)
    p.add_argument("--per-sheet", type=int, default=20)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--canaries", type=float, default=0.1)
    p = sub.add_parser("import-verdicts")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--sheets", type=Path, required=True)
    p.add_argument("--key", type=Path, required=True)
    p.add_argument("--reviewed-manifest", type=Path)
    p.add_argument("--drop-unreviewed", action="store_true")
    p.add_argument("--verdicts", type=Path, required=True)
    p.add_argument("--judge-name", required=True)
    p.add_argument("--instructions", type=Path, required=True)
    p = sub.add_parser("finalize")
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "derive":
        digest, doc = derive(args.src, args.out, min_both_rows=args.min_both_rows, ignore_top=args.ignore_top,
                             stripe_min=args.stripe_min, outside_k=args.outside_k,
                             near={"fit_rows": args.near_fit, "max_resid": args.near_max_resid,
                                   "min_width": args.near_min_width},
                             tool_commit=args.tool_commit)
        print(json.dumps({"manifest_sha256": digest, "frames": len(doc["frames"]),
                          "skipped_frames": doc["skipped_frames"]}))
    elif args.command == "sheets":
        print(json.dumps(sheets(args.out, args.dest, args.key, per_sheet=args.per_sheet, seed=args.seed,
                                canaries=args.canaries)))
    elif args.command == "import-verdicts":
        print(json.dumps(import_verdicts(args.out, args.sheets, args.key, args.verdicts, args.judge_name,
                                         args.instructions, reviewed_manifest=args.reviewed_manifest,
                                         drop_unreviewed=args.drop_unreviewed)))
    else:
        digest, doc = finalize(args.out)
        print(json.dumps({"manifest_sha256": digest, "frames": len(doc["frames"]),
                          "dropped": len(doc["judge"]["dropped"]), "counts": doc["judge"]["counts"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
