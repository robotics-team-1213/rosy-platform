## D-836 업무 앱의 공정 제안·후보 배정·완료 근거 경계를 연결한다

**Status:** Accepted for implementation (2026-10-21). D-827~829의 책임 분리와 사용자의 후속 구현 지시를 구체화한다. simulation 계약 구현이며 장치·현장 수용이나 production dispatch 개방이 아니다.

### Context

외부 앱의 이동 제안을 장치 명령으로 직접 바꾸면 공정 검증과 자원 점유를 앱마다 복제하게 된다. 기존 `cell-app/compile`과 `cell-app/proposals`는 문서 revision을 검사하고 설치된 공정 compiler로 재계산한다. 따라서 새 범용 실행 endpoint를 추가하지 않고 이 경로를 소비한다. 현재 TRIP 요청은 특정 로봇만 받으며, 외부 앱이 가용 후보를 제시할 지원 계약은 없다.

### Decision

1. 업무 앱은 관측 revision과 업무 요청을 불변 회수 제안으로 계산한다. 설치된 공정 문서의 ID·digest·workcell/instance와 이동 의미의 연결은 앱의 명시적 배치 binding이다. 누락된 binding, 변경된 문서 또는 미지원 공정은 거절한다. 앱은 기하를 임의 생성하거나 플랫폼 Python·DB·ROS에 의존하지 않는다.
2. 외부 앱은 기존 `POST /api/fleet/cell-app/compile`과 `/proposals`를 사용한다. 공정 문서 확인·compiler 선택·재컴파일은 기존 Fleet 조립 책임이다. proposal/resolve는 named operator admit 및 물리 완료와 별개다. 기존 장치의 공정 산출물 재검증을 유지한다.
3. `POST /api/fleet/trip-jobs`는 기존 `robot_id` 방식과 새 `candidate_robot_ids` 방식 중 하나를 받는다. 후보는 고유한 1~8개 ID이고 모두 등록돼야 한다. 후보 방식은 `request_key`(1~128자)를 필수로 받는다. 같은 principal·key·본문은 같은 원장 행을 돌려주고, 다른 본문 재사용은 409로 거절한다. 내부 key는 `trip-pool:` namespace를 사용한다.
4. Fleet이 후보 순서대로 기존 `hold_job`과 원장 claim transaction을 사용한다. `TRIP_ROBOT_BUSY`만 다음 후보를 시도할 수 있다. capability·lease·정지·전력 등 다른 거절과 불명 결과는 fail closed다. 원장 claim 충돌은 정리 후 실패하며 다른 후보에 자동 재시도하지 않는다. 모두 busy면 `TRIP_CANDIDATES_BUSY`(409). 앱은 최종 배정이나 장치 grant를 만들지 않는다.
5. 한 Fleet 프로세스의 후보 접수는 하나의 lock으로 직렬화하고, DB `BEGIN IMMEDIATE` 안의 principal/request-key 재검사와 기존 resource claim이 재접수·다중 연결의 충돌을 막는다. 오래된 물리 점유·UNKNOWN을 만료만으로 해제하지 않는다. 완료·HOLD·재시작 후 같은 key 재접수는 새 실행을 만들지 않는다. 다른 의도의 새 실행에는 새 key와 운영자 판단이 필요하다.
6. 업무 완료는 앱의 업무 장부가 판단하고, 실행 원장은 Fleet이 소유한다. 공정 단계와 최종 업무의 필요한 근거는 task/attempt·계획 revision·독립 관측 출처·시각에 결속한다. 접수·유예·동작 성공만으로 화물 보유·퇴피·안착을 확정하지 않는다. 출처를 명시한 앱 내부 시험 근거는 플랫폼 관측 근거로 게시하지 않는다.
7. 현재 TRIP simulation profile, named operator, stop epoch, claim·lease·기존 장치 정지 경계를 그대로 유지한다. 후보 API가 다중 운행·자동 충전 허용을 추가하지 않는다.

### Alternatives

- 앱이 가용 차량을 읽은 뒤 선택: 조회와 점유 사이 경합이 생기고 앱별 배정 로직이 늘어난다.
- 새 자원 서버·workflow 언어: 현재 두 소비 계약을 해결하는 데 필요하지 않다.
- 앱이 원장·장치를 직접 호출: 재컴파일·승인·정지 경계를 우회하므로 채택하지 않는다.

### Consequences and verification

공정 binding은 설치 검증과 함께 관리해야 하며, 문서 digest가 바뀌면 새 검토가 필요하다. 후보 방식의 접수 직렬화는 최적 처리량보다 기존 안전 경계를 우선한다. Wire 변경은 API reference v1.292와 공유 request schema에 함께 기록한다.

시험은 잘못된 후보·권한·닫힌 profile, 동시 요청·같은 key 재접수/본문 충돌, claim/lease 실패·E-stop·재시작, 미확인/과거 시도/오래된 완료 근거를 포함한다. 합성 앱 시험과 실제 Fleet route 시험을 구별하고, 제품 pytest는 커밋 SHA를 원격 runner로 검증한다. 실물 활성화·자동 도킹/충전·현장 수용은 별도다.
