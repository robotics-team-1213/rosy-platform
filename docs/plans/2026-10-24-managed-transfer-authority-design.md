# D-856 중립 자원 종료의 owner 권한 경계

**Status:** `69607b2b0d`에서 owner 권한 경계 구현과 독립 검토·집중 원격 119 passed/skip0/0 NEW를 확인했다. affected·Fleet physical producer/claim 해제는 후속이다. 기존 Cell/Pilot profile의 동작은 유지한다. [검증과 한계](../validation/harbor-managed-arm-2026-10-24/result.md)를 따른다.

## 기존 코드에서 확인한 빈틈

`ControlSeatAdmission.acquire`는 owner lock과 로컬 unresolved Action만 검사한다. Action이 SUCCEEDED이면 Fleet claim이 남아 있어도 Pilot seat를 얻을 수 있다. Pilot/manual 명령은 Fleet authority_epoch/dispatch_generation을 자동 증가시키지 않으며 owner session_id도 그대로다. 따라서 fresh World 증거와 기존 Fleet generation만으로 관측 이후 움직임이 없음을 판정할 수 없다. 단일 Cell의 독립 goal·다중 팔의 device success 해제도 전체 링크 이탈과 후속 manual motion 배제를 제공하지 않는다.

## 새 managed profile에만 적용할 조건

첫 중립 physical profile은 **Fleet가 모든 움직임을 조정하는 owner**로 한정한다. Pilot/manual·다른 raw rule-based 경로는 이 profile에서 막고, 승인된 ARM phase만 기존 최종 owner로 보낸다. 이전 profile을 자동으로 이 모드로 전환하지 않는다. profile의 resource-policy digest는 owner journal에 영속 결속하며 활성화를 TTL 만료나 재시작으로 해제하지 않는다. 새 관리 모드가 기록된 journal은 이전 코드가 읽지 못하도록 schema version을 올린다. journal 교체·identity 변경은 조용한 unmanaged fallback 대신 명시적으로 거절해야 한다.

권한 상태는 기존 ControlSeatAdmission에 둔다. 새로운 command owner·ROS publisher·중계 서버는 만들지 않는다. 활성화는 owner lock 아래 ready·Pilot 미점유·미확정 Pilot goal/로컬 Action 없음이 확인될 때만 한다. 관리 모드에서 generic seat 획득은 거절한다. raw rule-based 명령도 phase라는 이름만으로 허용하지 않는다.

기존 `RosArmPhaseGoalPort.submit`은 같은 thread에서 같은 TrajectoryCommand 객체를 `owner.submit`에 전달한다. 그 짧은 호출에 한정한 process-local 명령 context를 사용한다. 관리된 phase port가 기존 stop/Fleet fence 아래에서 호출될 때 owner command_transaction 안에 정확한 명령 객체를 등록하고, 최종 `check_command`는 같은 thread·같은 객체·현재 owner session·managed policy의 일치를 확인한다. 호출 종료/예외에 항상 context를 지우고 중첩·다른 thread·복사/변경된 명령·만료된 grant는 거절한다. 이 context는 IPC로 직렬화하거나 caller의 identity 문자열로 만들 수 없다. 최종 owner lock 아래에서 새로운 DB/네트워크 조회를 하지 않는다.

설치 factory는 같은 ControlSeatAdmission과 journal에 bound된 managed phase port를 명시적으로 받는다. generic Action admission은 managed profile에서 ARM과 동일 policy만 허용한다. 기존 phase runner의 digest·시간·scope·stop/fence·그리퍼 검증은 그대로 유지한다. 기존 v1.305의 unmanaged library 사용과 default 거절은 보존하되, 새 Fleet physical producer는 managed profile의 identity가 검증되지 않으면 dispatch하지 않는다.

## 자원 종료와의 결합

site policy는 shared zone에 들어갈 수 있는 모든 로봇을 managed 참여자로 고정한다. 한 참여자라도 unmanaged/unknown이면 그 zone으로 dispatch하지 않는다. 첫 simulation profile은 한 owner·한 physical transfer부터 연결한다. 사용자가 승인하지 않은 실물 구성·배포·제어권 전환은 수행하지 않는다.

World는 object pose·전체 link/zone 관계·정지/그리퍼 관측을 제공하고 owner의 제어권을 부여하지 않는다. Fleet는 action/attempt·owner journal·설치 revision·trusted producer·freshness·현재 fence와 managed participant 구성을 대조해 receipt 저장/claim 해제를 한 transaction에서 수행한다. owner의 다음 명령도 Fleet claim을 획득한 새 Action만 가능하므로 관측 뒤 uncoordinated manual 이동으로 해제 조건을 무효화하지 못하게 한다. 이후 실제 receiver/HTTP 연결에서 이 전제를 검증한다.

## RED와 검증

- 새 managed 모드가 없는 기존 Pilot/Cell/PICK 회귀를 유지한다.
- 관리 모드에서는 Action 성공 뒤에도 Pilot 획득과 raw command가 거절되고 actuator 호출이 없어야 한다.
- 정확한 managed port 안의 명령만 허용하고 다른 객체/thread·호출 종료·예외 후 명령은 거절한다.
- busy/미확정 Action/Pilot 상태에서 활성화 실패, mode/policy/identity의 재시작 보존, 이전 schema 코드 거절을 검증한다.
- 실제 final owner/FakeActionClient까지 호출해 port 모양만 흉내 낸 시험과 구분한다. 정식 device·ROS·field 수용의 증거로 기록하지 않는다.

이 경계의 구현 검증 전에는 기존 generation에 새 이름을 붙이거나 World bool 하나로 shared-zone claim 해제를 열지 않는다.
