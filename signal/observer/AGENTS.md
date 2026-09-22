<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-22 | Updated: 2026-09-22 -->

# observer

## Purpose

Host-side read-only observation service. Camera frames in, lamp-state readings out.
**No command path exists** — the service exposes `GET /observed` (+ `/healthz`) only,
so it cannot become a control surface. Design:
`docs/plans/2026-09-22-signal-observer-vision-design.md`.

## Key Files

| File | Description |
|------|-------------|
| `observer.py` | HSV 분할 분류기(`classify_frame`), 설정 로더, FastAPI 표면(`GET /observed`·`/preview.jpeg`), cv2 프레임 소스, 프레임 동결(`freeze_after_s` → `frozen`/`age_s` 강등) |
| `config.example.json` | 카메라 인덱스·ROI·문턱·debounce·동결 예산 예시 (좌표는 설치 후 캘리브레이션) |
| `test/` | 합성 프레임 시험 32건 — 분류·설정 검증·명령 경로 부재·동결 강등·preview 자체 캡처 |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `test/` | pytest — 합성 프레임 기반 (합성 ≠ DEVICE, 실촬 회귀 세트는 벤치에서 수집) |

## For AI Agents

### Working In This Directory

- Rules in order: (1) no POST/command routes — 경로 부재가 아니면 안전하지 않다,
  (2) no frame → 503, 가짜 판독을 만들지 않는다, (3) 판정은 결정론적(같은 프레임 같은 답),
  (4) `group` 은 색상군이지 stop/go 의미가 아니다 — 해석은 사이클 지도(Fleet/운영자).
- `conftest.py` 는 `signal/observer/` 만 sys.path 에 올린다 — `signal/` 자체를 올리면
  표준 라이브러리 `signal` 을 가린다.
- Fleet 교차 검증(의도 vs 접점 vs 실측)은 `src/site/fleet` 쪽 소비자다 — 여기서
  Fleet 를 import 하지 않는다.

### Testing Requirements

```bash
python -m pytest signal/observer/test -q
```

OpenCV(opencv-python) 필요 — Windows 호스트에서 통과를 확인했다(2026-09-22, cv2 5.0).

### Common Patterns

합성 프레임 픽스처(`make_frame`) — 검은 판 + cv2.circle 렌즈. ROI 좌표는 (x, y, w, h).

## Dependencies

### Internal

- Design: `docs/plans/2026-09-22-signal-observer-vision-design.md`

### External

- opencv-python (cv2), numpy, fastapi, uvicorn
- Raspberry Pi 배치: picamera2 (선택 소스 — Pi 전용, 없으면 명확히 거절)

<!-- MANUAL: -->
