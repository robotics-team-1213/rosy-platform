# Harbor–ROSY 업무와 동작 경계 Implementation Plan

> **For agentic workers:** 구현을 시작할 때 `superpowers:executing-plans`로 단계를 순서대로 수행한다. 각 체크박스는 산출물과 확인 근거가 있어야 닫는다. 병렬 구현은 별도로 선택하지 않은 상태다.

**Goal:** Harbor가 업무 공정과 완료를 소유하고 ROSY는 로봇 동작·자원·실행 결과·안전을 소유하도록, 기존 소비자를 보존하며 한 흐름을 분리한다.

**Architecture:** Harbor 내부 공정 변환부가 지원 동작 요청을 만든다. Fleet이 기존 권한·승인·실행 원장·claim으로 접수하고 장치 owner가 실행한다. Harbor가 결과와 독립 관측을 업무에 반영한다.

**Tech Stack:** 기존 Harbor Python 3.10+ / 표준 라이브러리 / SQLite, Fleet FastAPI·기존 protocol schema, 기존 OMX owner와 simulation 시험 하네스. 새 의존성·중계 서버·메시지 브로커를 추가하지 않는다.

**Spec:** [D-856](../adr/D-856-application-action-boundary.md). 책임 경계의 정본은 ADR이며 이 문서는 단계·산출물·검증·인계를 관리한다.

## 실행 상태와 선행 조건

2026-10-24 실행 중. 사용자의 “목표잡고 진행” 지시로 문서 등록 뒤 구현·원격 검증을 진행한다. P0는 완료했다. P1의 첫 TRIP 계약과 P2/P4/P5의 해당 slice는 구현·HTTP 검증했지만, 팔 중립 실행과 Harbor 공정 변환까지 포함한 전체 단계는 미완료다. 각 상세 계약을 검토한 뒤 그 범위의 구현을 진행하며 아직 정하지 않은 public path·wire 필드를 제공 API로 선언하지 않는다.

문서 등록은 사용자의 2026-10-24 “바로 처리” 지시로 `docs/application-action-boundary` 작업용 worktree 1개 일회 추가 예외를 사용한다. 기존 등록 15개·고아 디렉터리 3개를 보존했다. 예외는 문서 등록과 검증용이며 추가 제품 구현 슬롯·착지·push 승인으로 확대하지 않는다. 검증 후 다음 실행 전까지 브랜치·증거를 보존하고 소유자 정리 절차로 슬롯을 회수한다.

이후 기존 브랜치는 `feat/application-action-boundary`로 전환됐다. 동료의 병합이 끝나고 슬롯이 9개로 줄어든 뒤 정규 예산 안에서 `app-neutral-actions`/`feat/neutral-arm-actions`를 생성했다(base `ba256ec45d`). 팔 구현은 이 격리 작업 공간이 소유한다. 과거 문서 슬롯 예외를 확대하지 않았으며 착지·push·배포·실물은 수행하지 않는다.

