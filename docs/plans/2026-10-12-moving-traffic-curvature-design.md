# 이동 후보의 교통 감속 곡률 보존

목적은 교통 정책의 감속 때문에 관측·판정된 주행 호가 더 좁아지는 문제를 고치는 것이다. 사용자 지도 완주 수정 권한과 Leg6 독립 재생에 근거하여 공유 TrafficPolicyManager의 기존 경계를 수정한다. 새 backend·모델·설정·API 필드는 만들지 않는다. 실제 주행은 별도 승인된 후속 실행이다.

선택한 안은 ENFORCED의 FOLLOW/APPROACH/PROCEED에서 이동 후보 `v != 0`에 `(s*v, s*w)`를 반환하는 것이다. 정지 상태 회전 `v == 0`은 기존 각속도를 유지한다. HOLD는 `(0,0)`, DISABLED/MONITOR_ONLY는 원래 후보를 유지한다. bridge 전용 사후 보정은 공유 정책 결과와 issued trail의 의미가 갈라지므로 선택하지 않는다. 선택 옵션 추가도 필요하지 않다.

유일 제품 호출자는 기존 `traffic_gate.apply_line_candidate`다. static profile clip → 현재 line revision 검사 → 현재 traffic revision 검사 → CommandManager의 곡률 보존 제출·최종 제한 순서를 유지한다. 기존 D-422 tighter-arc family는 원래 호를 포함하는 보수적 상위 집합으로 남겨 clearance를 완화하지 않는다. 이 변경은 벽 의미 오탐·목표 궤적·Fleet 속도 cap 전달 문제를 해결했다고 주장하지 않는다.

검증은 실패를 먼저 확인한 뒤 진행한다. 이동 직진·좌우/후진 호·제자리 회전·zero와 정책 네 상태/세 모드, dwell 이후 PROCEED, stale/current revision, 실제 CORE command SDK와 issued trail을 검증한다. D-422 몸 쓸기·출력 경계·관측 거리/법칙 회귀와 모듈 예산도 확인한다. 원격 CPU·메모리 기준 미달이면 기다리고 fallback 시험을 수용하지 않는다. 전체 CI, 실제 Gazebo, 실물 수용은 원격 단위 시험과 구분한다.
