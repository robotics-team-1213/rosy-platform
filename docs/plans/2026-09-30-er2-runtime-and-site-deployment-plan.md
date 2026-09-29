# ER 2 작업 경로와 OMX 현장 승격 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**상태:** 우선순위 실행 계획. 소스 통합은 시작했으며 실물 target, provider data path, ROS-SIM, signed artifact, DEVICE, FIELD는 별도 증거가 필요하다. 이 문서는 Gemini 호출이나 물리 동작을 승인하지 않는다.

**목표:** ER 2 또는 다른 승인 caller가 만든 `PICK_PLACE` 후보를 operator가 검토하고, Fleet이 Mission과 stop generation을 관리하며, OMX local owner가 ROS driver로 실행하고, 독립 관측으로 결과를 확인하는 경로를 만든다.

**구조:** ER 2는 후보 생성자다. Fleet은 인증, proposal, Mission, admission, 진행 원장을 소유한다. OMX local owner는 arm/gripper ROS action과 로컬 차단을 소유한다. ROS가 관절과 그리퍼를 제어한다. 모델 tool call은 ROS 명령이 아니다.

**기술:** Python 3.12, FastAPI, SQLite WAL + `synchronous=FULL`, Gemini Robotics ER 2 Interactions, Linux UDS, ROS 2 Jazzy, 승인된 OMX controller.

---

## 우선순위

| 순위 | 단계 | 완료 기준 | 현재 상태 |
|---|---|---|---|
| P0 | ADR·API 정합성 | Fleet REST, 모델 tool, Device Action, ROS 경계를 일치시킨다 | D-334 후속 note 보완 |
| P1 | Fleet CLI composition | 명시적 Mission API, named-user auth, 같은 SQLite 원장, dispatcher off | proposal 저장/조회 연결; resolver 없음 |
| P2 | 실물 target과 command owner | host, OMX, 카메라, gripper, ROS action, E-stop, 운영자를 확인한다 | HOLD: inventory 없음 |
| P3 | 목표·정지 evidence | 실제 producer와 trusted verifier/readback을 등록한다 | HOLD: producer 없음 |
| P4 | ROS-SIM | 재시작, 늦은 ACK, stale target, stop 경합 등 실패 주입 통과 | PARKED: target profile 필요 |
| P5 | ARTIFACT·운영 준비 | immutable build, 서명·키 enrollment, host/TLS, secret·rollback 확인 | HOLD: host/key/정책 미확정 |
| P6 | DEVICE | 감독된 장치 동작과 독립 physical E-stop 측정 통과 | HOLD: 미실시 |
| P7 | FIELD | 단일 workcell 제한 파일럿과 rollback 승인 | PARKED |

필수 전제가 HOLD면 다음 단계를 활성화하지 않는다. host test와 `/healthz`는 simulation, signed artifact, device, physical stop 또는 field acceptance 증거가 아니다.

## 현행 코드와 안전 경계

- API Reference v1.57과 `create_app`에는 proposal, operator admission, Mission snapshot, bounded cursor event API가 있다. `fleet console`은 기본적으로 Mission/Proposal store를 구성하지 않는다.
- D-334의 첫 implementation note는 Task 3 당시 기록이다. Task 8에서 cursor event가 추가됐으므로 후속 note를 덧붙인다. `get_mission_status` 모델 tool은 없다.
- `candidate_resolver`, trusted camera/object producer, arm/gripper readback producer와 등록된 goal verifier가 운영 composition에 없다. synthetic resolver는 연결하지 않는다.
- `--mission-api`는 named `--users-file`과 durable `--tasks-db`가 필요하다. proposal 저장/조회를 열고 ER 2/Mission dispatcher와 기존 자동 queued-task dispatcher는 끈다. 기존 인증된 Fleet 운영 명령 route는 계속 열려 있으므로 전역 read-only 모드는 아니다. resolver가 없으면 resolve는 `MISSION_RESOLVER_UNAVAILABLE` 503이다. admission, Device Action은 연결하지 않는다.
- Gemini 이미지/prompt 호출은 production app에 연결하지 않는다. data/비용/secret 정책과 승인된 live observation feed가 선행 조건이다. `store=false`는 전체 미보존 보증이 아니다.
- 실제 target 정보는 public repo에 기록하지 않는다. 승인된 비공개 `private/` inventory만 사용하고 미확인 값은 HOLD로 둔다.

