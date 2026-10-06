"""Ask a local Qwen3-VL (Ollama) for road points on every K-th video frame.

    qwen_points.py --video session.mp4 --every 15 --out keypoints.jsonl

One JSON row per keyframe: {frame, drivable: [[x, y], ...] in pixels, seconds,
model, prompt_id}. Training drafts only: eval frames take human points (D-475 §7).
Ollama must listen on loopback (rosy-ollama unit on the model PC, D-465).
"""
import argparse
import base64
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
    cap = cv2.VideoCapture(str(args.video))
    rows, idx = [], 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % args.every == 0:
                t = time.time()
                pts = parse_points(ask(frame, args.url, args.model), frame.shape[1], frame.shape[0])
                rows.append({"frame": idx, "drivable": pts, "seconds": round(time.time() - t, 1),
                             "model": args.model, "prompt_id": PROMPT_ID})
            idx += 1
    finally:
        cap.release()
        unload(args.url, args.model)
    args.out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"{len(rows)} keyframes, {sum(1 for r in rows if not r['drivable'])} without points")


if __name__ == "__main__":
    main()
