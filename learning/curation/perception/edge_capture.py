"""Edge-capture loop steps: distinct frames, v2/v3 pixel drafts, verified inputs, review import.

    edge_capture.py frames   <S>/<ID> --out <S>/edge                       (PC)
    edge_capture.py drafts   <S> --session ID                              (PC)
    edge_capture.py verified <E> --session ID --classes classes.yaml       (model PC)
    edge_capture.py sam3     <E>/verified-inputs --checkpoint sam3.pt       (model PC, GPU)
    edge_capture.py import   <E>/verified-inputs/verified-inputs-v3.jsonl --state REVIEW_STATE

<S> is the PC work folder of one session (edge_capture_session.py lays it out),
<E> its copy on the model PC. frames: one camera frame per second of the
recording whose 40x30 grey thumb differs from the last kept one (edge/frames,
edge/frames.jsonl). drafts (v2): the D-379 autolabel mask of the same frame
(LiDAR wall/floor) or 255, plus lane-model lane components of at least 40 px
painted over floor/unlabelled. verified: each edge frame as the mp4's own
decoded frame (matched by bag log time), PNG + sha256, with its v2 draft as an
indexed PNG bound to classes.yaml (review_ingest). sam3 (v3): drop the lane-model
lane, fill 255 with SAM 3 "floor"/"wall", paint SAM 3 "white line" over every
non-wall pixel; writes drafts-v3/, verified-inputs-v3.jsonl and receipt-v3.json.
Run sam3 with the SAM 3 venv and not beside another GPU job. Every draft stays
pending for a person (D-462); eval frames take human truth (D-475).
"""
from __future__ import annotations

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

from labels import FLOOR, IGNORE_INDEX, LANE, WALL

MIN_GAP_S = 1.0          # at most one candidate frame per second of recording
MIN_DIFF = 12.0          # mean |grey| difference of 40x30 thumbs that counts as a new view
THUMB = (40, 30)
MIN_LANE_PX = 40         # lane-model components below this are speckle
AUTOLABEL_MATCH_DIFF = 12.0
SAM_PROMPTS = {"line": "white line", "floor": "floor", "wall": "wall"}
SAM_MIN_SCORE = 0.5
V2_COLLECTION = "supervised-spin-edge-capture"
V3_COLLECTION = "sam3-text-v3:white-line/floor/wall"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_rows(path, rows):
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


# --- pure logic -------------------------------------------------------------------------------

def thumb(jpg: bytes):
    gray = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_GRAYSCALE)
    return None if gray is None else cv2.resize(gray, THUMB)


def distinct(items, thumb_of=thumb, min_gap_s=MIN_GAP_S, min_diff=MIN_DIFF):
    """Yield the (t_s, payload) items kept. A sample is taken at most every min_gap_s (counted
    from the last sample, kept or not) and kept only when its thumb differs from the last kept
    thumb by more than min_diff."""
    last_t = last = None
    for t, payload in items:
        if last_t is not None and t - last_t < min_gap_s:
            continue
        last_t = t
        g = thumb_of(payload)
        if g is None or (last is not None and float(np.mean(cv2.absdiff(g, last))) <= min_diff):
            continue
        last = g
        yield t, payload


def merge_v2(base, model, min_px=MIN_LANE_PX):
    """v2 draft: base (autolabel class mask, or None = all 255) plus the lane-model lane
    components of at least min_px over floor/unlabelled. Never paints over wall."""
    draft = np.full(model.shape, IGNORE_INDEX, np.uint8) if base is None else base.copy()
    lane = ((model == LANE) & ((draft == FLOOR) | (draft == IGNORE_INDEX))).astype(np.uint8)
    k, lab, stats, _ = cv2.connectedComponentsWithStats(lane, connectivity=8)
    for c in range(1, k):
        if stats[c, cv2.CC_STAT_AREA] >= min_px:
            draft[lab == c] = LANE
    return draft


def merge_v3(draft, line, floor, wall):
    """v3 draft from a v2 draft and SAM boolean masks: drop the lane-model lane, fill only
    255 with floor then wall, then SAM lane paint over everything except wall."""
    d = draft.copy()
    d[d == LANE] = IGNORE_INDEX
    d[(d == IGNORE_INDEX) & floor] = FLOOR
    d[(d == IGNORE_INDEX) & wall] = WALL
    d[line & (d != WALL)] = LANE
    return d


def match_video_frames(sidecar, edges):
    """{video frame index: edge row}, by exact bag log time; every edge row must match."""
    by_log = {r["log_ns"]: r["index"] for r in sidecar}
    missing = [e["index"] for e in edges if e["log_ns"] not in by_log]
    if missing:
        raise ValueError(f"edge frames without a video frame of the same log time: {missing[:5]}")
    return {by_log[e["log_ns"]]: e for e in edges}


