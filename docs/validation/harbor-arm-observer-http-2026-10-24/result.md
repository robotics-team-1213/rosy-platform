# 독립 관측자와 Harbor 중립 ARM HTTP 검증

API reference v1.312. 플랫폼 source commit `bb38fdcdd0140873e4e9d0133662982c1d6a30e0`, Harbor source commit `93e71eceb310b40c573029efb49b574a834f9eff`를 고정했다. 이 문서 뒤의 metadata commit을 시험 소스로 부르지 않는다.

## 구현과 책임

- Harbor `ArmTransferBinding`은 화물·업무 위치를 설치된 물리 참조로 변환한다. public body는 key와 workcell/instance/object/source/target뿐이다. 앱에 플랫폼 import·SQLite 접근·ROS·직접 명령·admit·관측 제출 기능을 추가하지 않았다.
- Fleet은 기존 공유 SQLite의 proposal principal/key/body, 두 사람 승인, generation/CAS·모든 participant capability·claim을 대조한다. 승인 뒤 고정 Action/attempt/grant를 준비한다. 독립 raw PRE 관측 두 개가 검증·영속화된 뒤 SDK Submit을1회 수행하고 이후에는 기존 Action Get만 사용한다.
- 서버 lifespan의 monitor가 결과를 추적한다. native Action SUCCEEDED만으로 claim을 해제하지 않는다. POST 관측 두 개가 object-origin 도착·모든 link의 정지/구역 밖·빈 열린 gripper·scope/owner/session/model/calibration/transform·freshness를 만족해야 원래 owner/generation의 claim 해제와 physical receipt가 원자적으로 기록된다.
- 관측자는 expiring 별도 credential과 producer identity에 묶인다. 앱/운영자/robot/다른 producer/Channel 자격과 중복을 거절한다. observer는 proposer/approver가 될 수 없다. body는 closed raw facts이며 `clear`, 업무 성공 또는 release flag를 받지 않는다. 비어 있는 raw coverage는 unknown으로 보존하고 evaluator가 근거 부족을 거절한다.
- 상태 불명·취소·stop·owner/fence 변경·재시작은 점유를 유지한다. 더 늦은 SUCCEEDED를 읽어도 HOLD를 자동 재개하지 않는다. exact proof replay는 과거 receipt를 읽으며 새 owner claim을 해제하지 않는다.
- Harbor는 별도 physical receipt를 원래 작업/물리 참조/policy/fence와 대조한다. 이 receipt의 grant digest와 제안 body digest를 같은 해시로 비교하지 않는다. 이후에도 기존 배치·퇴피 근거와 최종 업무 완료 gate를 유지한다.

## 집중 원격 시험

모든 플랫폼 pytest는 커밋된 SHA를 공식 remote runner로 실행했다. 각 로그는 `test/known_failures.py`로 분류했다. 아래 실행은 중복되는 suite가 있으므로 pass 수를 고유 시험 수로 합산하지 않는다.

| source | 실행과 결과 |
|---|---|
| commit 18360bf0e0 | wire RED16failed/16NEW; 모델·enum leaf 부재 |
| commit 97725fd099 | monitor RED3failed20passed/3NEW |
| commit 39ef770c60 | 잘못 지정한 path로 collection exit4/no tests; acceptance 아님. 정정 실행은1178passed/2failed(Version header)/2NEW |
| commit 4957d31670 | observer/unknown/store guard RED6failed45passed2errors/8NEW |
| commit c4bbe67fe3 | Foundation 전체·정합성·dispatcher·observer·store·기존 job API·문서1266passed, skip0,0NEW |
| commit f1d207eb2f | 추가 credential isolation/expiry/unknown/lifespan 및 dispatcher38passed, skip0,0NEW |
| commit 76baab6c8a | Channel transport/Bot token 재사용 RED2failed/2NEW |
| commit dc5dbe55af | observer/dispatcher/Channel64passed, skip0,0NEW |
| commit 743e55f4a4 | FULL에서 발견한 auth/secret gate 집중121passed1failed/1NEW; 남은 finding은 test lambda 형태 |
| commit bb38fdcdd0 | auth/observer/release guards122passed, skip0,0NEW |

Local runner의 한 실행은 UTF-8 로그를 저장한 뒤 출력 encoding에서 실패했다. 저장된1178passed/2failed 로그를 원본으로 분류했으며 성공으로 간주하지 않았다. 이후 runner 출력 encoding을 UTF-8로 고정했다. 버전 pin 보완은 원래 header·assertion 문맥을 복구했고 시험 강도를 낮추지 않았다.

기존 secret scanner가 새 증거의 bare Git/SHA256 값과 test callback을 거절했다. 공개 자료에 commit/SHA256 유형을 명시하고 fixture를 console method로 표현했다. hash 값과 이전 결과는 유지했다. scanner·allowlist·release guard의 제외 규칙은 바꾸지 않았다.

## 독립 HTTP와 기존 소비자

양쪽 clean checkout을 Git bundle로 시험 PC에 전달했다. launcher는 두 전체 SHA와 clean 상태를 검사한다. 임시 자격·장부는 Git 밖 loopback simulation에만 생성한다. 원본 로그는 작업 공간 `Rosy/docs/workspace-records/2026-10-24/harbor-arm-http-evidence/`에 보존한다.

