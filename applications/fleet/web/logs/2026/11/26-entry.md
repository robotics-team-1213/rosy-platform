## 2026-11-26 · uncommitted · 천장 분할에서 눈금자를 사이트 가장자리에, 이름표를 좌표 칩 띠 아래로

- 변경: 현장 캡처(천장 분할 1366·390): 분할 칸에서 X 눈금자가 siteBounds 여백 0.25 m만큼 바닥 그림 아래로 떨어지고, 390에서 왼쪽 위 좌표 칩이 로봇 이름표(rosy_46→y_46)를 가림. map-view drawSiteView가 눈금자 범위를 여백 없는 사이트 사각형(siteBounds(…, 0))∩보이는 칸으로 잡고, 위 40 px 띠(#959의 칩·축척 띠)를 reserveBox로 잡아 이름표가 그 아래로 비킴. 분할 칸 높이를 지도 비율에 맞추는 안은 무대 높이가 고정이라 빈 칸이 옆이나 아래로 옮겨질 뿐이어서 택하지 않음. D-766 순증 없게 fillStyle/fillRect 한 줄로 접음
- 증거: test/test_fleet_console_browser_part2.py::test_ceiling_split_keeps_ruler_on_the_site_edge_and_names_below_the_axis_chip 1366·390: 시험만 커밋에서 2건 실패(눈금 간격 31·22 px), 수정본 통과. sample 서버+모의 사이트 지도 전후 캡처 D:/DevTemp/ui-map-panel-1126/split-map/{before,after}-mock-*.png
- gate 변화: 원격 브라우저 시험만. 현장 배포·실영상 확인 전
- 결정: 없음
- 교훈: 없음