def verified_row(*, session, capture_group, collection, video_name, video_sha256, video_frame,
                 video_time_s, width, height, image_path, png: bytes, mask_rel, mask: bytes,
                 classes_sha256):
    """One review_ingest row with an indexed-PNG draft bound to classes.yaml by its sha256."""
    return {"source_session": session, "capture_group": capture_group, "source_video": video_name,
            "source_video_sha256": video_sha256, "video_frame": video_frame, "video_time_s": video_time_s,
            "timestamp_basis": "camera_header_stamp", "collection": collection,
            "width": width, "height": height, "image": str(image_path), "image_sha256": sha(png),
            "mask": {"indexed_png": mask_rel, "sha256": sha(mask), "classes_sha256": classes_sha256}}


# --- steps ------------------------------------------------------------------------------------

def _bag_order(path):
    return int("".join(c for c in path.stem if c.isdigit()) or 0)


def cmd_frames(args):
    from mcap.reader import make_reader
    session = args.session_dir.name
    bags = sorted((args.session_dir / "bag").glob("*.mcap"), key=_bag_order)

    def camera():
        for bag in bags:
            with open(bag, "rb") as fh:
                for _, ch, msg in make_reader(fh).iter_messages():
                    soi = msg.data.find(b"\xff\xd8")
                    if "camera" in ch.topic and soi >= 0:
                        yield msg.log_time / 1e9, (msg.log_time, msg.data[soi:])

    (args.out / "frames").mkdir(parents=True, exist_ok=True)
    rows = []
    for _, (log_ns, jpg) in distinct(camera(), thumb_of=lambda p: thumb(p[1])):
        i = len(rows)
        (args.out / "frames" / f"{i:06d}.jpg").write_bytes(jpg)
        rows.append({"index": i, "image": f"frames/{i:06d}.jpg", "log_ns": log_ns, "session": session,
                     "image_sha256": sha(jpg)})
    _write_rows(args.out / "frames.jsonl", rows)
    print("distinct frames", len(rows))


def _autolabel_base(auto_dir, labels, img, t_s):
    """The autolabel mask of the same view: one of the 3 nearest autolabel frames in time
    whose grey image differs by less than AUTOLABEL_MATCH_DIFF and that has a label source."""
    best, diff = None, float("inf")
    for r in sorted(labels, key=lambda r: abs(r["t"] - t_s))[:3]:
        a = cv2.imread(str(auto_dir / "frames" / f"{r['index']:06d}.jpg"), cv2.IMREAD_GRAYSCALE)
        if a is not None and a.shape == img.shape:
            d = float(np.mean(cv2.absdiff(a, img)))
            if d < diff:
                best, diff = r, d
    if best is None or diff >= AUTOLABEL_MATCH_DIFF or not best.get("sources"):
        return None
    return cv2.imread(str(auto_dir / "masks" / f"{best['index']:06d}.png"), cv2.IMREAD_UNCHANGED)


def cmd_drafts(args):
    s, auto = args.work, args.work / "autolabel"
    labels = _rows(auto / "labels.jsonl")
    out = s / "drafts"
    out.mkdir(exist_ok=True)
    n_lidar = 0
    edges = _rows(s / "edge" / "frames.jsonl")
    for e in edges:
        img = cv2.imread(str(s / "edge" / e["image"]), cv2.IMREAD_GRAYSCALE)
        base = _autolabel_base(auto, labels, img, e["log_ns"] / 1e9)
        n_lidar += base is not None
        model = cv2.imread(str(s / "prelabel" / "masks" / f"{args.session}__{e['index']:06d}.png"),
                           cv2.IMREAD_UNCHANGED)
        if model is None:
            sys.exit(f"no lane-model mask for edge frame {e['index']}")
        cv2.imwrite(str(out / f"{e['index']:06d}.png"), merge_v2(base, model))
    print("drafts", len(edges), "with LiDAR geometry", n_lidar)


def cmd_verified(args):
    e_dir = args.work
    vi = e_dir / "verified-inputs"
    (vi / "images").mkdir(parents=True, exist_ok=True)
    (vi / "drafts").mkdir(exist_ok=True)
    shutil.copy(args.classes, vi / "classes.yaml")
    videos = sorted((e_dir / "video").glob("*.mp4"))
    if len(videos) != 1:
        sys.exit(f"expected one mp4 in {e_dir / 'video'}, found {len(videos)}")
    video = videos[0]
    side = _rows(video.with_suffix(".jsonl"))
    want = match_video_frames(side, _rows(e_dir / "edge" / "frames.jsonl"))
    vsha, cls = sha(video.read_bytes()), sha((vi / "classes.yaml").read_bytes())
    capture_group = args.capture_group or f"edge-spin-{args.session}"
    cap, i, rows = cv2.VideoCapture(str(video)), 0, []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i in want:
            rel = f"drafts/{want[i]['index']:06d}.png"
            mask = (e_dir / rel).read_bytes()
            (vi / rel).write_bytes(mask)
            png = cv2.imencode(".png", frame)[1].tobytes()
            img = (vi / "images" / f"{args.session}__vf{i:06d}.png").resolve()
            img.write_bytes(png)
            rows.append(verified_row(
                session=args.session, capture_group=capture_group, collection=args.collection,
                video_name=video.name, video_sha256=vsha, video_frame=i,
                video_time_s=side[i]["t"] - side[0]["t"], width=frame.shape[1], height=frame.shape[0],
                image_path=img, png=png, mask_rel=rel, mask=mask, classes_sha256=cls))
        i += 1
    cap.release()
    if len(rows) != len(want):
        sys.exit(f"decoded {len(rows)} of {len(want)} edge frames from {video.name}")
    _write_rows(vi / "verified-inputs.jsonl", rows)
    print("verified rows", len(rows))


