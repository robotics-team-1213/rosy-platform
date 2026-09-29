"""차선 인식 녹화 재생 벤치 (D-353 §4).

녹화(mp4) 또는 프레임 폴더를 풀어 차선 검출기들을 같은 프레임에 돌리고, 격자 그림·프레임별 JSON·
지표를 낸다. 녹화와 결과는 공개 저장소 밖에 둔다(D-226) — --out 이 저장소 안이면 거부한다.

  python tools/lane_replay.py --video X:/DevTemp/rosy-pilot-evidence/.../run3.mp4 \
      --crop pilot-side --out X:/DevTemp/lane-replay/run3 --detectors line,between

지표(검출기별):
  on_line_rate  목표가 흰 선 위에 있는 프레임 비율 — 차로 유지에서는 결함이다.
  jump_rate     이웃 프레임 사이 목표가 화면 폭의 30% 넘게 튄 비율.
  none_rate     비가시(HOLD) 비율.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "runtime" / "sensing"))

from control.sensing.perception import lane as lane_mod  # noqa: E402
from control.sensing.perception.camera_ground import nominal_ground_plane  # noqa: E402
from control.sensing.perception.lane_boundaries import LaneBoundaryTracker  # noqa: E402

PROFILE_PATH = REPO / "src" / "runtime" / "sensing" / "config" / "camera_nominal_pinky_pro.yaml"
LANE_HALF_WIDTH_M = 0.0925

# pilot 녹화(1332x760, 가로 배치 D-350)의 카메라 영상 전체(4:3, 머리띠는 지평선 위라 지면 계산에 안 든다).
# none = 원본 카메라 녹화(예: data/teleop/learning, 320x240). 둘 다 공칭 프로필 크기(320x240)로 맞춘다.
CROPS = {"pilot-side": (233, 110, 866, 650), "none": None}
FRAME_W, FRAME_H = 320, 240
EVAL_ROWS = (0.72, 0.95)        # 목표가 선 위인지 보는 행 범위(화면 높이 비율)
ON_LINE_FILL = 0.30             # 목표 주변 상자에서 흰 화소가 이 비율 이상이면 선 위
JUMP_FRACTION = 0.30


def white_mask(bgr: np.ndarray, bright: int = 180, max_sat: int = 60) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return ((hsv[..., 2] >= bright) & (hsv[..., 1] <= max_sat)).astype(np.uint8)


def target_on_line(mask: np.ndarray, error: float) -> bool:
    h, w = mask.shape
    x = int(round(w / 2 + error * w / 2))
    half = max(3, int(w * 0.015))
    y0, y1 = int(h * EVAL_ROWS[0]), int(h * EVAL_ROWS[1])
    box = mask[y0:y1, max(0, x - half):min(w, x + half + 1)]
    return box.size > 0 and float(box.mean()) >= ON_LINE_FILL


def _centre_detector():
    """실물 'centre' 모드(LaneBoundaryTracker)를 공칭 지면으로 — 녹화에는 오도메트리가 없어
    매 프레임 기억을 비우고(memoryless) 정지 자세로 돌린다. 기억 계층(MEMORY)은 평가하지 않는다."""
    import yaml
    profile = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))
    ground = nominal_ground_plane(source="NOMINAL", allowed=True, width_px=FRAME_W,
                                  height_px=FRAME_H, profile=profile)
    tracker = LaneBoundaryTracker(camera_x_offset_m=float(profile["x_offset_m"]))
    clock = {"t": 0.0}

    def detect(img):
        clock["t"] += 0.25
        tracker._forget()
        return tracker.update(clock["t"], (0.0, 0.0, 0.0), img, ground,
                              lane_half_width_m=LANE_HALF_WIDTH_M)
    return detect


def make_detectors(names):
    detectors = {}
    for name in names:
        if name == "line":
            detectors[name] = lambda img: lane_mod.detect_lane_error(img)
        elif name == "between":
            keeper = lane_mod.LaneBetweenKeeper()
            detectors[name] = keeper.update
        elif name == "centre":
            detectors[name] = _centre_detector()
        else:
            raise SystemExit(f"unknown detector {name!r}")
    return detectors


COLOURS = [(0, 0, 255), (0, 255, 0), (255, 128, 0), (255, 0, 255)]


def extract(video: str, crop, fps: float, dst: Path) -> list[Path]:
    vf = [f"fps={fps}"]
    if crop:
        x, y, w, h = crop
        vf.append(f"crop={w}:{h}:{x}:{y}")
    vf.append(f"scale={FRAME_W}:{FRAME_H}")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vf", ",".join(vf),
                    str(dst / "f_%05d.png")], check=True)
    return sorted(dst.glob("f_*.png"))


def run(frames: list[Path], names: list[str], out: Path) -> dict:
    detectors = make_detectors(names)
    rows, tiles = [], []
    for index, path in enumerate(frames):
        img = cv2.imread(str(path))
        if img is None:
            continue
        h, w = img.shape[:2]
        mask = white_mask(img)
        if mask.mean() > 0.6:           # 빈 화면(연결 전 흰 화면 등)은 건너뛴다
            continue
        row = {"frame": path.name}
        vis = img.copy()
        cv2.line(vis, (w // 2, h), (w // 2, h - 50), (255, 255, 255), 1)
        for k, (name, detect) in enumerate(detectors.items()):
            obs = detect(img)
            if obs is None:
                row[name] = None
                continue
            on = target_on_line(mask, obs.error)
            row[name] = {"error": round(float(obs.error), 3),
                         "confidence": round(float(obs.confidence), 2), "on_line": on}
            x = int(w / 2 + obs.error * w / 2)
            y = h - 18 - 24 * k
            cv2.circle(vis, (x, y), 9, COLOURS[k % len(COLOURS)], -1)
            if on:
                cv2.circle(vis, (x, y), 13, (0, 0, 0), 2)
        label = " ".join(f"{n}={'-' if row[n] is None else row[n]['error']}" for n in detectors)
        cv2.putText(vis, f"{index} {label}", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        rows.append(row)
        tiles.append(vis)
    metrics = {}
    for name in detectors:
        seen = [r[name] for r in rows if r[name] is not None]
        jumps = sum(1 for a, b in zip(rows, rows[1:])
                    if a[name] is not None and b[name] is not None
                    and abs(a[name]["error"] - b[name]["error"]) > 2 * JUMP_FRACTION)
        metrics[name] = {
            "frames": len(rows),
            "none_rate": round(1 - len(seen) / max(1, len(rows)), 3),
            "on_line_rate": round(sum(s["on_line"] for s in seen) / max(1, len(seen)), 3),
            "jump_rate": round(jumps / max(1, len(rows) - 1), 3),
        }
    out.mkdir(parents=True, exist_ok=True)
    (out / "frames.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1), encoding="utf-8")
    if tiles:
        step = max(1, len(tiles) // 16)
        pick = tiles[::step][:16]
        while len(pick) % 4:
            pick.append(np.zeros_like(tiles[0]))
        grid = np.vstack([np.hstack(pick[r:r + 4]) for r in range(0, len(pick), 4)])
        cv2.imwrite(str(out / "grid.png"), cv2.resize(grid, None, fx=0.5, fy=0.5))
    return metrics


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--video", action="append", help="녹화 mp4 (여러 번 줄 수 있음)")
    src.add_argument("--frames", help="이미 잘린 카메라 프레임 폴더(png/jpg)")
    parser.add_argument("--crop", default="pilot-side", choices=sorted(CROPS))
    parser.add_argument("--fps", type=float, default=4.0)
    parser.add_argument("--detectors", default="line,between")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    if REPO in out.parents or out == REPO:
        raise SystemExit("--out must be outside the public repo (D-226)")
    names = [n.strip() for n in args.detectors.split(",") if n.strip()]
    if args.frames:
        frames = sorted(p for p in Path(args.frames).iterdir() if p.suffix.lower() in (".png", ".jpg"))
        metrics = run(frames, names, out)
    else:
        frames = []
        tmp = Path(tempfile.mkdtemp(dir=str(out.parent) if out.parent.exists() else None))
        for n, video in enumerate(args.video):
            sub = tmp / f"v{n}"
            sub.mkdir()
            frames += extract(video, CROPS[args.crop], args.fps, sub)
        metrics = run(frames, names, out)
    print(json.dumps(metrics, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
