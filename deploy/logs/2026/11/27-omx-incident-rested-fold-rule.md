## 2026-11-27 · uncommitted · OMX 사건 보고: 토크 끈 쉬는 접힌 팔을 "펴진 팔"로 오판하지 않게(좁힌 규칙)

- 변경: omx_incident.facts의 folded는 원래 HOME_TOL(3) 식 그대로다. 별도 사실 rested_folded(시작 라이브러리 접힘 자세로 cell_job_peer_health.live_folded가 calibrated 기준만 접힘이라 하고 몸 관절이 모두 core_common REST_TOL(8) 안)를 decide()의 "토크 꺼짐 + folded 아님" 가지에서만 읽는다. rested_folded가 참이면 guarded_home_decision을 부르지 않고 그 아래 기존 검사로 이어진다. rested_folded 계산용 라이브러리 읽기만 OSError/ValueError/객체 아님이면 None이고, home 조회는 예전처럼 읽기·파싱 오류를 그대로 낸다. is_home_recovery가 참이면 쉬는 자세여도 guarded_home_decision을 예전과 똑같이 부른다.
- 지키는 ADR 줄: D-1047(쉬는 팔이 folded를 대신하는 것은 링크 끊김 종류만, 공원 변형 정지는 3 이내 folded 필요)과 D-1048(home 3 이내)은 건드리지 않는다. Fleet이 믿는 folded(machine_clearable, software_stop, 위험 점수의 drift 감점)는 넓어지지 않는다. rested_folded는 BoundedJson facts의 여분 키이며 core_common은 읽지 않는다.
- 증거: 2026-11-27 arm_s 세션 끝 자세 [0.22, -58.53, 54.68, 49.84, -4.66]가 세 번 사건을 열었고 같은 자세를 준비 상태 규칙은 접힘으로 읽음. 시험 test_omx_incident.py(쉬는 자세 무사건·folded False 고정, latched 유지, 몸 9 단위 사건 유지·7 단위 무사건, 라이브러리 없음/깨짐)
- gate 변화: 없음(펴진 팔 탐지는 약해지지 않음)
- 결정: D-1048 보완 기록(쉬는 자세 REST_TOL 8은 사건 열기 결정에서만 펴짐 아님; 통신 끊김 복구는 예전 그대로 보류, 라이브러리 읽기 실패는 home 조회에서 예전처럼 오류)
- 교훈: 없음(셀 수용 전)