| 산출물 | 확인한 상태 | 남은 범위 |
|---|---|---|
| P0 ADR·Log·계획 | `f14d00748e` 문서 원격 552 passed | 없음 |
| [TRIP 상세 계약](2026-10-24-application-action-contract-design.md) | 조회/응답 유실 대조 구현, Harbor와 독립 HTTP 1 passed, 기존 Cell HTTP 3 passed | 팔 공정 변환을 대신하지 않음 |
| [중립 팔 계산](2026-10-24-neutral-arm-planning-design.md) | 기존 Cell provenance 보존, 관련 원격 135 passed, 독립 검토 | 실제 실행 통합은 아래 owner 행 참조 |
| [팔 catalog·사전검사](2026-10-24-neutral-arm-preflight-design.md) | API v1.299·owner/Fleet HTTP 연결, 신규/기존 원격 213 passed/skip0, 실제 HTTP/UDS·독립 검토 | 중립 실행 통합은 아래 원장/owner 행 참조, 설치 wheel·장치 수용 |
| [step grant 검증 경계](2026-10-24-step-grant-boundary-design.md) | typed kind·공통 identity와 종류별 전체 payload 분리, 원격 184/152개 별도 회귀·독립 검토 | 실제 물리 producer·등록 kind·실행 |
| [중립 팔 실행 계약](2026-10-24-neutral-arm-execution-design.md) | 물체–기하 결속 원격 112개, v1.303 grant·기존 소비자 원격 1385개 및 독립 검토 | 실제 physical producer·전체 자원 종료·Harbor 변환 |
| [원장 provenance](2026-10-24-neutral-arm-ledger-design.md) | version5 schema·Cell 소비자 차단, 원격 69/13/244개 별도 회귀와 affected 두 그룹 통과 | 물리 생성/승인·claim 종료 연결 |
| [owner 실행](2026-10-24-neutral-arm-owner-design.md) | 내부 복구 74개, v1.305 설치 factory/phase-only IPC 153개·v2 client 15개 별도 회귀 및 독립 검토 | actual admitted-state/HTTP·Fleet producer·물리 종료·Harbor 연결 |
| [managed owner 권한](2026-10-24-managed-transfer-authority-design.md) | 영속 mode/최종 명령 경계, 집중 119개·affected 1754 passed/34 skipped/0 NEW | 실제 ROS/장치·승인/물리 종료 |
| [실제 capability/대상 owner](2026-10-24-managed-transfer-capability-design.md) | API v1.306·canonical journal/session·receipt/404 결속, 집중790/0 NEW, FULL표행1NEW 수정 후 entry9 7371 passed/91 skipped/0 NEW(다른22개원본0NEW), 독립 검토 | Fleet physical producer·claim 종료·Harbor ARM |
| [물리 종료/producer 계획](2026-10-24-neutral-transfer-closure-and-producer-design.md) | 독립 architecture/critic 3회 검토 approve, World 사실/Fleet atomic claim/Harbor 업무 분리와 object origin·실행 전 점유 확인 명시 | policy·물리 관측·승인/producer·Harbor 연결 구현 |
| [World 물리 관측 자료형](../validation/harbor-physical-observations-2026-10-24/result.md) | source084 불변 raw facts·미측정 속도 None 보존·독립 wheel, World28/affected764 passed·0 NEW | 실제 producer 인증·두 표본 freshness/모델 coverage·Fleet 판정/claims |
| 전체 P3–P5 | 진행 중 | 중립 팔 실행의 승인/자원 종료, Harbor 공정 변환, 복구·독립성 통합 증거 |

첫 HTTP 증거는 플랫폼 commit `a8a7d66121597bec9ee5efa2d25e66e0dbfc75c1`과 Harbor commit `0ee812f2ebd9aa83f160534b53d1e711ee755416`의 고정 조합이며 새 팔 구현의 검증으로 대신하지 않는다. 전체 회귀에서 확인한 기동/오류 문구 회귀는 별도 수정·재검증하고 FULL 통과와 개별 회귀 통과를 구별한다.

공개 사전검사 commit `754d5ca7bf`의 후속 FULL은 문서 검사 두 종류와 충전 status 조회 타임아웃으로 실패했다. 문서 검사는 수정 후 통과했으며, 같은 SHA의 충전 해당 node는 단독 재실행에서 통과했다. FULL 실패의 재현 조건과 추가 전체 검증은 미완료로 유지한다. 상세는 위 사전검사 검증 기록을 따른다.

## Global Constraints

- 업무 정책과 `MoveEvidence`의 업무 필드는 Harbor 소유다. 공통 실행에 항만 완료 상태를 추가하지 않는다.
- 외부 앱은 HTTP/JSON만 소비한다. 플랫폼 Python·DB·ROS·장치 Unix socket에 접근하지 않는다.
- Fleet Action과 장치 내부 Motion Intent는 다르다. 기존 Action gateway·장치 owner의 승인·검증·안전 경계를 보존한다.
- 기존 `cell-app`·`CELL_TRANSFER`는 호환 소비자가 전환되기 전까지 유지한다. 공정 digest 검증을 삭제해 중립성을 만들지 않는다.
- simulation 계약으로 실물 dispatch·자동 충전·병렬 운행을 열지 않는다. 새 배포 프로필도 만들지 않는다.
- app/instance 권한 범위·중복 방지·불명 실행 복구를 P1에서 확정한다. 자동 POST 재시도와 timeout에 의한 점유 해제를 추가하지 않는다.
- 플랫폼 pytest는 커밋된 SHA를 공식 원격 runner로만 검증한다. Harbor 단독 unittest는 해당 저장소 절차를 따른다.
- 플랫폼 계약·하네스 변경과 실행부 변경은 별도 착지 단위로 한다. Harbor 변경은 팀 fork → 원본 PR 절차를 따른다.
- 커밋·검증·게시·장치 수용 상태를 구분한다. 착지와 push는 기존 사용자 승인 범위를 확인한 뒤 수행한다.

