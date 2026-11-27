## 2026-11-28 · uncommitted · OMX 벨트 자세 범위를 번들이 선언(Panel N)

- 변경: cell_belt_pose가 ENV_STATE.json belt_reference.range(dx_m·dy_m·yaw_rad)를 쓴다. 없으면 기존 RANGE. 형식 오류나 상한(dx -10~+40 mm, |dy| 35 mm, |yaw| 20도) 초과는 기본값으로 되돌리지 않고 BELT_POSE_UNKNOWN(NOT_AVAILABLE)으로 거절한다. OUT_OF_RANGE 문구에 쓴 범위를 찍는다. omx_env_state.py --range가 선언을 쓴다.
- 증거: test/test_omx_policy_belt_pose.py 새 시험, 원격 48 passed 2 skipped, 0 new
- gate 변화: 값을 자르지 않는 거절 유지, 번들별 범위는 고정 상한 안에서만 넓어짐, 팔 동작 코드 불변
- 결정: 없음
- 교훈: 없음(셀 수용 전)
