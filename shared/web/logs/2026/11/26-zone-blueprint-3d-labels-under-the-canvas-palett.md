## 2026-11-26 · 193197c657 · zone blueprint 3D labels under the canvas palette contract

- 변경: `applications/fleet/web/map/zone-blueprint-3d.js`가 라벨 텍스처를 2D 캔버스에 그리므로 `CANVAS_FILES`에 올렸다. 색은 `cssColor("--scrim")`·`cssColor("--text-primary")`, 글꼴은 `window.RosyPalette.canvasFont("label", "mono", 2)`·`canvasTextSize("label")`로 읽는다. 예외는 추가하지 않았다.
- 증거: 원격 1차 `ac950831b7`의 캔버스 계약 목록 누락 NEW 1을 같은 판정식으로 로컬에서 재확인해 통과. 원격 2차 `7aa1fe40b4` 기준 `shared/web/test/test_canvas_palette_contract.py` 포함 묶음 exit 0, known_failures NEW 0.
- gate 변화: 없음.
- 결정: 없음
- 교훈: 해당 없음 — 계약 목록 등록이며 원인은 시험에 남는다.