## Review Focus

| 실패 조건 | 필요한 동작 | 소유 단계 |
|---|---|---|
| 동작 성공 뒤 화물 관측 누락·오래된 관측·팔 퇴피 미확인 | 업무 단계/최종 완료를 진행하지 않음 | P4 |
| 접수 POST는 서버에 도달했으나 응답 유실·클라이언트 재시작 | 동일 실행을 조회·대조하고 두 번째 실행을 만들지 않음 | P2·P5 |
| 같은 요청 key의 다른 본문, 다른 앱/instance의 같은 key | 충돌과 권한 scope를 계약대로 구별하고 타 앱 원장을 노출하지 않음 | P2·P5 |
| 보정 변경·허용 영역 위반·정지·claim 경합 | 장치 owner와 Fleet이 거절하며 앱의 성공 판정으로 우회되지 않음 | P3 |
| Harbor/palletizing 미설치, 공정별 데이터 없이 동일 동작 호출 | 공통 실행은 기동·실행하고 미지원 동작은 접수 전에 거절 | P3·P5 |

## P0 — 정식 ADR과 문서 연결 등록

**Owner:** 플랫폼 문서 담당. **산출물:** 번호 있는 ADR·같은 상태의 Log 항목·계획 링크. 런타임 API 변경은 없다.

**Files:** 플랫폼 신규 `docs/adr/D-<선점번호>-application-action-boundary.md`, 수정 `docs/reference/ROSY ADR Log.md`, `docs/logs.md`; 이 계획의 Spec 링크. 생성 index는 생성기로만 갱신한다.

- [x] 슬롯 운영 규칙으로 작업 슬롯을 확보한다. main의 `git status --short --branch`, `git worktree list`, `python tools/worktrees.py status`로 점유와 동료 변경을 확인한다.
- [x] `python tools/worktrees.py new app-action-boundary docs/application-action-boundary`로 생성하고 등록된 non-main 브랜치인지 확인한다. 일회성 예외가 있으면 사유·회수 조건을 인계에 남긴다.
- [x] worktree의 `README.md` 핵심 계약, `docs/AGENTS.md`, `docs/adr/AGENTS.md`, `docs/progress.md`, `docs/index.md`를 읽는다. D-827~829·D-836·D-841 및 병행 작업의 최신 상태를 다시 확인한다.
- [x] `tools/harness/adr_reserve.py`를 읽고 작성 직전 `python tools/harness/adr_reserve.py next "업무 공정 해석과 로봇 동작 실행의 분리"`를 실행한다.
- [x] D-856을 정식 ADR로 기록한다. 제목을 선점 번호 형식으로 바꾸고 구조 경계의 사용자 결정과 상세 wire 미확정을 구분한다. 현재 링크는 소유 저장소의 상대 경로로 바꾼다. Log 상태도 일치시킨다.
- [x] `docs/logs.md`에 이번 문서 등록과 미실행 검사를 남긴다. `python tools/harness/rosy_harness.py generate`, `python tools/harness/rosy_harness.py lint`를 실행한다. 새 ADR과 Log 항목의 쌍·번호 충돌·링크를 확인한다.
- [x] 자신의 경로만 커밋하고 공식 원격 runner로 `test/test_harness_contracts.py`를 검증한다. 실제 경로가 변경되면 `rg --files test`로 현행 시험을 먼저 확인한다. 생성 문서 변경이 있으면 그 변경도 같은 검증 SHA에 포함한다.

**Exit:** ADR·Log·계획 링크가 정본을 가리키고 lint와 해당 문서 계약 검사의 결과·SHA가 있다. Git 밖 초안과 계획은 이 정본으로 가는 안내로 바꾼다.

## P1 — 첫 동작의 상세 계약 확정

**Owner:** 플랫폼 계약 담당 + Harbor 소비자 담당. **산출물:** 실행 가능한 최소 동작의 상세 설계와 양 끝 fixture, 이후 단계의 정확한 path/schema/함수·시험 목록.

