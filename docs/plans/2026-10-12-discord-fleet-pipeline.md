# Discord 대화 요청과 Fleet 대응 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Discord 대화를 기명 작업 후보·위험 사건 대응으로 연결하고 기존 Fleet Console 규약과 결과 증거를 보존한다.
**Architecture:** Bot은 transport, Decision은 후보, Fleet은 원장·권한·기존 작업 제출을 소유한다. 일반 관리는 Console이며 위험 사건의 Discord 대응은 기존 인수·정지 경계 안에서 단계적으로 수용한다.
**Tech Stack:** 기존 Fleet FastAPI/SQLite/httpx와 설치 helper, 기존 Decision·execution; Discord 공식 Bot/Gateway 계약은 구현 직전 검증한다.

## 1. 현재 경로 점검·계약 확정

- Read: `fleet/server/{site_auth,mission_routes,intent_routes,work_routes}.py`, `fleet/incidents/{handoff,notifications}.py`, `fleet/stuck/{board,reports}.py`, Console incident/work UI.
- Deliver: D-669, 대응 설계와 이 계획, 비밀 없는 Discord 연결 receipt. 현재 없는 기능을 완료로 표시하지 않는다.
- 일반 Mission/Cell Job 승인 구분과 D-655/D-664 범위를 고정한다. Discord 위험 대응에 허용할 조회/인수/정지와 금지할 해제/rearm/이동을 API 계약으로 명시한다.

## 2. 기명 수신·요청 원장 SOURCE

- Proposed create after D-669 acceptance: `integrations/messaging/discord/`의 transport, `operations/fleet/fleet/server/channel_requests.py`의 기존 DB 요청 원장.
- Modify together: `tools/harness/platform_parts.yaml`, Fleet 설치 helper/metadata, 설치·source/native 검사. 새 holder 등록과 외부 API가 필요한 경우 API Reference와 `contracts/foundation/core_common/protocol` 계약을 함께 작성한다.
- Test first: 허용 채널/사용자만 intake, Bot/webhook/DM zero-intake, 동일 메시지 중복·수정 충돌·권한 철회·재시작·원장 실패. caller-supplied principal·공용 operator bearer·`site-console`·development fallback을 거절하고 Fleet이 transport identity로 기명 principal을 결정하는지 확인한다. 요청 수신은 장치 요청/승인/실행을 만들지 않는다.
- Commit RED first; remote `test/known_failures.py`로 NEW를 확인한 뒤 최소 구현·GREEN·커밋. 실제 token은 주입하지 않는다.

## 3. 후보·Console 연결

- Reuse: 기존 Decision 후보, Fleet ProposalStore/Mission/Task/Cell Job resolver·admit, `work_read.py`, `operations/ui/console` 실제 작업 화면.
- 후보 의미 검증: 요청자·원문 hash·대상·관측 revision·구조화 작업을 연결하고 모호한 입력은 질문/보류. 모델 문자열을 `/api/fleet/do`나 장치 endpoint로 직접 전달하지 않는다.
- Test: 일반 Mission의 다른 owner read/admit 거절, Cell Job의 다른 기명 approver 정상 경로와 동일 proposer 승인 거절, stale evidence·capability 변경·중복 승인·UNKNOWN 재시작, 한 작업씩 확인. 일반 Mission 계약을 임의로 독립 승인자로 변경하지 않는다.
- 실제 provider/FIELD HOLD가 해제되기 전 fake 후보로 source/설치만 검증한다.

## 4. 위험 사건 응답과 결과 reply

- Reuse: 사건 revision·기명 handoff·resolver fence, OPEN/CLOSED outbox, 기존 stop/cancel 경로, progress/goal evidence.
- Confirm contract before code: Discord로 어떤 인증된 인수/정지 요청을 받을지, 권한 철회·오래된 사건·기한·부분 실패의 결과. 새 장치 writer는 만들지 않는다.
- Test: 자기 reply 재수신 zero-action, 잘못된 사건·담당·revision·reply 목적지 거절, CURRENT/UNKNOWN/REJECTED 구분, 정상 비개입 zero-send, 자연 해소와 조치 성공 구분.
- 원래 message/thread에 결과를 한 번 연결하며 provider 수락과 장치 목표 증거를 별도로 표시한다. timeout/5xx는 맹목 재전송하지 않는다.

## 5. 실제 연동 수용

- 사용자 관리 계정에서 Bot application·token·명시 채널 권한과 기명 Fleet 사용자 연결을 준비한다. 관리자 전체 권한은 요구하지 않는다. webhook과 Bot은 서로 다른 자격이다.
- Fleet 실행 SHA·실제 HTTPS Console·명시 비공개 설정·기존 DB/인증의 readback을 확인한다. 준비된 config를 적용하기 전 실제 전송·작업 동작 범위를 기록한다.
- 실제 대화 1건 → 요청 원장 → 후보 → Console 로그인/확인 → Fleet readback → 결과 reply를 검증한다. 로봇이 오프라인이면 장치 실행/목표는 HOLD다.
- 별도 승인된 제한 장치 수용에서 CORE admission·stop generation·목표 증거·종료 reply까지 확인한다. Discord 수신만으로 현장 완료를 선언하지 않는다.

## 검증 명령과 커밋/착지

이 노트북에서 pytest를 실행하지 않는다. 각 committed HEAD를 `tools/remote/remote_pytest.py`로 보내고 원시 로그마다 `test/known_failures.py`를 실행한다. `test/test_harness_contracts.py`, `test/test_network_topology_contracts.py`, 관련 Fleet 승인/인수/알림·설치·구조 시험을 함께 사용한다. 새 계약의 정확한 suite는 각 task의 경로 확정 후 추가한다.

```powershell
python tools/remote/remote_pytest.py --log-dir <X-session>/logs/contracts -- test/test_harness_contracts.py test/test_network_topology_contracts.py -q
python test/known_failures.py <X-session>/logs/contracts/run-1.txt
python tools/harness/rosy_harness.py lint
python tools/land.py --tests auto
```

자기 경로만 커밋하고 사용자 승인 범위의 로컬 FF를 사용한다. push/배포/provider/장치 동작은 source 착지와 별도다. D-669가 Proposed인 동안 새 권한 경로를 구현·활성화하지 않는다.

## 2026-10-12 후속: D-671 제한 접수 source

D-671이 실행 권한 없는 접수·owner read만 source 수용했다. Task 2의 Fleet 접수 API/기명 mapping 검증/원장과 순수 Discord projection/signature holder, CLI opt-in 및 설치 closure를 구현했다. Task 3에서는 현재 Console 작업 화면에 자기 원문 조회만 연결했으며 후보/resolve/admit은 연결하지 않았다. Task 4와 Task 5 실제 대화 수신 수용은 미완료다. Gateway 실행기/token/runtime identity mapping은 다음 작업이다.

기명 계정·paired HTTPS Console의 실제 cookie 로그인을 별도로 확인했다. Bot 서버 멤버 등록 및 기존 승인 webhook 연결 메시지 수신도 확인했으며 Bot 수신과 동일시하지 않는다. 독립 리뷰와 원격 증거는 [후속 기록](../validation/discord-fleet-pipeline-2026-10-12/named-login-and-intake.md)에 남긴다.
