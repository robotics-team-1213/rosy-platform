## 2026-11-28 · uncommitted · 셀 readiness는 오래된 팔 상태를 알 수 없음으로 낸다

- 변경: readiness folded는 15초 안의 live.json 또는 신선한 motor-health 접힘 증명만 사용, 보드 by-id 없음/오래됨은 state_unknown과 <arm>:state_unknown 거절, 실패 번들은 오래된 folded true를 버리고, Fleet cell-readiness와 콘솔 문구도 동일
- 증거: 원격 pytest test/test_omx_readiness_stale.py 외 readiness 관련, node web tests
- gate 변화: 없음
- 결정: 없음
- 교훈: 없음
