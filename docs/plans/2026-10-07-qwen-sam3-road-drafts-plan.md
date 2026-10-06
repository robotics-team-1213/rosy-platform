# Qwen 점 + SAM 3 도로(drivable) 초안 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 모델 PC 파일럿(`~/rosy-ml/qwen-sam3-pilot/`)을 저장소 도구로 옮겨, 세션 영상에서 drivable 초안을 만들고 기존 lane/wall 초안(v3) 위에 합쳐 `review_ingest`가 읽는 `verified-inputs.jsonl`로 낸다.

**Architecture:** 순수 함수 모듈 `road_draft.py`(점 파싱·gate·발판 seed·로봇 연결 도로·합성, numpy/cv2만)를 호스트에서 테스트한다. `qwen_points.py`는 로컬 Ollama에 키프레임마다 도로 점을 묻는 CLI, `sam3_road_draft.py`는 모델 PC 전용 CLI로 SAM 3 텍스트 lane + SAM 3.0 tracker 전파 후 `road_draft`로 합성한다. 설계: `docs/plans/2026-10-06-qwen-point-sam3-lane-drafts-design.md`의 「파일럿 결과와 수정된 구조」.

**Tech Stack:** Python 3.12, numpy, OpenCV, urllib(Ollama HTTP), `facebookresearch/sam3`(모델 PC `~/rosy-ml/sam3-venv`), pytest.

---

## 파일

| 파일 | 책임 |
|------|------|
| Create `learning/training/perception/dataset/road_draft.py` | 순수 함수. I/O·모델 없음 |
| Create `learning/training/perception/dataset/qwen_points.py` | 영상 K프레임마다 Qwen 도로 점 → `keypoints.jsonl` |
| Create `learning/training/perception/dataset/sam3_road_draft.py` | 모델 PC: 프레임 추출, SAM 3 lane, tracker 도로, 합성, 출력·receipt |
| Create `learning/training/perception/test/test_road_draft.py` | `road_draft` 단위 테스트 |
| Create `learning/training/perception/test/test_qwen_points.py` | 파서 + CLI(가짜 `ask`) 테스트 |
| Modify `learning/training/perception/test/test_cli_help.py` | 두 CLI 등록 |
| Modify `learning/training/perception/dataset/AGENTS.md` | Key Files 3행 |
| Modify `docs/adr/D-465-*.md` | Addendum 2026-10-07 |

테스트 실행 기준(이 worktree에서):

```bash
python -m pytest learning/training/perception/test/test_road_draft.py learning/training/perception/test/test_qwen_points.py learning/training/perception/test/test_cli_help.py -q -p no:cacheprovider
```

---

### Task 1: 점 파싱과 밝기·노란색 마스크

**Files:**
- Create: `learning/training/perception/dataset/road_draft.py`
- Test: `learning/training/perception/test/test_road_draft.py`

- [ ] **Step 1: 실패하는 테스트**

```python
"""road_draft: robot-anchored drivable drafts (pure numpy/cv2)."""
import numpy as np

import road_draft as rd


def test_parse_points_scales_0_1000_and_dedupes():
    raw = '[{"point_2d": [500, 500], "label": "floor"}, {"point_2d": [501, 501]}, {"point_2d": [1000, 0]}]'
    assert rd.parse_points(raw, 320, 240) == [[160, 120], [319, 0]]


def test_parse_points_survives_truncated_json_and_caps():
    raw = "`" * 3 + 'json\n[' + ', '.join(f'{{"point_2d": [{10 * i}, 900]}}' for i in range(40)) + ', {"point_2d": [99'
    pts = rd.parse_points(raw, 320, 240, cap=5)
    assert len(pts) == 5 and pts[0] == [0, 216]


def test_bright_is_relative_to_lower_half_floor():
    lum = np.full((60, 80), 90.0)
    lum[40:45, :] = 200.0          # tape
    lum[:10, :] = 230.0            # white wall, also bright
    b = rd.bright_mask(lum)
    assert b[42, 5] and b[5, 5] and not b[55, 5]


def test_yellow_mask():
    rgb = np.zeros((2, 2, 3), np.float32)
    rgb[0, 0] = (230, 180, 20)
    rgb[1, 1] = (200, 200, 200)
    assert rd.yellow_mask(rgb).tolist() == [[True, False], [False, False]]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest learning/training/perception/test/test_road_draft.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError: No module named 'road_draft'`

- [ ] **Step 3: 최소 구현**

```python
"""Pure helpers for robot-anchored drivable drafts (D-465 addendum 2026-10-07).

SAM and VLM points find "carpet", not "road". The robot's own position is the
trusted anchor: drivable is the carpet component the robot stands on, bounded by
white lines (D-475 §8). Carpet beyond a line is reported as unsure for a person.
No I/O, no models.
"""
import re

