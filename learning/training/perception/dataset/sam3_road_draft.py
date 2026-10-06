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


def lane_masks(proc, frames, n, torch, Image):
    lane = None
    for i in range(n):
        im = Image.open(frames / f"{i:05d}.jpg").convert("RGB")
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
            out = proc.set_text_prompt(state=proc.set_image(im), prompt=LANE_PROMPT)
        if lane is None:
            lane = np.zeros((n, im.height, im.width), bool)
        for m, s in zip(out["masks"], out["scores"].tolist()):
            if s >= LANE_SCORE:
                lane[i] |= m.squeeze().cpu().numpy().astype(bool)
    return lane


def track_carpet(tracker, frames, rgb, lane, keypoints, every, torch):
    """Per-frame carpet masks; reseed at every keyframe. Returns (carpet, seeds report)."""
    n, h, w = lane.shape
    carpet = np.zeros_like(lane)
    state = tracker.init_state(video_path=str(frames), offload_video_to_cpu=True)
    seeds = []
    for k in range(0, n, every):
        bright = rd.bright_mask(rd.luminance(rgb[k]))
        pos = rd.gate_road_points(keypoints.get(k, []), bright, lane[k])
        foot = rd.footprint_seed(bright, lane[k])
        if foot:
            pos = [foot] + pos
        seeds.append({"frame": k, "qwen": len(keypoints.get(k, [])), "kept": len(pos), "footprint": foot is not None})
        tracker.clear_all_points_in_video(state)
        if not pos:
            continue
        tracker.add_new_points_or_box(
            inference_state=state, frame_idx=k, obj_id=1,
            points=torch.tensor([[x / w, y / h] for x, y in pos], dtype=torch.float32),
            labels=torch.ones(len(pos), dtype=torch.int32))
        for fi, _, _, masks, _ in tracker.propagate_in_video(
                state, start_frame_idx=k, max_frame_num_to_track=every - 1, reverse=False, propagate_preflight=True):
            if fi < n:
                carpet[fi] = (masks[0, 0] > 0).cpu().numpy()
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
    keypoints = {r["frame"]: r["drivable"] for r in map(json.loads, args.keypoints.read_text().splitlines())}

    import torch
    from PIL import Image
    from sam3.model.sam3_image_processor import Sam3Processor
    from sam3.model_builder import build_sam3_image_model, build_sam3_video_model

    t0 = time.time()
    frames = args.out / "frames"
    n = extract_frames(args.video, frames)
    rgb = [cv2.cvtColor(cv2.imread(str(frames / f"{i:05d}.jpg")), cv2.COLOR_BGR2RGB).astype(np.float32) for i in range(n)]
    proc = Sam3Processor(build_sam3_image_model(checkpoint_path=str(args.checkpoint), load_from_HF=False))
    lane = lane_masks(proc, frames, n, torch, Image)
    video_model = build_sam3_video_model(checkpoint_path=str(args.checkpoint), load_from_HF=False)
    tracker = video_model.tracker
    tracker.backbone = video_model.detector.backbone
    carpet, seeds = track_carpet(tracker, frames, rgb, lane, keypoints, args.every, torch)

    (args.out / "drafts").mkdir()
    out_rows, stats = [], []
    for i, row in enumerate(rows):
        f = row["video_frame"]
        base = cv2.imread(str(args.base.parent / row["mask"]["indexed_png"]), cv2.IMREAD_UNCHANGED)
        road, unsure = rd.robot_road(rd.close_mask(carpet[f]) & ~rd.yellow_mask(rgb[f]), lane[f])
        cm = rd.compose(base, road, rd.yellow_mask(rgb[f]))
        name = f"drafts/{i:06d}.png"
        cv2.imwrite(str(args.out / name), cm)
        new = dict(row, collection=f"{row.get('collection', '')}+{COLLECTION}")
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
               "frames": n, "seconds": round(time.time() - t0, 1),
               "peak_vram_mb": torch.cuda.max_memory_allocated() // 2**20, "seeds": seeds, "rows": stats}
    (args.out / "receipt.json").write_text(json.dumps(receipt, indent=1))
    print(json.dumps({k: receipt[k] for k in ("frames", "seconds", "peak_vram_mb")}))


if __name__ == "__main__":
    main()
