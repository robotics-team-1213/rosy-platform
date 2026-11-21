## 2026-11-21 · uncommitted · pixel-measuring browser files run as lab evidence

- 변경: tools/harness/affected_browser.py LAB_FILES에 test_pilot_browser.py, test_pixel_workspace_browser.py, test_review_flow_browser.py 추가 (GitHub runner에서는 폰트 때문에 렌더 크기가 달라 정지 상자 85.89 px 대 82±1로 실패, lab PC는 통과); 시험 1개 추가
- 증거: #428 #430 #433 #435 CI 실패 로그 (browser-overlay-1of6/6of6, browser-alone), lab PC에서 origin/main과 #430 head 모두 통과
- gate 변화: 세 파일은 CI 대신 pr_land --evidence의 lab 실행으로만 확인; CI 폰트가 lab과 맞으면 LAB_FILES에서 줄을 지워 되돌림
- 결정: 없음
- 교훈: 없음