## Task 0 — 문서와 계약 정합성

**대상:** D-326~D-336, `docs/adr/D-334-er2-tool-and-progress-read-boundary.md`, `docs/reference/ROSY API & Protocol Reference.md`, ER 2 계획·조사 문서.

1. ADR 상태와 구현 범위를 확인한다. 결정 변경은 새 ADR로 기록한다.
2. REST proposal/Mission API, 모델 callable `propose_pick_place`, 내부 Device Action/UDS를 caller·권한·효과별로 구분한다.
3. Fleet CLI가 progress cursor API를 실제 노출하는지와 모델 tool 목록을 구분한다.
4. software stop, ROS cancel, OMX latch, physical E-stop 증거를 분리한다.

**검증:** API version/route와 ADR ID 검색, harness lint, Fleet API/문서 계약 시험. wire schema가 바뀔 때만 API Reference·schema·producer/consumer 시험을 함께 바꾼다.

## Task 1 — fail-closed Fleet Mission API

**대상:** `src/site/fleet/fleet/cli.py`, `src/site/fleet/fleet/server/app.py`, `src/site/fleet/test/test_cli.py`, `src/site/fleet/test/test_mission_api.py`.

1. `--mission-api` opt-in을 추가한다. named-user auth와 durable `--tasks-db`가 없으면 시작을 거부한다.
2. Task, Mission, Proposal store는 같은 SQLite DB를 사용한다.
3. operator proposal 저장/readback을 검증한다. resolver가 없으면 resolve는 503 fail-closed다.
4. `mission_dispatcher`와 자동 queued-task dispatcher는 생성하지 않는다. proposal/read 처리에서 provider 요청이나 Mission UDS Action은 발생하지 않는다. 기존 인증된 Fleet 운영 명령은 유지되며, 이 플래그는 전역 read-only 모드가 아니다.
5. 기존 API schema를 재사용한다. 새 wire contract는 별도 검토 후 만든다.

**완료 기준:** actual CLI composition에서 인증된 proposal 저장/조회가 동작한다. resolver·별도 승인 없이는 resolve/admission/physical submit을 할 수 없다.

## Task 2 — 실물 target과 최종 command owner

**대상:** OMX adapter/profile, deploy service, `docs/validation/er2-omx-action-baseline-2026-09-29/README.md`, 비공개 `private/` inventory.

1. host, OMX revision/serial, vendor driver/firmware, OS/ROS, arm action, gripper/readback, camera/calibration, E-stop, 운영자를 확인한다.
2. arm/gripper 최종 command writer를 하나로 고정하고 중복 ROS publisher/action client를 확인한다.
3. Fleet과 OMX가 같은 Linux host인지 확인한다. UDS의 UID/GID, socket mode, systemd ordering/restart를 검증한다. 다른 host면 별도 ADR 전까지 HOLD다.
4. driver accept/cancel/timeout/restart readback을 확인한다. `FollowJointTrajectory`만으로 grasp capability를 가정하지 않는다.
5. 독립 hardware E-stop과 re-arm owner를 확인한다. software stop과 HTTP ACK는 대체물이 아니다.

**완료 기준:** 이름이 지정된 target과 final writer/interface가 확인된다. 나머지 profile은 disabled 상태다.

## Task 3 — 목표와 정지 evidence producer

**대상:** Fleet goal verifier, 승인된 camera/object producer, OMX arm/gripper readback adapter와 contract tests.

1. observation ID/digest, capture time, calibration/transform revision, object identity, action/attempt 관계를 검증한다.
2. post-action camera evidence가 목적지 점유를 확인하고 fresh `OPEN` gripper readback이 같은 attempt에 연결될 때만 goal을 성공 처리한다.
3. stale/future/missing/reordered observation, calibration 변경, stale gripper, process restart는 HOLD한다.
4. Mission, Action, goal, stop의 owner/readback 축을 보존하고 physical 상태가 불명확하면 `UNKNOWN`을 유지한다.

**완료 기준:** trusted verifier가 실제 producer provenance를 확인한다. producer/verifier가 없으면 성공 전이를 허용하지 않는다.

