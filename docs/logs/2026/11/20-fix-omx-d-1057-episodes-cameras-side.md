## 2026-11-20 · uncommitted · fix(omx): D-1057 측면 프레임 원천에 episodes.cameras.side 폴백

- 변경: `cell_zone_verification`이 `cameras.side`가 없으면 같은 설정의 `episodes.cameras.side` 주소를 frame 호출 동안만 빌려 쓴다(둘 다 없으면 top 전용 basis). 목표 슬롯 col/row는 그대로 unverified.
- 증거: 로컬 `test/test_omx_cell_zone_verification.py`. 실물 미실시.
- gate 변화: 없음.
- 결정: 없음
- 교훈: 없음
