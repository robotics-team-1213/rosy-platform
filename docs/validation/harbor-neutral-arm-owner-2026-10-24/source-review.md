# D-856 설치된 중립 팔 실행의 독립 소스 검토

검토자: `neutral_arm_contract_review` (`rosy_contract_reviewer`). 기준 commit `01e3a174cd` 대비 설치 factory·ActionRunner/Store·IPC v2 변경을 검토했다. 기능 커밋 SHA와 원격 결과는 검증 후 [result](result.md)에 기록한다.

설치 scope/capability/config/catalog/bindings/object/resource-policy 결속, owner 기하 선택, 계획 전후 clock/freshness/revision, 매 phase 상태 검사, factory 없는 owner의 journal 전 거절, mandatory shared control과 phase-only 실행에 material finding은 없었다. 기존 phase runner·goal 취소·stop/fence·네 phase 성공과 hold→release 그리퍼 검증을 재사용하고 별도 ARM 완료 source를 기록한다. Fleet goal이나 claim 해제는 만들지 않는다.

이 판정은 독립 소스 검토다. 합성 goal/gripper ports를 사용하는 원격 planner/journal 시험, 실제 ROS owner 동작과 실물 안전 수용은 다른 증거다. 최종 SHA의 재검토와 GREEN 결과를 소스 판정과 구분한다. stale calibration/fence·완료 callback 실패·재시작의 durable 조회는 별도 회귀로 검증한다.
