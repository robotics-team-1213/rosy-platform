## 2026-11-26 · uncommitted · 관제 지도 눈금자 이름표 겹침 수정

- 변경: PR #925가 관제 지도를 활성 지도 범위로 맞춘 뒤에도 눈금자(drawMapDatum)는 카메라 사각형 전체를 받아, 화면 밖 눈금 이름표가 캔버스 가장자리로 몰려 겹침(X0/X1, X6/X8, 0/Y-1)·위쪽 이름표가 좌표 칩에 가려짐. map-view drawSiteView가 격자 범위와 보이는 칸(여백 32, 위 좌표 칩 띠 40 안쪽)의 겹침만 눈금자에 넘김. D-766 순증 없게 map-view 두 곳 접음
- 증거: test_sample_browser.py::test_control_map_ruler_labels_stay_apart_inside_the_map 1366·390 원격: 시험만 커밋(af025bbfdc) 2건 실패(X-1/X0 등 겹침), 수정본 통과. sample 미리보기 전후 캡처 D:/DevTemp/ui-map-panel-1126/map-ruler/{before,after3}_*.png
- gate 변화: 없음
- 결정: 없음
- 교훈: 없음
