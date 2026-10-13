"""신호등 관측 서비스 — 카메라 프레임에서 램프 상태를 읽어 **읽기 전용**으로 내어준다.

설계: docs/plans/2026-09-22-signal-observer-vision-design.md · D-163
경계 규칙: 이 서버에는 명령 경로가 없다. POST 라우트 자체를 만들지 않는다 — 증거만
내어주는 서버이고, 제어 권한은 ESP32 컨트롤러(ROSY-SIGNAL-001)와 Fleet 콘솔에 있다.

파이프라인(v1): 캡처 → ROI 크롭 → HSV 색 분할 → lit/색상군 판정.
YOLO 같은 탐지기는 같은 `classify_frame` 인터페이스 뒤에 끼우는 v2 단계다(설계 §2) —
3개의 큰 LED 가 고정 프레임에 있는 문제에는 결정론적 색 분할이 맞다.

응답은 두 층이다:
- `lamps` — 이 프레임의 날 판정(원시값). 같은 프레임이면 같은 답(결정론).
- `stable` — `stable_after` 프레임 연속 일치할 때만 바뀌는 안정 상태. 화면·기록은
  이쪽을 쓴다. 한 프레임 반짝임(AWB 순간 변화 등)이 상태를 뒤집지 않게.

증거의 나이도 함께 나간다 — `frame_id`·`captured_at`·`age_s`·`frozen`. 소스가 같은
버퍼를 반복해도(프레임이 멈춰도) 소비자는 "지금 빨강"으로 읽지 못한다: 내용이
`freeze_after_s` 동안 안 바뀌면 `frozen` 이고, 그때의 `stable` 은 강등된다(UNKNOWN,
`pending: true`). 낡은 프레임의 CONFIRMED 는 만들지 않는다 — v2 확인 예산 T=5s 와
같은 값이다.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

#: 색상군 — B0 사이클 지도의 색과 대조하는 값이지 의미가 아니다(v2 제안 §2.1: 색의
#: 해석 stop/go 는 운영자의 지도가 한다). hue 구간은 OpenCV HSV(0–179) 기준.
HUE_GROUPS: dict[str, list[tuple[int, int]]] = {
    "red": [(0, 10), (170, 180)],
    "orange": [(10, 35)],
    "green": [(35, 90)],
    "blue": [(90, 130)],
}

FRAME_SOURCE_ERROR = "NO_FRAME"
JPEG_MAGIC = b"\xff\xd8"


class ObserverConfigError(ValueError):
    """관측 설정 파일이 규칙을 통과하지 못했다."""


@dataclass(frozen=True)
class Roi:
    name: str
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class ObserverConfig:
    camera: int = 0
    rois: tuple[Roi, ...] = ()
    lit_value_min: int = 90
    lit_sat_min: int = 60
    frame_width: int = 640
    frame_height: int = 480
    #: 프레임 소스 — 없으면 "cv"(camera 인덱스). Pi 배치는 "picamera2", 회귀 세트
    #: 재생은 "file"(디렉터리의 이미지를 순환). 설계 §6: 같은 코드가 Windows 벤치와
    #: Pi 현장에서 돈다.
    source: Optional[dict] = None
    #: 안정 상태로 인정되기까지 필요한 연속 일치 프레임 수. 1 이면 사실상 비활성.
    stable_after: int = 2
    #: 프레임 내용이 마지막으로 바뀐 뒤 이 시간(초)이 지나면 동결(frozen)로 본다 —
    #: 멈춘 프레임의 판정으로 확정(CONFIRMED)을 만들지 않는다(v2 예산 T=5s 와 같은 값).
    freeze_after_s: float = 5.0


@dataclass(frozen=True)
class LampReading:
    name: str
    lit: bool
    group: Optional[str]
    confidence: float

    def as_row(self) -> dict:
        return {"lit": self.lit, "group": self.group, "confidence": round(self.confidence, 2)}


def load_config(path: Path) -> ObserverConfig:
    """설정 파일 → `ObserverConfig`. 나쁜 값은 여기서 거절한다 — 관측이 시작되고 나서
    조용히 이상 판정을 내는 것보다 싸다."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObserverConfigError(f"{path}: cannot read config: {exc}") from exc
    if not isinstance(data, dict):
        raise ObserverConfigError(f"{path}: expected a JSON object")
    camera = data.get("camera")
    source = data.get("source")
    if source is None:
        if not isinstance(camera, int) or camera < 0:
            raise ObserverConfigError(f"{path}: 'camera' must be a device index >= 0 "
                                      "(or give an explicit 'source')")
    if source is not None:
        if not isinstance(source, dict) or "type" not in source:
            raise ObserverConfigError(f"{path}: 'source' must be an object with 'type'")
        if source["type"] not in ("cv", "file", "picamera2"):
            raise ObserverConfigError(f"{path}: source.type must be cv/file/picamera2")
        if source["type"] == "file" and not isinstance(source.get("path"), str):
            raise ObserverConfigError(f"{path}: file source needs 'path'")
    try:
        frame_width = int(data.get("frame_width", 640))
        frame_height = int(data.get("frame_height", 480))
    except (TypeError, ValueError) as exc:
        raise ObserverConfigError(f"{path}: frame_width/frame_height must be integers") from exc
    if frame_width <= 0 or frame_height <= 0:
        raise ObserverConfigError(f"{path}: frame_width/frame_height must be > 0")
    rows = data.get("rois")
    if not isinstance(rows, list) or not rows:
        raise ObserverConfigError(f"{path}: needs a non-empty 'rois' list")
    rois: list[Roi] = []
    names: set[str] = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ObserverConfigError(f"{path}: rois[{i}] is not an object")
        try:
            name = str(row["name"])
            x, y, w, h = (int(row["x"]), int(row["y"]), int(row["w"]), int(row["h"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ObserverConfigError(f"{path}: rois[{i}] needs name/x/y/w/h") from exc
        if not name or name in names:
            raise ObserverConfigError(f"{path}: rois[{i}] name must be unique and non-empty")
        if x < 0 or y < 0 or w <= 0 or h <= 0:
            raise ObserverConfigError(f"{path}: rois[{i}] must be x,y >= 0 and w,h > 0")
        if x + w > frame_width or y + h > frame_height:
            raise ObserverConfigError(
                f"{path}: rois[{i}] ({x},{y}) {w}x{h} reaches outside the declared "
                f"frame {frame_width}x{frame_height}")
        names.add(name)
        rois.append(Roi(name, x, y, w, h))
    thresholds = data.get("thresholds", {})
    if not isinstance(thresholds, dict):
        raise ObserverConfigError(f"{path}: 'thresholds' must be an object")
    stable_after = int(data.get("stable_after", 2))
    if stable_after < 1:
        raise ObserverConfigError(f"{path}: 'stable_after' must be >= 1")
    try:
        freeze_after_s = float(data.get("freeze_after_s", 5.0))
    except (TypeError, ValueError) as exc:
        raise ObserverConfigError(f"{path}: 'freeze_after_s' must be a number of seconds") from exc
    if freeze_after_s <= 0:
        raise ObserverConfigError(
            f"{path}: 'freeze_after_s' must be > 0 seconds "
            "(how long an unchanged frame may still count as fresh evidence)")
    return ObserverConfig(
        camera=camera if isinstance(camera, int) else 0,
        rois=tuple(rois),
        lit_value_min=int(thresholds.get("lit_value_min", 90)),
        lit_sat_min=int(thresholds.get("lit_sat_min", 60)),
        frame_width=frame_width,
        frame_height=frame_height,
        source=source,
        stable_after=stable_after,
        freeze_after_s=freeze_after_s,
    )


def _group_scores(hue: np.ndarray, sat: np.ndarray, val: np.ndarray) -> dict[str, float]:
    """색상군별 점수 — 켜진 픽셀의 채도×명도 평균. 어두운 픽셀은 점수를 못 얻는다."""
    scores: dict[str, float] = {}
    for group, ranges in HUE_GROUPS.items():
        mask = np.zeros(hue.shape, dtype=bool)
        for lo, hi in ranges:
            mask |= (hue >= lo) & (hue < hi)
        scores[group] = float((sat[mask] * val[mask]).mean()) if mask.any() else 0.0
    return scores


def classify_frame(frame: np.ndarray, rois: Sequence[Roi], *,
                   lit_value_min: int = 90, lit_sat_min: int = 60) -> list[LampReading]:
    """BGR 프레임 + ROI → 램프 판독. 결정론적이다 — 같은 프레임이면 같은 답.

    꺼짐 판정: ROI 평균 명도가 낮거나 평균 채도가 낮으면 꺼진 램프다(검은 플라스틱도
    같은 처우). 켜졌으면 색상군 점수가 최고인 군을 고르고, confidence 는 차점과의
    격차다 — 격차가 좁으면(흰 빛, 노이즈) 신뢰가 낮다고 보고하는 것이 맞다.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    readings: list[LampReading] = []
    for roi in rois:
        crop = hsv[roi.y:roi.y + roi.h, roi.x:roi.x + roi.w]
        if crop.size == 0:
            readings.append(LampReading(roi.name, False, None, 0.0))
            continue
        hue = crop[..., 0].astype(np.float32)
        sat = crop[..., 1].astype(np.float32)
        val = crop[..., 2].astype(np.float32)
        if float(val.mean()) < lit_value_min or float(sat.mean()) < lit_sat_min:
            readings.append(LampReading(roi.name, False, None, 0.0))
            continue
        scores = _group_scores(hue, sat, val)
        best = max(scores, key=lambda g: scores[g])
        best_score = scores[best]
        others = sorted((s for g, s in scores.items() if g != best), reverse=True)
        second = others[0] if others else 0.0
        confidence = (best_score - second) / best_score if best_score > 0 else 0.0
        readings.append(LampReading(roi.name, True, best, min(max(confidence, 0.0), 1.0)))
    return readings


FrameSource = Callable[[], Optional[np.ndarray]]


def make_source(config: ObserverConfig) -> FrameSource:
    """설정 → 프레임 소스. 같은 분류기가 Windows 벤치(cv)와 Pi 현장(picamera2)에서,
    시험은 file(기록 프레임 재생)로 돈다 — 소스만 바뀌고 판정 코드는 하나다."""
    src = config.source or {"type": "cv", "index": config.camera}
    kind = src.get("type")

    if kind == "cv":
        cap = cv2.VideoCapture(int(src.get("index", config.camera)))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.frame_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.frame_height)

        def grab_cv() -> Optional[np.ndarray]:
            ok, frame = cap.read()
            return frame if ok else None

        return grab_cv

    if kind == "file":
        directory = Path(str(src["path"]))
        files = sorted(p for p in directory.iterdir()
                       if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
        if not files:
            raise ObserverConfigError(f"{directory}: no png/jpg frames to replay")
        state = {"i": 0}

        def grab_file() -> Optional[np.ndarray]:
            frame = cv2.imread(str(files[state["i"] % len(files)]))
            state["i"] += 1
            return frame

        return grab_file

    if kind == "picamera2":
        try:
            from picamera2 import Picamera2  # Pi 전용 — Windows/CI 에는 없다
        except ImportError as exc:
            raise ObserverConfigError(
                "picamera2 is not installed here; it is for the Raspberry Pi "
                "deployment (see signal-observer-vision-design §6)") from exc
        cam = Picamera2()
        cam.configure(cam.create_still_configuration(main={"size": (
            config.frame_width, config.frame_height)}))
        cam.start()

        def grab_pi() -> Optional[np.ndarray]:
            import numpy as np
            array = cam.capture_array()
            # picamera2 는 RGB 로 준다 — 분류기는 BGR 을 기대한다.
            return cv2.cvtColor(np.asarray(array), cv2.COLOR_RGB2BGR)

        return grab_pi

    raise ObserverConfigError(f"unknown source type: {kind!r}")


# --- 안정 상태 (debounce) -------------------------------------------------------

@dataclass
class LampStability:
    """한 램프의 안정 상태. 연속 `stable_after` 프레임이 같아야 안정이 바뀐다.

    한 프레임 반짝임(AWB 순간 변화, 노이즈)이 화면·기록의 상태를 뒤집지 않게 하는
    장치다. `raw` 와 `stable` 이 갈리는 동안에는 아직 확정되지 않은 것이다.
    """
    stable_after: int
    stable_lit: Optional[bool] = None
    stable_group: Optional[str] = None
    history: deque = field(default_factory=deque)

    def update(self, reading: LampReading) -> dict:
        self.history.append((reading.lit, reading.group))
        while len(self.history) > self.stable_after:
            self.history.popleft()
        settled = (len(self.history) >= self.stable_after
                   and len(set(self.history)) == 1)
        if settled:
            self.stable_lit, self.stable_group = self.history[-1]
        return {"lit": self.stable_lit, "group": self.stable_group,
                "pending": not settled}

    def reset(self) -> None:
        """안정 상태를 비운다 — 동결로 갈라선 구간의 연속성을 이어 붙이지 않는다.
        다시 살아나면 debounce 를 처음부터 돈다(불확실함을 숨기지 않는 쪽이 안전)."""
        self.history.clear()
        self.stable_lit = None
        self.stable_group = None


def create_app(source: FrameSource, config: ObserverConfig, *,
               clock: Callable[[], float] = time.time) -> FastAPI:
    """FastAPI 표면. `clock` 을 주입하면 동결(frozen)을 시험에서 재현할 수 있다."""
    app = FastAPI(title="ROSY Signal Observer", version="0.3.0")
    state: dict[str, object] = {
        "frame": None, "frame_id": 0, "last_content": None,
        "captured_at": 0.0, "age_s": 0.0, "frozen": False,
    }
    stability_map: dict[str, LampStability] = {}

    def _stability_for(name: str) -> LampStability:
        if name not in stability_map:
            stability_map[name] = LampStability(stable_after=config.stable_after)
        return stability_map[name]

    def _capture() -> Optional[np.ndarray]:
        """프레임 하나 + 동결 판정 — 정보의 나이를 재는 곳.

        내용이 계속 같으면 그 정보는 낡은 것이다(카메라 드라이버가 마지막 버퍼를
        반복해도, 실제 램프가 그대로여도). frame_id 는 내용이 바뀔 때만 오르고,
        freeze_after_s 를 넘기면 frozen — stable 은 관측 응답에서 강등된다.
        """
        frame = source()
        if frame is None:
            return None
        now = clock()
        content = frame.tobytes()
        state["frame"] = frame
        if content != state["last_content"]:
            state["last_content"] = content
            state["frame_id"] = int(state["frame_id"]) + 1
            state["captured_at"] = now
        age = now - float(state["captured_at"])
        frozen = age > config.freeze_after_s
        if frozen and not state["frozen"]:
            # 동결로 갈라선 시점 — 멈춰 있던 안정 상태를 더 이상 믿지 않는다.
            for stability in stability_map.values():
                stability.reset()
        state["age_s"] = age
        state["frozen"] = frozen
        return frame

    @app.get("/observed")
    async def observed() -> dict:
        frame = _capture()
        if frame is None:
            return JSONResponse(status_code=503, content={"error": FRAME_SOURCE_ERROR})
        readings = classify_frame(
            frame, config.rois,
            lit_value_min=config.lit_value_min, lit_sat_min=config.lit_sat_min)
        frozen = bool(state["frozen"])
        lamps: dict[str, dict] = {}
        stable: dict[str, dict] = {}
        for reading in readings:
            lamps[reading.name] = reading.as_row()
            if frozen:
                # 낡은 증거로 확정을 만들지 않는다 — 강등은 UNKNOWN 이다.
                stable[reading.name] = {"lit": None, "group": None,
                                        "pending": True, "stale": True}
            else:
                stable[reading.name] = _stability_for(reading.name).update(reading)
        return {"ts": float(state["captured_at"]),
                "frame_id": int(state["frame_id"]),
                "captured_at": float(state["captured_at"]),
                "age_s": round(float(state["age_s"]), 3),
                "frozen": frozen, "lamps": lamps, "stable": stable}

    @app.get("/preview.jpeg")
    async def preview() -> Response:
        """ROI 캘리브레이션용 — 자기 프레임을 직접 캡처한다(`/observed` 를 먼저 부를
        필요가 없다). 소스가 못 주면 마지막 캡처로, 그것도 없으면 503."""
        frame = source()
        if frame is None:
            cached = state.get("frame")
            frame = cached if isinstance(cached, np.ndarray) else None
        if frame is None:
            return JSONResponse(status_code=503, content={"error": FRAME_SOURCE_ERROR})
        annotated = frame.copy()
        readings = {r.name: r for r in classify_frame(
            frame, config.rois,
            lit_value_min=config.lit_value_min, lit_sat_min=config.lit_sat_min)}
        for roi in config.rois:
            reading = readings.get(roi.name)
            color = (0, 200, 0) if reading and reading.lit else (140, 140, 140)
            cv2.rectangle(annotated, (roi.x, roi.y),
                          (roi.x + roi.w, roi.y + roi.h), color, 2)
            label = f"{roi.name}: {'ON ' + (reading.group or '') if reading and reading.lit else 'off'}"
            cv2.putText(annotated, label, (roi.x, max(12, roi.y - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
        ok, jpeg = cv2.imencode(".jpg", annotated)
        if not ok:
            return JSONResponse(status_code=500, content={"error": "ENCODE_FAILED"})
        return Response(content=jpeg.tobytes(), media_type="image/jpeg",
                        headers={"Cache-Control": "no-cache"})

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    return app


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="ROSY signal light observer (read-only)")
    parser.add_argument("--config", required=True, type=Path, help="observer config JSON")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8095)
    args = parser.parse_args(argv)

    import uvicorn

    config = load_config(args.config)
    app = create_app(make_source(config), config)
    print(f"signal observer: http://{args.host}:{args.port}/observed  "
          f"({len(config.rois)} rois, camera {config.camera})", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
