## 2026-11-26 · uncommitted · 관제·현장 지도·보정 맞춤을 fitBox 하나로

- 변경: site-map-model.js에 mapBounds·fitBox(축척·px 여백·y 뒤집기·화면 방향·3×3 matrix)를 두고 fitView, 관제 지도(map-view·camera-backdrop의 fitTransform+quarterTurn), 보정 topDownLayout이 그것을 부름. 관제 지도는 같은 좌표계의 활성 지도가 있으면 현장 지도와 같은 범위(장소·도로·시설)로 맞추고, 없을 때만 카메라 사각형. 화면 방향 검사는 viewTurnOf 하나(siteViewTurn 삭제). D-515 이후 호출자 없는 cameraScreenToMap·quarterTurn 삭제, test_only_exports 상한 4→3
- 증거: node --test operations/fleet/test/web 624 통과(site-layer·map-plane·map-datum·trail-view 시험을 fitBox로 같은 기대값 유지)
- gate 변화: 없음
- 결정: 2026-11-26 지도 패널 추천안(사용자 승인)
- 교훈: 없음