| 양 끝 source bb38/93e71 | 결과 |
|---|---|
| ARM module 진입 / 파일 진입 | 각각1test, exit0, skip0; 같은 시나리오의 진입점 검증 |
| 실제 SDK Unix framing | 각각 SubmitAction1, GetAction1 |
| 별도 credential의 PRE_DISPATCH/POST_ACTION | 각각1개 proof; Harbor child에 승인자/관측자 자격 없음 |
| 플랫폼 미import Harbor child / 다른 stdlib 소비자 | child의4개 플랫폼 namespace 미import assert; 같은 receipt 조회 |
| rosy_cell import가 차단된 ARM 서버 | compiler·recipe/cell seed 없이 실행 |
| 물리 성공 뒤 업무 원장 | WAITING 유지; 근거 없는 confirm·재제안 거절; 다른 principal receipt403 |
| 기존 Cell HTTP / 중립 TRIP HTTP | 3tests / 1test, 각각 exit0/skip0 |

Harbor 기본 unittest discovery는91tests/exit0/skip1(90pass)다. 환경 미설정으로 skip한 기존 통합 진입과 위 명시 HTTP 실행을 구분한다. 최초 harness IPC framing 누락과 module import 결함은 실제 RED를 보존하고 최종 source에서 두 진입을 확인했다. Harbor의 ADR0006과 같은 검증 문서가 앱 측 책임을 기록한다.

## 독립 소스 검토

`neutral_arm_contract_review`가 wire/observer/route/SDK·SQL/claim 경계를 읽고 empty unknown P2와 Channel credential P1을 지적했다. 각각 RED 뒤 보완·재검토했다. 최종 source bb38의 좁은 auth 보완에서도 supported material finding은 없다. 이는 소스 검토이며 물리 수용 판정이 아니다.

| reviewed source | LF-normalized SHA256 |
|---|---|
| app.py | sha256: b7b02c459576657c3818512fa54e73c99903fd1af4e4fafb91d9e61ba005845e |
| physical_transfer_observer_routes.py | sha256: 88d93b35d46f7ffb82542b916d8afdd635f7b18920fe232d3dba466c57e2e216 |
| physical_transfer_observer.py | sha256: abbcb158545cf9fa3b13a84a5d3bc301c8d817f9c9138052e02ab337fdb42e92 |
| arm_transfer_observations.py | sha256: 3432e4035b99a8773231c1c3e6121448cf368b6567fa0788536bf28c70ae9729 |

## FULL과 수용 한계

이전 source dc5의 FULL23 전체 실행은 exit1로 종료했다. 23개 로그를 모두 공식 분류했고 run21(secret gate)과 run12(ai_observer auth gate)의 실패가 각각1NEW이며 나머지21개는 exit0/0NEW다. [원본 전체 manifest](dc-full-run-summary.json)에 targets·summary·skip·공식 분류를 보존했다. 이를 위 집중 GREEN이나 이전 source58/schema6의 FULL 성공으로 덮지 않는다.

최종 source bb38의 FULL은 2026-10-25 exit0으로 종료했다. 원본 selector `rosy-physical-api312-bb-selection.json`의 metadata/mode/full_invocations를 보존하고, 실행 JSON의 local_invocations만 원래 full_invocations23개 전체로 확장했다. 추가 skip/ignore는 없으며 원본 selector의 ignore 인자를 그대로 유지했다. [최종 전체 manifest](full-run-summary.json)에23개 targets·summary·skip·공식 분류를 보존했다. 각 호출은 exit0이며 공식 분류는 모두0NEW/0known/0flaky다. 독립 증거 검토도23개 원본 로그·selector·manifest를 대조해 오류가 없음을 확인했다.

주요 묶음은 common/CORE7415passed91skipped, Fleet6479passed336skipped, root9707passed1135skipped, 장치/UI/관련 모듈2031passed298skipped다. suite가 겹치므로 이를 고유 시험 수로 합산하지 않는다. skip은 실행하지 않은 범위이며 위 explicit HTTP의 skip0와 구별한다. root에는 이전 G1 strict timing 검사도 포함되지만 이번 통과가 과거 실패 원인을 해결했다는 뜻은 아니다.

이 HTTP 하네스의 bounding boxes·영 속도·물체 자세는 synthetic fixtures다. 인증·통신·원장·점유 종료·소비자 독립성의 근거이며 physics·native actuator·센서 보정·실물 현장 수용의 근거가 아니다. 운영 producer·현장 binding·실패/취소 후 물리 정리와 명시적 복구/재승인은 후속이다. 실물 profile·push·merge·deploy를 개방하지 않았다.

2026-10-25 metadata commit `6f5e71dfa6`의 공식 원격 release/harness/architecture/계약 문서/버전 guard는235passed/skip0/0NEW다. metadata를 포함한 secret scan은0findings, module lint는0errors/33warnings, source730부터6f까지14개 commit의 size/safety 검사는 각각exit0이다. 실행 소스 bb38과 이 문서 검증 소스를 구분한다. 양쪽 소유 checkout은 각각 커밋해 보존했으며 착지·push는 수행하지 않았다.

CE: 새 교훈 해당 없음 — 구현·시험·ADR로 판단을 복원할 수 있다. 과거 G1 timing 원인은 여전히 미해결이며 새 단독 통과를 원인 해결로 부르지 않는다.