**Read/trace:** 플랫폼 `operations/fleet/fleet/server/cell/cell_app_routes.py`, `cell/cell_compiler.py`, `step_action_kinds.py`, `operations/site_execution/src/rosy/execution/`, `contracts/foundation/core_common/protocol/`, `contracts/motion/`, OMX `action_api.py`·`action_runner.py`·`pose_plan.py` 및 각 모듈 AGENTS. Harbor `process.py`, `rosy_http.py`, `workflow.py`.

- [ ] 첫 대상은 기존 simulation에서 검증되는 단일 물체 이동 흐름으로 제한한다. 등록된 Action·공개 입력·장치 소비자의 필수값을 끝까지 추적한다. 중립 입력만으로 기존 물리 검증을 구성할 수 있는지 확인하고, 부족하면 해당 검증 소유자부터 설계한다.
- [ ] 현재 `CELL_TRANSFER`의 `item`·`pallet`·`layer`·선택 `sku`·recipe/cell/process digest를 소비자별로 분류한다. 업무 의미, 불투명 추적값, 물리 안전 입력을 구별한다. 필드를 지우는 것 자체를 완료 기준으로 삼지 않는다.
- [ ] 요청/조회/취소의 기존 공개 surface 중 재사용 가능한 것을 정한다. 부족하면 typed 동작 계약의 최소 확장을 설계한다. 임의 실행 endpoint나 공정 JSON 전체를 실행기에 넘기는 우회는 채택하지 않는다.
- [ ] 논리 동작 identity·요청 key scope·본문 결속·동일 요청 재조회·권한·수명·보존기간·실패코드·취소/불명 결과를 표와 정상/거절 fixture로 확정한다. 앱 ID는 클라이언트 임의 문자열로 권한을 얻는 값이 아니라 인증 principal에 결속한다.
- [ ] 동작 성공 조건과 측정/근거 참조, Harbor가 추가로 확인할 업무 조건을 대응시킨다. 현재 `GOAL_CONFIRMED` 의존을 무엇으로 대체/유지할지 명시하고, 물리 검증과 완료 gate를 약화시키지 않는 시험을 정한다.
- [ ] 상세 설계를 플랫폼 `docs/plans/2026-10-24-application-action-contract-design.md`에 작성한다. 새 API가 필요하면 적용 시점에 API 버전을 선점하고 API reference·schema·공급자/소비자 시험을 같은 계약 변경으로 묶도록 명시한다.
- [ ] P2–P5를 상세 설계의 실제 함수 signature·route·schema·fixture·회귀 시험명으로 보완하고 계약 검토를 받는다. 공정별 검증을 없애야만 동작하는 안이면 P2로 진행하지 않고 검증 소유를 다시 설계한다.

**Exit:** 외부 소비자와 장치 실행부가 같은 의미의 요청/결과를 설명할 수 있고, 안전 보장 이동표와 양 끝 예제가 있다. 미지원 동작·설정은 접수 전에 거절된다. 이 단계가 끝나기 전 이후 단계는 착수하지 않는다.

## P2 — 계약과 실행 식별·권한·복구 구현

**Owner:** 플랫폼 계약/Fleet 담당. **Files:** P1이 확정한 protocol schema·API reference·typed route와 기존 실행 원장. 시험 후보는 `operations/fleet/test/`의 새 경계 계약 suite 및 기존 `test_cell_job_api.py`, `test_trip_candidates.py`다. 기존 시험을 수정해 새 기대값에 억지로 맞추지 않는다.

**Interfaces:** P1 fixture의 요청과 결과를 공개 HTTP로 소비한다. Harbor·다른 최소 소비자는 플랫폼 import 없이 같은 payload로 동작한다.

- [ ] 정상 요청·동일 principal/key/body·다른 본문·다른 앱 scope·권한 부족·누락/미지원 종류·응답 유실·재시작의 RED 시험을 작성하고 커밋된 SHA를 원격 runner로 확인한다.
- [ ] 기존 proposal/admission/claim/원장의 검증·식별 로직을 재사용해 최소 확장을 구현한다. 별도 동작 원장·전역 lock 서버를 만들지 않는다.
- [ ] P1이 정한 request-key 조회와 불명 접수 대조를 구현한다. key 재사용으로 새 실행을 만들지 않고 권한 밖 조회를 차단한다.
- [ ] 관련 suite를 원격 runner에서 GREEN으로 확인하고 `test/known_failures.py`로 결과를 대조한다. 불명 결과에서 자동 재전송이 없는지 확인한다.
- [ ] 계약·fixture·검증 SHA를 함께 기록하고 기존 사용자 권한 범위에 따라 검토/착지한다. 다음 단계가 미착지 계약을 운영 기능으로 사용하지 않게 한다.

