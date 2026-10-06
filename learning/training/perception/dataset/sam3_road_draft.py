"""Drivable drafts on the model PC (D-465 addendum 2026-10-07).

    sam3_road_draft.py --video s.mp4 --keypoints keypoints.jsonl \
        --checkpoint ~/rosy-ml/sam3-draft/ckpt/sam3/sam3.pt \
        --base verified-inputs-v3.jsonl --out new-dir

Lanes: SAM 3 text "white line" on every frame (barrier only; the base map keeps
its own lane/wall). Road: SAM 3.0 tracker seeded every K frames by the robot
footprint pixel plus gated Qwen points, then road_draft.robot_road. Drafts are
written only for the base rows (matched by video_frame) as <out>/drafts/NNNNNN.png
with <out>/verified-inputs.jsonl for review_ingest. Nothing is approved.
Run with ~/rosy-ml/sam3-venv/bin/python; do not run beside another GPU job.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

import road_draft as rd

LANE_PROMPT, LANE_SCORE = "white line", 0.5
COLLECTION = "sam3-road/1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def extract_frames(video, folder):
    """mp4 -> folder/00000.jpg ... (the SAM video loader reads numbered JPEGs)."""
    folder.mkdir(parents=True)
    cap, n = cv2.VideoCapture(str(video)), 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        cv2.imwrite(str(folder / f"{n:05d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        n += 1
    cap.release()
    if not n:
        sys.exit(f"no frames in {video}")
    return n


def _np(x):
    return x.cpu().numpy() if hasattr(x, "cpu") else np.asarray(x)


def select_rows(rows, video_sha, n):
    """Base rows this video can draft: same source video and a frame inside it.
    Returns (kept [(row index, row)], skipped [{row, reason}])."""
    kept, skipped = [], []
    for i, row in enumerate(rows):
        f = row.get("video_frame")
        if row.get("source_video_sha256") != video_sha:
            skipped.append({"row": i, "reason": "other video"})
        elif not isinstance(f, int) or not 0 <= f < n:
            skipped.append({"row": i, "reason": f"video_frame {f!r} outside 0..{n - 1}"})
        else:
            kept.append((i, row))
    return kept, skipped


def load_keypoints(path, every, video_sha):
    """qwen_points rows -> {frame: points}; refuses keypoints made for another video or spacing."""
    out = {}
    for line in path.read_text().splitlines():
        r = json.loads(line)
        if r.get("every") != every or r.get("video_sha256") != video_sha:
            sys.exit(f"{path}: keypoints were made with every={r.get('every')} for another video or spacing")
        out[r["frame"]] = r["drivable"]
    return out


def lane_masks(proc, frames, n, need, torch, Image):
    """SAM 3 text lanes, only for the frames that are used (keyframes and draft rows)."""
    lane = None
    for i in sorted(need):
        im = Image.open(frames / f"{i:05d}.jpg").convert("RGB")
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
            out = proc.set_text_prompt(state=proc.set_image(im), prompt=LANE_PROMPT)
        if lane is None:
            lane = np.zeros((n, im.height, im.width), bool)
        for m, s in zip(out["masks"], out["scores"].tolist()):
            if s >= LANE_SCORE:
                lane[i] |= _np(m.squeeze()).astype(bool)
    return lane


def segment_dir(frames, k, every, n):
    """A folder holding only frames k..k+every-1 renumbered from 0. The tracker loads
    every frame of its folder at 1008 px float (~12 MB each): the whole 642-frame
    video (~7.8 GB) hung the 15 GB model PC, one segment is ~180 MB."""
    seg = Path(frames).parent / "segment"
    shutil.rmtree(seg, ignore_errors=True)
    seg.mkdir()
    for j, fi in enumerate(range(k, min(n, k + every))):
        shutil.copy(Path(frames) / f"{fi:05d}.jpg", seg / f"{j:05d}.jpg")
    return seg


def track_carpet(tracker, frames, rgb, lane, keypoints, every, torch):
    """Per-frame carpet masks; a fresh tracker state per keyframe segment. Returns (carpet, seeds)."""
    n, h, w = lane.shape
    carpet = np.zeros_like(lane)
    seeds = []
    for k in range(0, n, every):
        bright = rd.bright_mask(rd.luminance(rgb[k]))
        pos = rd.gate_road_points(keypoints.get(k, []), bright, lane[k])
        foot = rd.footprint_seed(bright, lane[k])
        if foot:
            pos = [foot] + pos
        seeds.append({"frame": k, "qwen": len(keypoints.get(k, [])), "kept": len(pos), "footprint": foot is not None})
        if not pos:
            continue
        seg = segment_dir(frames, k, every, n)
        state = tracker.init_state(video_path=str(seg), offload_video_to_cpu=True)
        tracker.add_new_points_or_box(
            inference_state=state, frame_idx=0, obj_id=1,
            points=torch.tensor([[x / w, y / h] for x, y in pos], dtype=torch.float32),
            labels=torch.ones(len(pos), dtype=torch.int32))
        for j, _, _, masks, _ in tracker.propagate_in_video(
                state, start_frame_idx=0, max_frame_num_to_track=every - 1, reverse=False, propagate_preflight=True):
            if k + j < n:
                carpet[k + j] = _np(masks[0, 0] > 0)
        del state
        shutil.rmtree(seg)
    return carpet, seeds


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--keypoints", required=True, type=Path, help="qwen_points.py output")
    ap.add_argument("--checkpoint", required=True, type=Path, help="SAM 3.0 sam3.pt")
    ap.add_argument("--base", required=True, type=Path, help="verified-inputs.jsonl whose masks carry lane/wall")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--every", type=int, default=15)
    args = ap.parse_args(argv)
    if args.out.exists():
        sys.exit(f"refusing to overwrite {args.out}")
    rows = [json.loads(l) for l in args.base.read_text().splitlines() if l.strip()]
    video_sha = sha(args.video)
    keypoints = load_keypoints(args.keypoints, args.every, video_sha)

    import torch
    from PIL import Image
    from sam3.model.sam3_image_processor import Sam3Processor
    from sam3.model_builder import build_sam3_image_model, build_sam3_video_model

    t0 = time.time()
    frames = args.out / "frames"
    n = extract_frames(args.video, frames)
    kept, skipped = select_rows(rows, video_sha, n)
    if not kept:
        shutil.rmtree(args.out)
        sys.exit(f"no base row belongs to {args.video} ({len(skipped)} skipped)")
    need = set(range(0, n, args.every)) | {row["video_frame"] for _, row in kept}
    rgb = {i: cv2.cvtColor(cv2.imread(str(frames / f"{i:05d}.jpg")), cv2.COLOR_BGR2RGB) for i in need}
    proc = Sam3Processor(build_sam3_image_model(checkpoint_path=str(args.checkpoint), load_from_HF=False))
    lane = lane_masks(proc, frames, n, need, torch, Image)
    video_model = build_sam3_video_model(checkpoint_path=str(args.checkpoint), load_from_HF=False)
    tracker = video_model.tracker
    tracker.backbone = video_model.detector.backbone
    carpet, seeds = track_carpet(tracker, frames, rgb, lane, keypoints, args.every, torch)

    (args.out / "drafts").mkdir()
    out_rows, stats = [], []
    for i, row in kept:
        f = row["video_frame"]
        base = cv2.imread(str(args.base.parent / row["mask"]["indexed_png"]), cv2.IMREAD_UNCHANGED)
        if base is None or base.shape != carpet[f].shape:
            sys.exit(f"base mask for row {i} missing or not {carpet[f].shape}: {row['mask']['indexed_png']}")
        road, unsure = rd.robot_road(rd.close_mask(carpet[f]) & ~rd.yellow_mask(rgb[f]), lane[f])
        cm = rd.compose(base, road, rd.yellow_mask(rgb[f]))
        name = f"drafts/{i:06d}.png"
        cv2.imwrite(str(args.out / name), cm)
        new = dict(row, collection="+".join(c for c in (row.get("collection"), COLLECTION) if c))
        new["mask"] = dict(row["mask"], indexed_png=name, sha256=sha(args.out / name))
        out_rows.append(new)
        stats.append({"row": i, "video_frame": f, "drivable%": round(100 * float((cm == rd.DRIVABLE).mean()), 1),
                      "unsure_carpet%": round(100 * float(unsure.mean()), 1)})
    (args.out / "verified-inputs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out_rows))
    shutil.copy(args.base.parent / "classes.yaml", args.out / "classes.yaml")
    shutil.rmtree(frames)
    commit = subprocess.run(["git", "-C", str(Path(__file__).parent), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    receipt = {"collection": COLLECTION, "source_commit": commit, "video_sha256": sha(args.video),
               "keypoints_sha256": sha(args.keypoints), "base_sha256": sha(args.base),
               "checkpoint_sha256": sha(args.checkpoint), "every": args.every, "lane_prompt": LANE_PROMPT,
               "frames": n, "skipped_rows": skipped, "seconds": round(time.time() - t0, 1),
               "peak_vram_mb": torch.cuda.max_memory_allocated() // 2**20, "seeds": seeds, "rows": stats}
    (args.out / "receipt.json").write_text(json.dumps(receipt, indent=1))
    print(json.dumps({k: receipt[k] for k in ("frames", "seconds", "peak_vram_mb")}))


if __name__ == "__main__":
    main()
