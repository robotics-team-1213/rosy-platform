# D-716 모델 후보와 기존 단일 Fleet 복구 dispatch 연결

**Status:** Proposed (2026-10-12, implementation contract under review)

## 현재 소스와 문제

D-715까지의 incident worker는 line_follow Problem의 reobserve/human만 선택하며 허용된 incident 도구도 get_incident_status뿐이다. 기존 StuckResolverLoop가 별도로 규칙 답을 선택·전송한다. 이 상태의 판단 JSON·모델 합의·최종 cmd_vel 녹화만으로 모델이 문제를 물리적으로 해결했다고 할 수 없다. 정상 주행 속도 역시 불필요한 모델 명령과 같은 의미가 아니다.

## 결정 방향

첫 물리 backend는 Pinky의 기존 BACK_AND_RETRY 답 하나다. 새 ROS publisher·CORE URL·거리/속도 명령은 만들지 않는다. CORE D-407의 local_enabled·시도 수·몸 기하·뒤 여유·scan freshness·사각/trail와 최종 cmd_vel 권한은 유지한다. 기존 CORE 로컬 복구 기본값과 설치 설정도 이 변경으로 바꾸지 않는다. 아직 ASKING인 동일 사건에만 모델 후보를 검토하고 이미 CORE 로컬 복구가 처리한 사건은 관측 결과로 기록한다.

모델은 고정된 허용 후보를 제안한다. JSON에 속도·거리·주소·토큰·임의 코드를 받지 않는다. 새로운 choice/tool을 기존 공통 catalog/판정/receipt에 정의하고, 설치 프로파일·보정·signed 운영 수용을 모두 정확한 revision에 결속한다. 자기 보고 확률·PASS_OFFLINE_ONLY·모델끼리의 합의는 물리 조치 허가가 아니다. 수용되지 않은 모델은 기존 읽기·제한 재평가와 최종 인수만 한다.

Fleet 사건 원장에 case/profile/policy/input/generation별 후보를 기록하고 **기존 StuckResolverLoop 한 곳**이 이를 소비한다. worker가 별도로 _answer나 RobotClient를 호출하지 않는다. 규칙·모델 후보 중 실제 전송 하나를 고르고 현장 법칙·사람 claim·현재 사건/근거·클라이언트·예산을 await 전후 다시 확인한다. 같은 ASKING 사건에 rule과 model이 병렬 전송되는 경쟁을 실제 시험으로 막는다. 모델 경로의 첫 한계는 사건당 신규 물리 제출 최대 1회이며 CORE 자체 복구 시도 수와 별도다. profile 교체·새 관측·재시작이 이 한계를 초기화하지 않는다.

후보 기록/선택, 제출 시작, CORE 응답, 이후 종결 관측을 서로 다른 사실로 남긴다. CORE의 back 응답은 접수 사실이며 실제 후진·차선 회복 완료가 아니다. 취소·timeout·연결 단절·이미 제출된 상태의 재시작은 UNKNOWN과 미해결 인수로 남기고 재제출하지 않는다. 새 owner의 사건에 정지/취소를 보내지 않으며 기존 CORE의 bounded 실행·안전 계약을 유지한다. 성공은 새 trusted CORE 상태와 최종 출력 원본을 사건에 결속하고 별도 독립 평가로 확인한다. 현재 observe_closure의 NONE/UNVERIFIED를 모델 기여 성공으로 바꾸지 않는다.

## 구현 전 고정할 네 경계

1. **CORE 적용 시점:** Fleet의 마지막 ASKING 조회만으로 허가하지 않는다. 실제 `StuckWiring.stuck_decision`과 tick이 공유하는 manager lock 안에서 예상 사건·phase·episode를 확인한 뒤 적용한다. 먼저 BACKING/SETTLING 중 중복 BACK 답의 타이머·시도 재시작을 거절하고, 모델 제출에는 ASKING 일치 조건을 결속한다. 기존 사람의 WAIT/ABORT와 WAITING_CONSOLE 수동 처리 계약은 보존한다.
2. **규칙과 모델 선택:** 모델 후보의 ready/inflight/missing/rejected/stale를 구분한다. 적격 inflight일 때만 CORE의 남은 ASKING 시간보다 짧은 고정 대기 상한까지 기다리고, 만료·거절·누락에서는 기존 규칙 경로로 돌아간다. ready 후보도 현재 법칙·운영 수용을 통과해야 한다. 기존 `pipeline.ai_hold` 제안 검증을 가짜 legacy AI 패킷으로 통과시키지 않으며 새 typed 후보에는 동등한 명시적 검증 경계를 둔다. CORE 로컬 복구 타이머와 설치 기본값은 그대로다.
3. **signed 운영 수용:** 기존 `reasoning_calibration`과 구별되는 receipt kind를 정의한다. trusted 검수 principal, full profile/model revision, domain, calibration artifact digest, action contract/policy revision, site installation identity와 독립 품질·coverage 근거를 결속한다. 폐기·누락·다른 설치의 receipt는 물리 admission을 거절한다.
4. **최종 제출과 폐기:** await 이후, durable physical claim 직전에 현재 trust·보정·운영 수용을 다시 검증한다. 승인 revision/epoch와 claim의 원자적 순서를 정해 claim 전에 폐기되면 거절하고, 이미 제출 중이면 UNKNOWN을 보존하며 재전송·다른 owner 취소를 하지 않는다. 폐기와 claim 경쟁은 제어된 이벤트 시험으로 재현한다.

이 네 경계는 아직 구현할 계약이다. 실제 source 경로와 시험은 [실행 계획](../plans/2026-10-12-model-led-bounded-incident-recovery.md)에 둔다.

## 범용 확장과 증거

door와 arm_target은 각자의 관측·소유자·행동·성공 계약 backend를 같은 후보/결과 틀에 연결한다. arm의 최종 실행 owner를 CORE base writer로 대체하지 않는다. Jev/Laya를 포함한 모델은 같은 고정 프로파일/JSON 계약을 사용하며 text-only 모델에는 구조화된 사실만 전달한다.

정상 DO_NOT_INTERVENE에는 후보·제출·모델 호출이 없어야 한다. 전체 관측/후보/명령 창의 수집 누락과 actor/case/generation 상관관계를 검증하기 전 정상 무명령·모델 기여·재발을 0으로 채우지 않는다. 공통 receipt가 확장되면 SDK 버전·Fleet 요구·CI/local execution pin과 모든 소비자·실제 wheel/sdist를 함께 갱신한다. 별도 영속 전환과 기존 사건의 pinned 프로파일/예산/UNKNOWN은 유지한다.

이 ADR은 실제 motion·모델 호출·배포 승인이 아니다. runtime 구현·독립 검토·signed 운영 수용·현장 readback은 아직 필요하다.