**Exit:** 구현이 P1의 요청·권한·복구 fixture를 충족하며 기존 cell/trip 접수 의미가 보존된다. 아직 물리 장치 실행을 개방하지 않는다.

## P3 — 공정 지식 없는 실행 조립

**Owner:** 플랫폼 실행/Fleet·장치 owner 담당. **Files:** P1이 지정한 실행 adapter와 조립 지점, 기존 `step_action_kinds.py`, 필요 시 OMX의 grant/plan 검증. 회귀는 `test_cell_action_transport.py`, `test_cell_job_recovery.py`, `test_omx_action_api.py`, `test_omx_cell_transfer_runner.py` 및 해당 safety selector를 사용한다.

**Interfaces:** P2의 typed 요청을 기존 action/attempt·admission·owner 경로로 전달하고 P1의 동작 결과를 반환한다. 업무 공정 문서를 해석하지 않는다.

- [ ] palletizing 패키지가 없는 서버 구성으로 중립 동작의 기동·접수·실행 시험을 먼저 작성한다. 기존 Cell 앱 설정은 별도 구성으로 그대로 검증한다.
- [ ] 기존 공정 compiler를 호환 Cell 앱 조립에서만 사용하도록 경계를 분리한다. 공유 실행부의 업무별 분기와 필수 import를 제거하되 검증 책임을 P1 표대로 보존한다.
- [ ] 보정 불일치·도달 불가·영역 위반·동작 중 stop·claim 경합·늦은 attempt 결과를 주입한다. 장치 거절이 업무 앱 주장으로 무시되지 않는지 확인한다.
- [ ] 원격 회귀와 관련 safety 검토를 수행한다. safety-tagged 경로는 독립 검토와 실제 증거를 확보한 뒤 해당 절차로 기록한다.

**Exit:** 공통 실행은 앱/palletizing 없이 채택 동작을 처리하고 기존 공정 소비자·최종 writer·정지 동작이 유지된다. 새 실물 profile은 열지 않는다.

## P4 — Harbor 공정 변환과 업무 결과 소비

**Owner:** Harbor 담당. **Files:** `harborlogi/harbor/process.py`, `rosy_http.py`, `workflow.py`, `tests/test_execution.py`, `tests/test_http_execution.py`, `docs/platform-contract.md`, `docs/execution.md`, 필요 시 신규 내부 변환 모듈. 별도 서버·공유 SDK는 만들지 않는다.

**Interfaces:** P1–P3의 공개 동작 계약을 표준 라이브러리 HTTP adapter로 소비한다. 내부 업무 요청·관측 모델과 SQLite 업무 장부는 Harbor에 남는다.

- [ ] 회수 → 방해 화물 이동 → 목표 이동 → 복원 계획을 P1의 지원 동작으로 바꾸는 순수 변환 시험을 작성한다. 설치 binding·물리 검증 입력이 없거나 오래되면 요청하지 않는 RED를 확인한다.
- [ ] 공정 변환과 HTTP adapter만 최소 변경한다. 기존 업무 장부의 request/step/action/attempt 대응과 낙관적 버전 검사를 유지한다. 기존 업무 상태를 옮겨야 하면 호환 읽기·원본 보존 시험을 먼저 둔다.
- [ ] 동작 성공만 있는 경우, 관측 없음/오래됨/과거 attempt/다른 화물·목적지/퇴피 미확인/최종 하역 미확인에서 업무가 진행되지 않는 시험을 유지·추가한다.
- [ ] 응답 유실 뒤 HOLD와 P2의 조회 대조를 연결한다. 재시작 직후 fresh 대조 전 진행을 금지하고 늦은 응답의 이전 단계 덮어쓰기를 막는다.
- [ ] `python -m unittest discover -s tests -v`를 Harbor에서 실행한다. integration skip은 통과로 세지 않는다. 플랫폼 기준 SHA·API/fixture 버전·지원 동작을 소비 계약 문서에 기록한다.