## Task 4 — ROS-SIM 실패와 복구

**대상:** ROS 2 Jazzy/Isaac Sim, OMX profile, Fleet dispatch/stop tests, 날짜별 `docs/validation/` 보고서.

- 정상 고정 workbench `PICK_PLACE`와 duplicate admission, stale/moved target, transform 오류, gripper unknown/drop, UDS/network loss, restart, late ACK, stop-generation 경합, ROS cancel nonterminal, unresolved journal을 시험한다.
- durable `SUBMITTING` 이후 uncertainty에서 재전송이 없고 re-arm 전 자동재개가 없어야 한다.
- ROS cancel ACK와 simulated standstill/E-stop는 별도 증거다. simulator 결과로 physical stop time을 주장하지 않는다.

**완료 기준:** 재현 명령, environment/config digest, 필수 시나리오 결과를 고정한다.

## Task 5 — signed artifact와 Site 운영 준비

**대상:** `deploy/`, Site/OMX package 정의, D-301, 비밀 없는 template, validation evidence.

- 승인 commit에서 Site image와 OMX native package를 빌드하고 digest, architecture, SBOM, config를 고정한다.
- offline Ed25519 서명과 verifier/public key를 candidate와 분리해 등록한다. Pinky key를 재사용하지 않는다.
- Site host, OS, TLS/CA, network, SQLite volume, backup/restore, clock/log, operator identity를 확인한다.
- Gemini 약관/비용/데이터 전송 승인 후 최소 권한 secret, rotation, timeout, call budget, log/retention을 검증한다. secret/image는 Git에 넣지 않는다.
- staging 설치·서명 검증·restore·rollback을 확인한다. 승인 host/key가 없으면 production HOLD다.

## Task 6 — 감독된 DEVICE acceptance

- 안전 owner가 사전에 정한 정지시간/오차 기준을 사용한다. 이 계획에서 수치를 임의 지정하지 않는다.
- identity, calibration, ROS action, gripper readback, UDS 권한, latch/re-arm을 확인한다.
- 단일 `PICK_PLACE`, software stop, ROS cancel, process/network loss, 독립 physical E-stop을 각각 입회 시험한다.
- action/attempt/ROS goal, observation digest, gripper/load readback, stop 원시 측정을 상관시킨다.

## Task 7 — 제한된 FIELD pilot

- 한 고정 workcell과 단일 `PICK_PLACE`, operator 승인만 허용한다. auto replan, streaming, multidevice, Pinky 이동은 비활성이다.
- 실패/불확실/센서 불일치에서 fail-closed, 수동 복구, 재시도 금지, rollback을 입회 확인한다.
- 범위 확대는 새 ADR과 새 evidence 전까지 비활성이다.

## 실행 기록 — 2026-09-30

- Task 0: 완료. D-334 후속 note가 Task 3 기록과 Task 8 cursor endpoint 사이의 시점을 설명한다.
- Task 1: 부분 완료. `--mission-api`는 named-user auth와 durable DB를 요구하고 CLI에서 proposal API를 구성한다. 저장/readback은 통과, resolver 부재는 503, Mission 및 자동 queued-task dispatcher는 미생성이다. 기존 Fleet 운영 명령 route는 계속 활성 상태다. Gemini 호출, Mission admission, ROS Action 연결은 미완료다.
- 검증: CLI RED 테스트가 `--mission-api` 미지원 및 기존 대기 작업 자동 발송 문제를 재현한 뒤 수정했다. Fleet 전체 702 passed, 5 skipped; 기본 계약 suite 95 passed; flake8 통과; harness lint 0 errors, 20 freshness warnings; `git diff --check` 통과.
- 다음 gate: target inventory 및 실제 observation/gripper producer가 없어 Task 2/3과 ROS-SIM은 HOLD/PARKED다. provider data/secret 정책과 target 확인 전 artifact activation, DEVICE, FIELD는 진행하지 않는다.
- safety outcome: 이 변경은 Gemini 이미지 요청이나 Mission-to-OMX Action을 발생시키지 않고 자동 dispatcher를 시작하지 않는다. 기존 Fleet 운영 명령은 여전히 CORE 명령을 실행할 수 있으므로 API 인증과 운영자 통제는 필요하다.