def cmd_sam3(args):
    import torch  # lazy: the PC side and the tests run without torch/SAM
    from PIL import Image
    from sam3.model.sam3_image_processor import Sam3Processor
    from sam3.model_builder import build_sam3_image_model

    proc = Sam3Processor(build_sam3_image_model(checkpoint_path=str(args.checkpoint), load_from_HF=False))

    def union(state, prompt, shape):
        out, m = proc.set_text_prompt(state=state, prompt=prompt), np.zeros(shape, bool)
        for mask, score in zip(out["masks"], out["scores"]):
            if float(score) >= SAM_MIN_SCORE:
                m |= mask.squeeze().cpu().numpy().astype(bool)
        return m

    t0, vi = time.time(), args.verified_inputs
    out = vi / "drafts-v3"
    out.mkdir(exist_ok=True)
    rows, new_rows, counts = _rows(vi / "verified-inputs.jsonl"), [], np.zeros(256, np.int64)
    for r in rows:
        draft = np.array(Image.open(vi / r["mask"]["indexed_png"]))
        with torch.autocast("cuda", dtype=torch.bfloat16), torch.inference_mode():
            st = proc.set_image(Image.open(r["image"]).convert("RGB"))
            sam = {k: union(st, p, draft.shape) for k, p in SAM_PROMPTS.items()}
        d = merge_v3(draft, **sam)
        name = Path(r["mask"]["indexed_png"]).name
        Image.fromarray(d).save(out / name)
        new_rows.append(dict(r, collection=V3_COLLECTION,
                             mask=dict(r["mask"], indexed_png=f"drafts-v3/{name}", sha256=sha((out / name).read_bytes()))))
        counts += np.bincount(d.ravel(), minlength=256)
    _write_rows(vi / "verified-inputs-v3.jsonl", new_rows)
    total = max(int(counts.sum()), 1)
    commit = subprocess.run(["git", "-C", str(Path(__file__).parent), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    receipt = {"collection": V3_COLLECTION, "source_commit": commit, "prompts": SAM_PROMPTS,
               "min_score": SAM_MIN_SCORE, "checkpoint_sha256": sha(Path(args.checkpoint).read_bytes()),
               "base_sha256": sha((vi / "verified-inputs.jsonl").read_bytes()), "frames": len(rows),
               "unlabelled": round(int(counts[IGNORE_INDEX]) / total, 4), "lane": round(int(counts[LANE]) / total, 4),
               "seconds": round(time.time() - t0, 1), "peak_vram_mb": torch.cuda.max_memory_allocated() // 2**20}
    (vi / "receipt-v3.json").write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    print(json.dumps({k: receipt[k] for k in ("frames", "unlabelled", "lane", "seconds", "peak_vram_mb")}))


def cmd_import(args):
    import review_app
    import review_ingest
    store = review_app.ReviewStore(args.state)
    r = review_ingest.import_frames(store, {"path": str(args.catalog)})
    print({k: r.get(k) for k in ("added", "pixel_reviews_pending", "indices")})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("frames")
    p.add_argument("session_dir", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_frames)
    p = sub.add_parser("drafts")
    p.add_argument("work", type=Path)
    p.add_argument("--session", required=True)
    p.set_defaults(fn=cmd_drafts)
    p = sub.add_parser("verified")
    p.add_argument("work", type=Path)
    p.add_argument("--session", required=True)
    p.add_argument("--classes", type=Path, required=True, help="the review workspace's classes.yaml")
    p.add_argument("--capture-group", help="default edge-spin-<session>")
    p.add_argument("--collection", default=V2_COLLECTION)
    p.set_defaults(fn=cmd_verified)
    p = sub.add_parser("sam3")
    p.add_argument("verified_inputs", type=Path)
    p.add_argument("--checkpoint", type=Path, required=True, help="SAM 3.0 sam3.pt")
    p.set_defaults(fn=cmd_sam3)
    p = sub.add_parser("import")
    p.add_argument("catalog", type=Path)
    p.add_argument("--state", type=Path, required=True, help="review app state folder")
    p.set_defaults(fn=cmd_import)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
