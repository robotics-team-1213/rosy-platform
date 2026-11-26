## 2026-11-26 · uncommitted · 천장 분할에서 가로형 지도는 위아래로 쌓고, 이름표가 로봇 원을 피함

- 변경: 현장 캡처(22-1366·24-390): 천장 분할의 좌 58% 칸이 세로로 길어 가로형 사이트가 가운데 떠 위아래가 빔(1366 42%·1920 36%), 390에서 #977의 위 40 px 띠를 피해 내려온 이름표가 맨 위 로봇의 원을 덮음. map-view가 지도 맞춤 범위(회전 반영)로 stage data-map-shape=wide|tall을 두고 device-watch.css는 쌓기를 기본, 넓은 창의 세로형만 좌우로 나눔(천장 단추는 두 배치 모두 영상 오른쪽 아래). drawGuide에 reserve를 줘 사이트 보기에서 로봇 원 상자를 칩 장애물로 잡음(__mapMarkers는 그대로라 격자 보기 3개 표식 시험·칩 배치 불변). 지도 무대 높이를 줄이는 안은 빈 칸이 패널 아래로 옮겨질 뿐이라 택하지 않음. 쌓은 칸은 높이에 맞아 좌우 여백이 남음
- 증거: test/test_fleet_console_browser_part2.py::test_ceiling_split_fills_the_map_cell_and_names_clear_their_robot 1366·390·1920. sample 서버+모의 3×2 m 사이트 전후 캡처 D:/DevTemp/ui-map-panel-1126/split-rest/{before,after}-mock-*.png: 빈 띠 1366 0.42→0, 1920 0.36→0, 390 0→0, 390 이름표-원 겹침 있음→없음, 천장 끔 화면 픽셀 동일
- gate 변화: 원격 브라우저 시험만. 현장 배포·실영상 확인 전
- 결정: 없음
- 교훈: 없음
