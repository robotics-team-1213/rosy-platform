## 2026-11-28 · uncommitted · 셀 장치 업데이터가 한 시간 넘게 정상 단계가 없거나 green-main 포인터가 낡으면 관제 알림 창에 주의 행 한 건

- 변경: update_summary 의 channels[].alert, 콘솔 큐 행(host-health.updateAlertRows, console-refresh 60초 읽기)
- 증거: node --test update-alert 3 pass; pytest 는 원격 test_host_control.py (커밋 뒤)
- gate 변화: 없음
- 결정: D-871 개정 2026-11-28, D-632
- 교훈: 없음
