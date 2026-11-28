
# observer

**Parent context:** `../AGENTS.md`

## Purpose

Host-side read-only observation service. Camera frames in, lamp-state readings out.
**No command path exists** — the service exposes `GET /observed` (+ `/healthz`) only,
so it cannot become a control surface. Design:
`docs/plans/2026-09-22-signal-observer-vision-design.md`.

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
- Fleet 교차 검증(의도 vs 접점 vs 실측)은 `operations/fleet` 쪽 소비자다 — 여기서
  Fleet 를 import 하지 않는다.

### Testing Requirements

```bash
python -m pytest operations/signal_observation/test -q
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