**Exit:** 업무 정책은 Harbor만 바꿔 조정할 수 있고 플랫폼 내부 import·장치 직접 명령·업무 관측 위조가 없다. 새로운 runtime 동작 호출과 업무 완료가 분리된다.

## P5 — 양 끝 독립성·복구 검증과 호환 전환

**Owner:** 양쪽 담당의 통합 검증. **Files:** Harbor `tools/integration/real_fleet_http.py`, `tests/integration/test_real_fleet_http.py`, 양쪽 contract fixture/validation 기록. 기존 Vault 하네스의 test-only 의존성과 앱 runtime 독립성을 구분한다.

- [ ] 플랫폼·Harbor·하네스를 고정 전체 SHA/clean checkout으로 준비한다. 임시 자격·장부·simulation 서버로 정상 흐름과 중복·충돌·busy·권한·응답 유실·재시작·늦은 결과를 HTTP 경계에서 검증한다.
- [ ] Harbor 없는 공급자, palletizing 없는 중립 실행 구성, 플랫폼 Python 없는 Harbor 소비자, 같은 fixture를 쓰는 두 번째 최소 HTTP 소비자를 각각 실행한다. 두 번째 소비자는 시험용으로만 두고 새 제품 앱을 만들지 않는다.
- [ ] 동작 완료와 업무 완료를 따로 단언한다. 합성 관측을 실제 화물·퇴피·하역 수용으로 기록하지 않는다.
- [ ] 기존 Cell 경로 회귀와 배포 profile 불변을 확인한다. 실패 시 새 경로의 dispatch를 비활성화한다. managed journal이 생긴 profile은 권한 제한·장부·점유를 보존한 HOLD에서 복구하며 구버전 binary나 unmanaged profile로 제어권을 자동 복귀시키지 않는다. 기존 지원 버전 복귀는 그 버전이 해당 journal/권한을 보존하는 경우에만 허용한다. 장부 삭제·요청 key 초기화·자동 재접수는 복구 방법으로 사용하지 않는다.
- [ ] 양쪽 validation에 SHA·환경·명령·exit·skip·관측 출처·확인 한계를 기록한다. 앱 계약 정본은 플랫폼, Harbor 대응은 Harbor 문서에서 관리하고 내용을 복제하지 않는다.
- [ ] 기존 `CELL_TRANSFER` 폐기는 실제 소비자 목록이 0이고 새 검증 보장이 확인된 별도 변경에서만 다룬다. 실물은 장치 담당과 별도 수용 계획으로 진행한다.

**Exit:** ADR 수용 기준을 검증 ID와 연결하고 실패·미실행을 표시한다. HTTP/simulation 통과와 장치·현장 수용은 별도 상태로 남는다.

## 검증 명령과 인계

플랫폼 각 단계에서 소유 변경을 먼저 커밋하고 다음 공식 runner를 사용한다. `<이번 단계 시험 경로>`는 P1에서 고정한 실제 목록이며 임의의 전체 suite나 local pytest로 대체하지 않는다.

```text
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/harbor-action-boundary/<단계> -- <이번 단계 시험 경로>
python test/known_failures.py X:/DevTemp/harbor-action-boundary/<단계>/run-1.txt
```

이번 문서 작성의 CE 판정은 **해당 없음**이다. 운영 장애 해결이나 비자명한 검증된 복구를 수행하지 않았다. 구현 단계에서 장애·데이터 무결성·권한 경계 문제가 실제로 해결되면 workspace CE 게이트를 적용한다.

현재 다음 행동은 physical 생성/두 사람 승인·trusted 물리 종료 관측·atomic claim 해제를 연결한 뒤 Harbor의 공정 변환을 중립 API로 옮기는 것이다. 공통 원장 provenance, 설치된 owner 실행, 영속 managed 권한과 canonical owner/receipt 경계는 위 근거까지 구현했으며 [최신 검증과 FULL 진행 상태](../validation/harbor-managed-capability-2026-10-24/result.md)를 따른다. 기존 World ArmState의 정규화 관절값/unobserved 물체 상태는 퇴피·물체 배치 증거로 쓰지 않는다. 전체 D-856 목표는 계속 진행 중이다. 이 기록은 push·병합·배포·장치 실행 승인이 아니다.
