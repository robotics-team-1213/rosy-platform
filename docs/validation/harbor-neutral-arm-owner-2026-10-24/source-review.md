# D-856 설치된 중립 팔 실행의 독립 소스 검토

검토자: `neutral_arm_contract_review` (`rosy_contract_reviewer`). 기준 commit `01e3a174cd` 대비 설치 factory·ActionRunner/Store·IPC v2 변경을 검토했다. 기능 커밋 SHA와 원격 결과는 검증 후 [result](result.md)에 기록한다.

설치 scope/capability/config/catalog/bindings/object/resource-policy 결속, owner 기하 선택, 계획 전후 clock/freshness/revision, 매 phase 상태 검사, factory 없는 owner의 journal 전 거절, mandatory shared control과 phase-only 실행에 material finding은 없었다. 기존 phase runner·goal 취소·stop/fence·네 phase 성공과 hold→release 그리퍼 검증을 재사용하고 별도 ARM 완료 source를 기록한다. Fleet goal이나 claim 해제는 만들지 않는다.

이 판정은 독립 소스 검토다. 합성 goal/gripper ports를 사용하는 원격 planner/journal 시험, 실제 ROS owner 동작과 실물 안전 수용은 다른 증거다. 최종 SHA의 재검토와 GREEN 결과를 소스 판정과 구분한다. stale calibration/fence·완료 callback 실패·재시작의 durable 조회는 별도 회귀로 검증한다.

최종 feature commit `45173e6f927749910f5b865f790b1154b865282d`를 같은 독립 검토자가 재검토했고 material finding은 없었다. profile/kinematics/gripper 타입 검사와 phase/final 오류의 HOLD 경로를 포함한다. 후속 test-only commit `337e42e314`에서 원격 153 passed/skip0/0 NEW를 확인했다. 조회용으로 원장을 재개방하는 시험은 durable GET 증거이며 진행 중 Action의 실제 장치 재시작 수용 증거가 아니다.

SDK 확장 commit `fc5d75eecd142e9a8332625c7ac716bee4312f61`도 독립 검토했고 material finding은 없었다. ARM을 기존 v2 map·type union에 추가하며 receipt identity 대조와 timeout/재시도 없는 동작은 유지한다. 관련 원격 15 passed/skip0/0 NEW다. Fleet registry·creator·claim 해제를 활성화한 결과는 아니다.
