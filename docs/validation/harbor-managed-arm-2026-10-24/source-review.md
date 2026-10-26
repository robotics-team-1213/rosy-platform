# D-856 managed physical owner 소스 검토

기준 `ed5eecc216`, 검토자 `neutral_arm_contract_review` (`rosy_contract_reviewer`). 관리 모드의 영속 scope/policy, Action admission, phase journal과 synchronous command context, 기존 stop fence와 최종 ArmCommandOwner까지 독립 검토했다.

첫 검토에서 constructor의 cached schema version이 동시 managed 활성화를 덮어쓰는 경합과 delegate의 실제 owner 결속 누락을 지적했다. schema 생성·scope 읽기·version 기록을 `BEGIN IMMEDIATE` 한 transaction으로 묶고, native phase port가 노출하는 `command_owner`와 실제 admission/recorder/action/attempt의 동일성을 검사하도록 수정했다. 결정적 동시 초기화와 잘못 연결된 owner 회귀를 추가했다. 수정 소스 재검토에서 두 finding은 해소됐고 추가 material finding은 없었다.

원격 시험·고정 기능 SHA 재검토는 이 소스 판정과 별도 증거다. 관리 모드는 새 프로파일의 명시적 opt-in이며 기본 Cell/Pilot 구성은 유지한다. Fleet physical producer와 claim 해제는 여전히 닫혀 있고, 실제 ROS·장치·현장 수용이나 배포를 입증하지 않는다.

고정 기능 SHA `e4b2c6c3c0ff8082e62ae9747cbc2f9d4b4dde2f` 재검토도 material finding 없음이었다. 추가 edge 검토에서는 context 발급 뒤 최종 writer 직전 grant가 만료되는 경우를 보강했다. test-only `69295d4b9e`의 원격 실행은 유효 명령 1 passed, 만료 명령이 실제 FakeActionClient에 `submitted`되는 1 failed를 확인했다. 최초 수기 owner 설정의 rate limit 누락 실패와 이 유효한 RED를 구분한다. context의 pure-clock validator를 최종 check_command에서도 실행하고 finally에서 제거한다. 관리 모드 활성화는 실제 owner에 결속된 admission만 허용한다. 이 수정 소스의 독립 검토에서 material finding은 없었으며 GREEN·최종 SHA 판정은 별도다.
