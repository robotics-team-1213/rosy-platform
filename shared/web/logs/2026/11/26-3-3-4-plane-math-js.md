## 2026-11-26 · uncommitted · 3×3 평면 투영 사본 4벌을 plane-math.js 하나로

- 변경: shared/web/plane-math.js(invert3·project)를 /common 자산으로 추가하고 Fleet map-fit.js·measured-calibration-view.js·field-layers.js·start-point-layer.js와 Calibration grid-projection.js의 사본을 그것으로 바꿈. 특이 임계 1e-15, 지평선 w≤1e-9는 null(가장 엄격한 규칙). test_shared_dedupe HELPERS에 invert3 행(Calibration 화면 포함), test_only_exports 상한 5→4
- 증거: node --test operations/fleet/test/web (plane-math.test.mjs가 옛 사본과 동일성·차이 고정) 로컬 통과; 원격 pytest는 갈래 보고에 기록
- gate 변화: 없음
- 결정: 2026-11-26 지도 패널 추천안(사용자 승인)
- 교훈: 없음