import cv2
import numpy as np

FLOOR, LANE, WALL, DRIVABLE, IGNORE = 0, 1, 2, 3, 255
BRIGHT_DELTA = 50   # luminance above the lower-half floor median counted as tape/wall
_POINT = re.compile(r'"point_2d"\s*:\s*\[\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\]')


def parse_points(raw, width, height, cap=16, cell=6):
    """Qwen3-VL point_2d (0-1000 relative) to pixel [x, y]; tolerant of truncated JSON."""
    seen, out = set(), []
    for x, y in _POINT.findall(raw):
        px = min(width - 1, round(float(x) / 1000 * width))
        py = min(height - 1, round(float(y) / 1000 * height))
        if (px // cell, py // cell) not in seen:
            seen.add((px // cell, py // cell))
            out.append([px, py])
    return out[:cap]


def luminance(rgb):
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def bright_mask(lum):
    return lum >= np.median(lum[lum.shape[0] // 2:]) + BRIGHT_DELTA


def yellow_mask(rgb):
    return (rgb[..., 0] > 150) & (rgb[..., 1] > 110) & (rgb[..., 2] < 90)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest learning/training/perception/test/test_road_draft.py -q -p no:cacheprovider`
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add learning/training/perception/dataset/road_draft.py learning/training/perception/test/test_road_draft.py
git commit -m "feat: road_draft point parsing and brightness masks"
```

### Task 2: 발판 seed와 도로 점 gate

**Files:**
- Modify: `learning/training/perception/dataset/road_draft.py`
- Test: `learning/training/perception/test/test_road_draft.py`

- [ ] **Step 1: 실패하는 테스트 (파일 끝에 추가)**

```python
def test_footprint_band_is_bottom_centre():
    rows, cols = rd.footprint_band(240, 320)
    assert (rows.start, rows.stop, cols.start, cols.stop) == (200, 240, 80, 240)


def test_footprint_seed_prefers_bottom_centre_carpet():
    bright = np.zeros((60, 80), bool)
    lane = np.zeros((60, 80), bool)
    lane[:, 38:43] = True                       # a line straight under the camera
    x, y = rd.footprint_seed(bright, lane)
    assert not lane[y, x] and y >= 50 and abs(x - 40) <= 4


def test_footprint_seed_none_when_band_is_all_tape():
    bright = np.zeros((60, 80), bool)
    bright[50:, :] = True
    assert rd.footprint_seed(bright, np.zeros((60, 80), bool)) is None


def test_gate_drops_points_on_tape_or_lane():
    bright = np.zeros((10, 10), bool); bright[1, 1] = True
    lane = np.zeros((10, 10), bool); lane[2, 2] = True
    assert rd.gate_road_points([[1, 1], [2, 2], [5, 5]], bright, lane) == [[5, 5]]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest learning/training/perception/test/test_road_draft.py -q -p no:cacheprovider`
Expected: FAIL, `AttributeError: module 'road_draft' has no attribute 'footprint_band'`

- [ ] **Step 3: 구현 (road_draft.py 끝에 추가)**

```python
def footprint_band(height, width):
    """Rows/cols just in front of the robot (bottom centre of a forward camera)."""
    return slice(height * 5 // 6, height), slice(width // 4, width * 3 // 4)


def footprint_seed(bright, lane):
    """Carpet pixel nearest the bottom centre: the road the robot stands on. None if all tape."""
    rows, cols = footprint_band(*bright.shape)
    ys, xs = np.nonzero(~bright[rows, cols] & ~lane[rows, cols])
    if not len(xs):
        return None
    h, w = bright.shape
    ys, xs = ys + rows.start, xs + cols.start
    j = np.argmin((xs - w // 2) ** 2 + 4 * (ys - (h - 5)) ** 2)
    return [int(xs[j]), int(ys[j])]


def gate_road_points(points, bright, lane):
    """Keep VLM road points that sit on dark, non-lane pixels."""
    return [[x, y] for x, y in points if not bright[y, x] and not lane[y, x]]
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest learning/training/perception/test/test_road_draft.py -q -p no:cacheprovider`
Expected: 8 passed

- [ ] **Step 5: 커밋**

```bash
git add learning/training/perception/dataset/road_draft.py learning/training/perception/test/test_road_draft.py
git commit -m "feat: road_draft footprint seed and road point gate"
```

### Task 3: 로봇 연결 도로와 클래스 맵 합성

**Files:**
- Modify: `learning/training/perception/dataset/road_draft.py`
- Test: `learning/training/perception/test/test_road_draft.py`

- [ ] **Step 1: 실패하는 테스트 (파일 끝에 추가)**

```python
def _scene():
    """Carpet everywhere, one white line across row 30: the robot is below it."""
    carpet = np.ones((60, 80), bool)
    lane = np.zeros((60, 80), bool)
    lane[29:32, :] = True
    carpet[lane] = False
    return carpet, lane


def test_robot_road_stops_at_the_line():
    carpet, lane = _scene()
    road, unsure = rd.robot_road(carpet, lane)
    assert road[55, 40] and not road[10, 40]
    assert unsure[10, 40] and not unsure[55, 40] and not unsure[30, 40]


def test_robot_road_empty_without_footprint_carpet():
    carpet, lane = _scene()
    carpet[50:, :] = False
    road, unsure = rd.robot_road(carpet, lane)
    assert not road.any() and unsure[10, 40]


def test_close_mask_fills_speckle():
    m = np.ones((20, 20), bool); m[10, 10] = False
    assert rd.close_mask(m)[10, 10]


def test_compose_keeps_lane_wall_and_yellow():
    base = np.full((4, 4), rd.FLOOR, np.uint8)
    base[0, :] = rd.WALL
    base[1, 0] = rd.LANE
    base[3, 3] = rd.IGNORE
    road = np.ones((4, 4), bool)
    yellow = np.zeros((4, 4), bool); yellow[2, 2] = True
    out = rd.compose(base, road, yellow)
    assert (out[0] == rd.WALL).all() and out[1, 0] == rd.LANE
    assert out[2, 2] == rd.FLOOR and out[3, 3] == rd.DRIVABLE and out[1, 1] == rd.DRIVABLE
    assert base[1, 1] == rd.FLOOR      # input untouched
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest learning/training/perception/test/test_road_draft.py -q -p no:cacheprovider`
Expected: FAIL, `AttributeError: module 'road_draft' has no attribute 'robot_road'`

- [ ] **Step 3: 구현 (road_draft.py 끝에 추가)**

```python
def close_mask(mask, radius=2):
    k = np.ones((2 * radius + 1, 2 * radius + 1), np.uint8)
    return cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, k) > 0


def robot_road(carpet, lane):
    """(road, unsure): the carpet component with the largest footprint overlap,
    not crossing a 1 px dilated line; other carpet is unsure (maybe another road, maybe off-road)."""
    free = carpet & ~cv2.dilate(lane.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    _, lab = cv2.connectedComponents(free.astype(np.uint8), connectivity=4)
    band = lab[footprint_band(*lab.shape)]
    ids, counts = np.unique(band[band > 0], return_counts=True)
    road = lab == ids[counts.argmax()] if len(ids) else np.zeros_like(carpet)
    return road, carpet & ~road & ~lane


def compose(base, road, yellow):
    """Drivable on top of a base class map; base lane/wall and yellow ramps are kept."""
    out = base.copy()
    out[road & ~np.isin(base, (LANE, WALL)) & ~yellow] = DRIVABLE
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest learning/training/perception/test/test_road_draft.py -q -p no:cacheprovider`
Expected: 12 passed

- [ ] **Step 5: 커밋**

```bash
git add learning/training/perception/dataset/road_draft.py learning/training/perception/test/test_road_draft.py
git commit -m "feat: robot-connected road and class-map compose"
```

### Task 4: `qwen_points.py` (키프레임 도로 점 CLI)

**Files:**
- Create: `learning/training/perception/dataset/qwen_points.py`
- Test: `learning/training/perception/test/test_qwen_points.py`

- [ ] **Step 1: 실패하는 테스트**

```python
"""qwen_points writes one keypoints row per K-th frame and never overwrites."""
import json

import cv2
import numpy as np
import pytest

import qwen_points


def _video(path, n=7):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 8, (32, 24))
    if not w.isOpened():
        pytest.skip("no MJPG writer in this OpenCV build")
    for i in range(n):
        w.write(np.full((24, 32, 3), i * 20, np.uint8))
    w.release()


def test_every_kth_frame_gets_points(tmp_path, monkeypatch):
    video = tmp_path / "s.avi"; _video(video)
    asked = []
    monkeypatch.setattr(qwen_points, "ask", lambda img, url, model: asked.append(img.shape) or '[{"point_2d": [500, 500]}]')
    monkeypatch.setattr(qwen_points, "unload", lambda url, model: None)
    out = tmp_path / "keypoints.jsonl"
    qwen_points.main(["--video", str(video), "--every", "3", "--out", str(out)])
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert [r["frame"] for r in rows] == [0, 3, 6]
    assert rows[0]["drivable"] == [[16, 12]] and rows[0]["prompt_id"] == qwen_points.PROMPT_ID
    assert asked[0] == (24, 32, 3)


def test_refuses_existing_output(tmp_path):
    out = tmp_path / "keypoints.jsonl"; out.write_text("")
    with pytest.raises(SystemExit):
        qwen_points.main(["--video", str(tmp_path / "x.avi"), "--out", str(out)])
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest learning/training/perception/test/test_qwen_points.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError: No module named 'qwen_points'`

- [ ] **Step 3: 구현**

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest learning/training/perception/test/test_qwen_points.py -q -p no:cacheprovider`
Expected: 2 passed (MJPG 없는 OpenCV면 1 skipped)

- [ ] **Step 5: 커밋**

```bash
git add learning/training/perception/dataset/qwen_points.py learning/training/perception/test/test_qwen_points.py
git commit -m "feat: qwen_points keyframe road points from local Ollama"
```

### Task 5: `sam3_road_draft.py` (모델 PC CLI)

**Files:**
- Create: `learning/training/perception/dataset/sam3_road_draft.py`
- Modify: `learning/training/perception/test/test_cli_help.py` (CLIS 목록)

GPU·sam3가 필요한 부분은 호스트에서 단위 테스트하지 않는다. 합성 규칙은 Task 1–3의 테스트가 지키고, 이 파일은 `--help`(sam3 지연 import)와 Task 7의 모델 PC 실행으로 확인한다.

- [ ] **Step 1: `test_cli_help.py`에 두 CLI를 등록(실패 테스트)**

`CLIS` 목록의 `prelabel.py` 다음 줄에 추가:

```python
    "learning/training/perception/dataset/qwen_points.py",
    "learning/training/perception/dataset/sam3_road_draft.py",
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest learning/training/perception/test/test_cli_help.py -q -p no:cacheprovider`
Expected: `sam3_road_draft.py` 항목 FAIL(파일 없음), 나머지 pass

- [ ] **Step 3: 구현**

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest learning/training/perception/test/test_cli_help.py -q -p no:cacheprovider`
Expected: 전부 pass(또는 선택 패키지 없음 skip)

- [ ] **Step 5: 커밋**

```bash
git add learning/training/perception/dataset/sam3_road_draft.py learning/training/perception/test/test_cli_help.py
git commit -m "feat: sam3_road_draft model-PC CLI for robot-anchored drivable drafts"
```

### Task 6: 문서 (AGENTS.md, D-465 addendum)

**Files:**
- Modify: `learning/training/perception/dataset/AGENTS.md` (Key Files 표, `geometry.py` 행 다음)
- Modify: `docs/adr/D-465-*.md` (파일 끝, `**Related:**` 앞)

- [ ] **Step 1: AGENTS.md 행 추가**

```markdown
| `road_draft.py` | Robot-anchored drivable drafts (D-465 addendum 2026-10-07): Qwen `point_2d` parsing, point gate, footprint seed, carpet component the robot stands on bounded by lines, compose over a base map; pure numpy/cv2 |
| `qwen_points.py` | Every K-th video frame → local Ollama Qwen3-VL road points (`keypoints.jsonl`); training drafts only |
| `sam3_road_draft.py` | Model PC only (`~/rosy-ml/sam3-venv`): SAM 3 text lanes + SAM 3.0 tracker road → pending indexed drafts + `verified-inputs.jsonl` for `review_ingest` |
```

- [ ] **Step 2: D-465 addendum 추가**

```markdown
### Addendum 2026-10-07 — SAM 3와 VLM 점으로 drivable 초안

**맥락.** 모델 PC 파일럿(세션 `20261006T091340Z_rosy_26`, 642프레임)에서 VLM(Qwen3-VL 8B) 점 → SAM 분할을 시험했다. VLM 차선 점은 가장자리 환각이 많아 SAM 3 텍스트 프롬프트 차선보다 나빴다. VLM 도로 점 + SAM은 「카펫」을 분할할 뿐 도로와 도로 밖을 구분하지 못했다.

**결정.** §2의 SAM 2 계열에 SAM 3.0(텍스트·점 프롬프트, tracker 전파)을 더한다. lane_line·wall 초안은 SAM 3 텍스트 프롬프트로 만든다. drivable 초안은 로봇 바로 앞 카펫(발판) seed와 밝기·차선 gate를 통과한 VLM 점으로 tracker를 K프레임마다 다시 시작하고, 흰 선을 넘지 않고 발판과 연결된 카펫 성분만 drivable로 둔다. 선 너머 카펫은 기존 base 값을 유지하며 사람이 판단한다. VLM 점은 학습 초안에만 쓰고 고정 평가 정답(D-475 §7)에는 쓰지 않는다. 초안은 receipt에 영상·점·base·체크포인트 hash와 source commit을 남기고, 승인 없이 `review_ingest`로만 들어간다. 도구: `dataset/road_draft.py`, `qwen_points.py`, `sam3_road_draft.py`.

**검증 상태.** 파일럿 수치(연속 프레임 IoU 중앙값 0.998, 0.5 미만 전환 5/641, 0.43 s/frame, peak 7.5 GB)는 초안 안정성 증거이며 라벨 정확도 증거가 아니다. 정확도는 사람 검수 수정량과 독립 평가 마스크(§8)로 잰다.
```

- [ ] **Step 3: 하네스 lint**

Run: `python tools/harness/rosy_harness.py lint`
Expected: 오류 없음 (새 ADR 번호를 쓰지 않으므로 Log 행 불필요)

- [ ] **Step 4: 커밋**

```bash
git add learning/training/perception/dataset/AGENTS.md docs/adr/D-465-*.md
git commit -m "docs: D-465 addendum for SAM 3 + VLM point drivable drafts"
```

### Task 7: 모델 PC 실행과 파일럿 대비 확인

**Files:** 없음(데이터는 `~/rosy-ml/qwen-sam3-road/`, git 밖)

- [ ] **Step 1: 브랜치를 모델 PC 저장소로 보낸다**

```bash
git bundle create X:/DevTemp/qwen-sam3-road.bundle main..HEAD
scp -i C:/Users/livs/.ssh/rosy_model_pc_ed25519 X:/DevTemp/qwen-sam3-road.bundle rosy@192.168.1.231:rosy-ml/
ssh ... 'cd ~/rosy-ml/rosy-platform && git fetch ~/rosy-ml/qwen-sam3-road.bundle HEAD:qwen-sam3-road && git worktree add ~/rosy-ml/wt-qwen-sam3-road qwen-sam3-road'
```

Expected: worktree 생성. 모델 PC 저장소가 이 브랜치의 base 커밋을 갖지 않으면 bundle을 `main` 포함으로 다시 만든다.

- [ ] **Step 2: GPU 사용을 rosy-42에 알리고 실행**

```bash
S=~/rosy-ml/edge-capture/20261006T091340Z_rosy_26; D=~/rosy-ml/wt-qwen-sam3-road/learning/training/perception/dataset; O=~/rosy-ml/qwen-sam3-road/091340Z
mkdir -p ~/rosy-ml/qwen-sam3-road
python3 $D/qwen_points.py --video $S/video/teleop_rosy_26_20261006T091340Z.mp4 --every 15 --out ~/rosy-ml/qwen-sam3-road/091340Z.keypoints.jsonl
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True ~/rosy-ml/sam3-venv/bin/python $D/sam3_road_draft.py \
  --video $S/video/teleop_rosy_26_20261006T091340Z.mp4 --keypoints ~/rosy-ml/qwen-sam3-road/091340Z.keypoints.jsonl \
  --checkpoint ~/rosy-ml/sam3-draft/ckpt/sam3/sam3.pt --base $S/verified-inputs/verified-inputs-v3.jsonl --out $O
```

Expected: 43 keyframes, `frames` 642, peak VRAM 8 GB 이하, `$O/drafts/` 20장.

- [ ] **Step 3: 파일럿과 비교**

receipt의 `rows`에서 drivable% 평균이 파일럿 road 29.1%와 ±5%p 안인지 보고, 20장 overlay 시트를 만들어 눈으로 확인한다(초록 drivable, 흰 lane, 빨강 wall). 크게 다르면 Task 3 규칙과 파일럿 `d_robot_road.py` 차이를 비교한다.

- [ ] **Step 4: 기존 테스트와 비교**

```bash
python -m pytest learning/training/perception/test -q -rfE -p no:cacheprovider > X:/DevTemp/qwen-sam3-road/run.txt
python test/known_failures.py X:/DevTemp/qwen-sam3-road/run.txt
```

Expected: `NEW` 없음.

리뷰 앱 반입 위치(별도 리뷰 상태 vs rosy-42의 `rosy-edge-review`)는 사용자 결정이며 이 계획 밖이다.
