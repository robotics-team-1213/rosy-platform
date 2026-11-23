## 2026-11-23 · uncommitted · D-1075 Proposed: 셀 자리 이름 고정 + Rosy 컨테이너 인식을 Harbor로

- 변경: docs/adr/D-1075-cell-site-names-fixed-and-rosy-container-recognition-to-harbor.md 신규(Proposed). 자리 이름은 shared/web/cell-site-map.json(rosy.cell-site-map.v1) 하나로 고정하고 바깥 계약은 wire ref만 쓴다. 컨테이너 인식은 Rosy 비전이 셀 top 카메라로 자리별 결과를 만들고 Fleet 읽기 API로 Harbor에 낸다(경로는 D-18 순서로 나중에 확정)
- 증거: origin/main d2e25aae3a에서 확인: cell_site_targets.py:40 wire_ref, .py 전체에 camera_item_pose·cell-source-observations 없음. Harbor origin/main 095c3ec harbor/rosy_vision.py:126 image/jpeg만 받음
- gate 변화: 없음
- 결정: D-1075 Proposed
- 교훈: 없음
