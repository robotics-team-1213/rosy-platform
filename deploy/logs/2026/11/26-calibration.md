## 2026-11-26 · uncommitted · Calibration 화면 신선도를 서버 예산으로, 옛 지도는 점선·흐림과 문구로

- 변경: cell_calibration_view가 robot_status.live에 age_ms·fresh_for_ms를 더하고 calibration_web 프레임 응답에 X-Rosy-Frame-Observed-At을 더함(기존 필드 불변). 화면은 TCP 신선도를 performance.now()로 예산과 비교하고(브라우저 벽시계 비교 제거), stale_map bias를 warn 색 대신 ink-quiet 점선과 '지도 지연'으로 그리며, 탑 카메라 지도 아래에 '지도 SHA 8자 · 관측 HH:MM:SS(KST) · 출처' 근거 줄을 둔다. 시각 표기는 KST HH:MM:SS, UTC 원문은 title.
- 증거: test/test_calibration_web.py(신선도 예산·Observed-At 헤더), test/test_calibration_frame_browser.py(TCP 표시·옛 지도 문구·근거 줄), applications/calibration/test/status-logic.test.mjs
- gate 변화: ARTIFACT
- 결정: 없음
- 교훈: 없음
