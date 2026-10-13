"""Ask a local Qwen3-VL (Ollama) for road points on every K-th video frame.

    qwen_points.py --video session.mp4 --every 15 --out keypoints.jsonl

One JSON row per keyframe: {frame, every, video_sha256, drivable: [[x, y], ...]
in pixels, seconds, model, prompt_id[, error]}; a failed frame keeps empty points
and its error, and the run goes on (rows are written as they come). Training drafts only: eval frames take human points (D-475 §7).
Ollama must listen on loopback (rosy-ollama unit on the model PC, D-465).
"""
import argparse
import base64
import hashlib
import http.client
import json
import sys
import time
import urllib.request
from pathlib import Path

import cv2

from road_draft import parse_points

PROMPT_ID = "qwen-road-points/1"
PROMPT = ("Point to 3 spots of plain grey carpet floor that are not on any white tape and not on any object. "
          'Output JSON list: [{"point_2d": [x, y], "label": "floor"}, ...]')
SCALE = 3          # 320x240 gives Qwen3-VL too few visual tokens; x3 fixed empty answers in the pilot
NUM_PREDICT = 600  # uncapped point lists ran away to 160 s in the pilot


def _post(url, path, body, timeout=300):
    req = urllib.request.Request(url + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def ask(image_bgr, url, model):
    big = cv2.resize(image_bgr, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_CUBIC)
    png = cv2.imencode(".png", big)[1].tobytes()
    body = {"model": model, "stream": False, "think": False, "keep_alive": "2m",
            "options": {"temperature": 0, "num_predict": NUM_PREDICT},
            "messages": [{"role": "user", "content": PROMPT, "images": [base64.b64encode(png).decode()]}]}
    return _post(url, "/api/chat", body)["message"]["content"]


def unload(url, model):
    """Free VRAM for SAM: Qwen and SAM never share the 16 GB GPU."""
    _post(url, "/api/generate", {"model": model, "keep_alive": 0})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--every", type=int, default=15, help="keyframe spacing in frames (pilot: 15 at 8 fps)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--url", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="qwen3-vl:8b-instruct")
    args = ap.parse_args(argv)
    if args.out.exists():
        sys.exit(f"refusing to overwrite {args.out}")
    video_sha = hashlib.sha256(args.video.read_bytes()).hexdigest()
    cap = cv2.VideoCapture(str(args.video))
    idx = written = errors = empty = 0
    with args.out.open("x") as out:
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if idx % args.every == 0:
                    t = time.time()
                    row = {"frame": idx, "every": args.every, "video_sha256": video_sha,
                           "model": args.model, "prompt_id": PROMPT_ID}
                    try:
                        row["drivable"] = parse_points(ask(frame, args.url, args.model), frame.shape[1], frame.shape[0])
                    except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError) as e:  # URLError/timeouts are OSError
                        row["drivable"], row["error"] = [], f"{type(e).__name__}: {e}"[:200]
                        errors += 1
                    row["seconds"] = round(time.time() - t, 1)
                    empty += not row["drivable"]
                    out.write(json.dumps(row) + "\n")
                    out.flush()
                    written += 1
                idx += 1
        finally:
            cap.release()
            try:
                unload(args.url, args.model)
            except OSError as e:
                print(f"warning: could not unload {args.model}: {e}", file=sys.stderr)
    print(f"{written} keyframes, {empty} without points, {errors} errors")

if __name__ == "__main__":
    main()
