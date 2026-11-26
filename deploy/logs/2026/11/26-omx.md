## 2026-11-26 · uncommitted · OMX 작업대 녹화 화면 결정 반영(녹화 중지 표기, 자동 복구 우선, 녹화 시작 중립, 공용 값 일치 시험, 좁은 폭 표시)

- 변경: /stop 단추 표기를 녹화 중지로 바꾸고 전원 차단 위치를 aria-describedby로 덧붙였다. 수동 보류 카드에서 자동 복구 단추를 사람 확인 단추보다 위에 두고 주 단추를 자동 복구 하나로 줄였다. 녹화 시작 단추는 중립 채움에 빨간 점만 남겼다. 390·320 폭에서 손목 카메라 배지 겹침, 알림 단추 세로 꺾임, 12px 미만 글자를 고쳤다. 단추 동작·위치·단축키는 그대로다.
- 증거: test/test_omx_bench_decisions_ui.py, test/test_omx_bench_narrow_browser.py, 원격 test/test_omx_bench_*.py
- gate 변화: 없음
- 결정: 2026-11-26 UI 지도 패널 bench-r2 결정 1~4(사용자 나머지 처리 지시)
- 교훈: 없음
