# 앱·웹 책임과 공유 통신·소스 배치 이전 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** D-425의 화면·API·상태·실행 소유권을 실제 호출과 설치 경계로 검증하고, 중복 통신을 추출한 뒤 앱별 소스를 목표 경로로 점진 이전한다.

**Architecture:** [D-425](../adr/D-425-app-surface-ownership-shared-boundaries-and-source-layout.md)를 따른다. 사람의 화면은 `ui`, 프로세스 조합은 `apps/site`·`apps/device`, 기능 규칙은 D-413의 `modules`·`integrations`에 둔다. 기존 서버·wire·ROS identity·최종 writer를 보존하며 한 소비자 묶음의 코드·설치·회귀를 함께 이전한다.

**Tech Stack:** 기존 JavaScript ES modules·Node test runner·Python/FastAPI·pytest·setuptools·ament/colcon·ROS 2 Jazzy·Android Kotlin/Gradle·Docker/Caddy. 새 프론트엔드 프레임워크나 서버는 도입하지 않는다.

---

**Status:** Tasks 0–1 SOURCE/LOCAL contract complete (2026-10-03); Tasks 2–13 NOT STARTED. 실행 브랜치 `refactor/ui-ownership`, 기준 `d10c77e89`. 아래 시험과 완료 조건은 실행 지침이며 통과 기록이 아니다. 계획 작성 기준은 local main `3bb18bd59`; 각 작업 시작 시 HEAD와 진행 중 브랜치를 다시 확인한다.

## 범위와 의존 작업

- [D-413 이전 계획](2026-10-02-platform-architecture-v02-migration.md)의 Cell/Skill/두 원장/설치 작업을 재사용한다. `apps/gateway`와 `apps/agent`는 이미 있는 조합이다. 이 계획에서 같은 Fleet 서버·Cell UI·Mission 원장·장치 Action 원장을 새로 만들지 않는다.
- [2026-09-30 역할·공유 연결 계획](2026-09-30-site-app-roles-and-shared-link-plan.md)은 당시 조사 기록이다. discovery parser·공유 fixture·Pilot 연결 처리 등 이미 구현된 항목은 Task 0에서 현재 증거를 연결하고 재구현하지 않는다.
- 호스트 관리 Host Agent, 센서 I/O, Games, 진단 화면, 시뮬레이터, MCU는 이번 이름 변경 대상이 아니다. 설치형 웹 셸·스토어 배포·새 origin·새 API 버전도 별도 범위다.
- CORE는 기존 한 프로세스의 ROS executor와 FastAPI를 유지한다. `core_api_web`은 API 라이브러리다. Vision은 관측 생산자이며 조종 API가 아니다. Fleet은 사이트 순서·원장·불명 결과를 소유하고 CORE가 최종 로봇 명령을 결정한다.
- Task 12는 D-413 앱 설치 계약과 관련 변경이 착지한 뒤 진행한다. Task 13은 기능 추출이 끝난 단위만 이전한다. 고정 셀 검증을 경로 변경 때문에 중단하거나 기존 진행 상태를 완료로 바꾸지 않는다.

## 역할별 수용 계약

| 화면/앱 | 화면 책임 | API/상태 소유자 | 금지하거나 이행 조건이 필요한 책임 |
|---|---|---|---|
| Robot | 단일 로봇 상태·진단·영구 설정 | CORE API와 기존 설정/상태 owner | 사이트 Mission 순서·별도 최종 command writer |
| Pilot | 현재 장치 세션의 조종·실습 입력 | CORE API, 장치가 승인한 capability/limits | 영구 설정 정본·탭 복귀/재연결 후 자동 조종 재개 |
| Console operate | 사이트 상태·운용·Mission·site stop | Fleet API/사이트 원장 | 로봇 DDS 직접 접근·UI 자체 작업 성공 판정 |
| Console install | 등록·카메라/좌표/사이트 설치 | 같은 Fleet API/인증 세션 | 별도 설치 서버·별도 원장·운용 화면에 영구 설치 편집 복제 |
| Cam | 휴대전화 캡처·전송·상태 | Vision ingest 계약, Fleet 등록 계약 | stop/drive 권한·관측을 명령으로 변환 |
| Face | LCD 표시 | 기존 표시 입력 생산자 | 조종/설정 정본 |
| Vision 서비스 | 영상 ingest·관측·preview | 기존 Vision 생산자와 lease 계약 | 움직임·Mission 실행 |

등록부의 `owns` 선언과 실제 API 호출·권한 거절·서버 쓰기 owner를 함께 확인한다. Pilot의 DEVICE 수용 전 Robot의 이행용 teleop은 D-370 조건으로 남긴다. SOURCE/LOCAL 시험으로 이 예외를 제거하지 않는다. 중복 허용인 긴급 정지는 서버 권한 검사를 유지한다.

## 단계·설치 전략

```text
0 기준선 → 1 소유권 검사 → 2 통신 도구 → 3 Fleet client → 4 CORE client
  → 5 화면 책임 정리 → 6 설치 계약 → 7 공유 UI → 8 Robot/Pilot
  → 9 Console → 10 Cam/Face → 11 브라우저·설치 종합 수용
  → 12 기존 실행 조합 이름 이전 → 13 준비된 backend 조합 이전·호환 정리
```

| 묶음 | 출구 | 허용하는 완료 주장 |
|---|---|---|
| 0–1 | 화면/API/정본/writer/설치/이행 예외가 현재 코드와 대응 | 책임 기준선 확보 |
| 2–5 | 같은 서비스의 클라이언트 공유, 자격 격리·취소·오류·재연결 검증 | SOURCE/LOCAL 책임 정리 |
| 6–10 | 앱마다 원본 1곳, 기존 설치 identity로 자산/코드 설치 | 해당 앱 SOURCE/LOCAL 이전 |
| 11 | 실제 렌더링 및 저장소 없는 설치 실행 | LOCAL 수용; 생성·검증한 artifact만 ARTIFACT |
| 12–13 | D-413 의존 출구 충족, 기존 프로세스/writer/최소 설치 보존 | 검증된 backend 단위만 이전 |

소스와 설치 위치를 구분한다. web UI의 기존 ament 패키지는 우선 `src/hmi`의 **설치 전용 wrapper**로 남기고 `ui`의 원본을 manifest대로 설치한다. package.xml/resource/ROS package명과 `share/web_common`, `share/dashboard`, `share/pilot` 경로는 보존한다. wrapper에는 자산 사본·업무 코드가 없어야 한다. wrapper 제거는 모든 colcon/release 소비자가 새 검색 경로를 사용한 뒤에만 한다.

Fleet 화면은 `ui/console`이 원본이고 wheel 안의 기존 `fleet/server/web`이 설치 위치다. setuptools의 build_py/sdist 단계에서 manifest로 자산을 수집한다. checkout wheel과 **sdist에서 다시 만든 wheel**을 모두 검사한다. sdist에는 수집한 자산을 담고, build 과정은 source tree에 파일을 생성하지 않는다. 새 UI wheel이나 소스 폴더 symlink에 의존하지 않는다.

Cam은 Gradle 앱 전체를 `ui/cam`으로 이동한다. Face는 Python/ament 패키지 전체를 `ui/face`로 이동하고 colcon 검색 경로에 명시한다. Face의 `emotion` import·entrypoint·ament identity는 보존한다. web wrapper와 Face의 설치 방법을 혼동하지 않는다.

## 공통 실행 규칙

구현할 때 @using-git-worktrees, @verification-before-completion과 [.claude/skills/rosy-land-on-main](../../.claude/skills/rosy-land-on-main/SKILL.md)을 적용한다. 브랜치는 `refactor/ui-ownership`, worktree는 저장소 `.worktrees/ui-ownership`을 권장한다. 다른 세션의 같은 경로 수정이 있으면 먼저 착지 여부를 확인한다. 작업마다 변경 파일만 명시적으로 stage/commit한다. 원격 push·배포는 이 계획의 자동 단계가 아니다.

임시 산출물은 `X:\DevTemp\rosy-ui-ownership`에만 둔다. Linux/WSL에서는 같은 X: 마운트를 확인해 `ROSY_SCRATCH`를 설정한다. CI의 runner 임시 디렉터리도 source checkout 밖에 둔다.

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:ROSY_SCRATCH = 'X:\DevTemp\rosy-ui-ownership'
New-Item -ItemType Directory -Force -Path $env:ROSY_SCRATCH | Out-Null
$env:TEMP = $env:ROSY_SCRATCH
$env:TMP = $env:ROSY_SCRATCH
```

아래 pytest 명령은 별도 실행한다. 각각 `-q -p no:cacheprovider --basetemp "$env:ROSY_SCRATCH/pt-task-N"`를 붙이고 실행 로그를 X:에 저장한다. 실패 시 `python -B -X utf8 test/known_failures.py "$env:ROSY_SCRATCH/task-N.txt"`로 기존 실패와 새 실패를 구별한다. Linux 명령에서는 PowerShell 환경 변수 표기만 해당 셸 표기로 바꾼다.

각 코드 task는 **실패 사례 작성 → 의도한 실패 확인 → 최소 변경 → 회귀 → 제한 커밋**으로 진행한다. 큰 task 안에서도 소비자 하나·설치 방식 하나씩 이 반복을 수행한다. 문서 task에는 구현을 그대로 따라 쓰는 새 테스트를 만들지 않는다. 모듈 logs/progress, harness path와 생성 index를 실제 증거에 맞춰 함께 갱신하며 DEVICE/FIELD는 자동 승격하지 않는다.

## Task 0: 현재 소유권·소비자·설치 기준선

**Reuse:** `STATUS.md`, D-425, D-413 계획, `src/hmi/web_common/surfaces.yaml`, `src/hmi/dashboard/panels.yaml`, `src/runtime/api_web/core_api_web/api/app.py`, `src/site/fleet/fleet/server/app.py`, `src/site/fleet/fleet/server/static_routes.py`, 각 대상 `progress.md`.

**Create:** `docs/validation/app-ownership-migration-2026-10-03/README.md`, `ownership.csv`, `migration.csv` (동일 디렉터리).

1. HEAD·dirty paths·worktree·진행 중 D-413 앱 조합 변경을 기록한다. `ownership.csv` 열은 `user_task,surface,api,credential_audience,state_owner,writer,session_scope,transition_gate,evidence`로 고정한다.
2. `migration.csv`에 `source,target,callers,build_entry,installed_path,public_identity,tests,rollback,status`를 채운다. 정적 파일·Python import·Gradle·CMake·Docker·release·CI·harness 참조를 `rg`로 확인한다.
3. CORE/Fleet 오류 형식, 각 client의 반환/throw, credential 저장·만료, WS close code, 타이머 cleanup과 PWA cache를 실제 코드에서 기록한다.
4. 별도로 `test/architecture/test_app_roles.py`, `src/hmi/web_common/test`, `src/hmi/dashboard/test`, `src/hmi/pilot/test`, `src/runtime/api_web/test`, `src/site/fleet/test`를 실행한다. ROS/브라우저/Android 때문에 실행 못 한 항목은 환경과 이유를 기록한다.
5. 기존 Sep30 계획에서 구현된 항목과 남은 항목을 대응시키고 baseline을 커밋한다: `docs: capture app ownership and installation baseline`.

**출구:** 실제 호출·빌드 경로에 근거한 표, 기존 실패 목록, D-413 작업 충돌/의존 목록. 아직 이동하지 않는다.

**완료 증거 (2026-10-03):** [소유권·설치 기준선](../validation/app-ownership-migration-2026-10-03/README.md), ownership.csv·migration.csv 각 12개 행. 역할/shared/Robot/Pilot/API/Fleet 별도 실행 합계 1939 passed/139 skipped, 모든 known-failure 비교 0 new/0 known. 기존 web-transport worktree의 충돌과 다른 세션 변경은 보존했다. skip·브라우저·설치·DEVICE/FIELD는 미수용이며 다음 단계에서 별도 검증한다.

## Task 1: 선언과 실제 동작을 연결하는 소유권 검사

**Modify:** `src/hmi/web_common/surfaces.yaml`, `test/architecture/test_app_roles.py`, `src/hmi/web_common/test/test_surface_registry.py`, `src/runtime/api_web/test/test_surface_manifest_api.py`, `src/site/fleet/test/web/authorization.test.mjs`.

**Create:** `test/test_app_ownership_contracts.py`.

1. viewer/operator/admin·Cam ingest 자격을 주입해 금지된 설정/조종/stop API가 서버에서 거절되는 시험을 먼저 추가한다. UI에서 버튼이 숨겨졌다는 검사만으로 끝내지 않는다.
2. Console 운용/설치와 Robot/Pilot의 대표 요청을 실제 adapter 또는 기존 브라우저 fake server에 기록하고, Task 0 표의 API owner와 대조한다. 대표 쓰기 API마다 한 권한 거절과 한 승인 사례를 둔다.
3. 선언은 변경됐는데 금지된 실제 호출이 남는 변이를 주입해 검사 실패를 확인한다. Cam이 stop 자격을 소비하거나 공통 library가 domain endpoint를 직접 선택하는 경우도 거절한다.
4. 필요한 등록부/검사만 갱신한다. Pilot 이행 예외에는 DEVICE 증거의 식별자가 필요하며 아직 없는 증거를 만들지 않는다.
5. 위 다섯 기존 시험과 새 시험을 실행하고 커밋한다: `test: enforce app ownership at API boundaries`.

**출구:** 선언·실제 요청·API 권한 거절이 함께 검증되고 UI 검사 자체가 실행 권한으로 취급되지 않음.

**완료 증거 (2026-10-03):** [Task 1 계약·변이 증명](../validation/app-ownership-migration-2026-10-03/task1-ownership-contracts.md). api_owners 6개 명시, 실제 CORE/Fleet 인증·권한·설정/정지 owner 거절/승인 및 기존 JS caller를 Node로 검증. 책임 suite 33 passed, 기존 Fleet authorization Node 3 passed. owner 선언·CORE/Fleet 권한 guard·공통 literal dispatch의 변이 4개가 예상대로 실패했고 원본 bytes를 복원했다. 원격/DEVICE gate와 Pilot 이행 예외는 그대로다.

## Task 2: 공통 HTTP·화면 scope 도구

**Create:** `src/hmi/web_common/request.js`, `scope.js`, `test/transport/request.test.mjs`, `test/transport/scope.test.mjs`, `test/test_transport.py`.

**Modify:** `src/hmi/web_common/shared-assets.json`, `src/hmi/web_common/CMakeLists.txt`, `src/hmi/web_common/test/test_asset_manifest.py`.

1. 두 credential 공급자·두 origin·동시 요청·timeout·abort·비 JSON 응답·204·늦은 응답을 시험한다. 아래 완전한 예시는 새 request 계약의 최소 수용 사례다.

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequest} from '../../request.js';

test('credential scopes stay separate and writes are sent once', async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push([String(url), new Headers(options.headers).get('Authorization')]);
    return new Response(JSON.stringify({detail: 'unavailable'}), {
      status: 503, headers: {'Content-Type': 'application/json'},
    });
  };
  const core = createRequest({origin: 'https://robot.test',
    credential: () => 'core-token', fetchImpl});
  const fleet = createRequest({origin: 'https://fleet.test',
    credential: () => 'fleet-token', fetchImpl});
  const [a, b] = await Promise.all([
    core('/api/v1/teleop', {method: 'POST', body: '{}'}),
    fleet('/api/state'),
  ]);
  assert.equal(a.status, 503);
  assert.equal(b.ok, false);
  assert.equal(calls.length, 2);
  assert.deepEqual(calls.map(row => row[1]), ['Bearer core-token', 'Bearer fleet-token']);
  await assert.rejects(core('https://fleet.test/api/state'), /origin/);
  assert.equal(calls.length, 2);
});
```

2. `node --test src/hmi/web_common/test/transport/request.test.mjs src/hmi/web_common/test/transport/scope.test.mjs`로 아직 없는 모듈/계약의 실패를 확인한다. 시험 데이터는 fake이며 실제 자격을 출력하지 않는다.
3. `createRequest({origin,credential,fetchImpl})`는 요청 시 credential을 받고 `{status,ok,body}`를 반환한다. HTTP 오류 해석은 서비스 adapter가 맡고 network/abort는 명확히 전달한다. token 저장·endpoint 목록·재시도·freshness threshold는 넣지 않는다. 다른 origin 요청은 credential을 붙이기 전에 거절한다.
4. `createScope()`는 AbortSignal과 현재 generation 검사를 제공한다. dispose 시 timer/subscription cleanup·늦은 응답 무시를 보장한다. scope가 끝나면 어떤 handler도 새 요청을 발행하지 않는다. 기존 polling interval/stop policy는 바꾸지 않는다.
5. Node 시험과 pytest wrapper/asset manifest 시험을 실행한다. manifest와 CMake allowlist에 새 자산을 함께 넣고 커밋한다: `refactor: add scoped HTTP transport primitives`.

**출구:** 두 실제 클라이언트가 사용할 최소 통신 도구, 자동 명령 재전송 없음, 설치 자산 누락 없음. WS 공통화는 Task 4의 두 소비자 검증 뒤에만 한다.

## Task 3: Console 운용·설치의 Fleet client 공유

**Create:** `src/hmi/web_common/fleet-client.js`, `src/site/fleet/test/web/fleet-client.test.mjs`.

**Modify:** `src/site/fleet/fleet/server/web/console.js`, `install.js` (동일 디렉터리), 공유 자산 manifest/CMake, `src/site/fleet/test/web/authorization.test.mjs`, `poll-gate.test.mjs`.

1. 기존 `call()`의 성공 body·`detail` 오류·401 잠금·404 optional poll gate를 red 시험으로 고정한다. Console 두 문서에서 로그인을 바꾸거나 만료시키고 같은 origin에서만 session이 이어지는지 검증한다.
2. Fleet adapter는 Task 2 request를 사용하고 기존 throw/오류 코드 의미를 유지한다. storage key `rosy-console-token`과 잠금 UI는 Console 소유다. adapter에는 DOM·CORE credential·Mission 성공 판정을 넣지 않는다.
3. 운용 문서의 첫 실제 요청을 전환해 회귀를 실행한 뒤 설치 문서를 전환한다. 탭/문서 해제 뒤 polling·늦은 repaint가 없는지 확인한다.
4. `node --test src/site/fleet/test/web/fleet-client.test.mjs src/site/fleet/test/web/authorization.test.mjs src/site/fleet/test/web/poll-gate.test.mjs`와 Fleet static 관련 시험을 실행한다.
5. 커밋: `refactor: share Fleet client across Console documents`.

**출구:** 두 Console 문서가 같은 계약 adapter를 사용하고 기존 인증·오류·선택 기능 의미를 유지함.

## Task 4: Robot·Pilot의 CORE client와 연결 수명주기

**Create:** `src/hmi/web_common/core-client.js`, `src/hmi/web_common/test/transport/core-client.test.mjs`.

**Modify:** `src/hmi/dashboard/client.js`, `src/hmi/pilot/client.js`, `src/hmi/pilot/link.js`, 공유 자산 manifest/CMake, `src/hmi/pilot/test/test_link.py`, `src/runtime/api_web/test/test_pilot_route.py`.

1. Robot과 Pilot의 서로 다른 성공/오류 반환 형태, pairing/session 만료·remember 선택, close 4401/4403, 기존 timeout을 시험한다. 400ms 조종 timeout/CORE watchdog 관계를 보존한다.
2. 공통 CORE adapter가 `error.code/message/detail`을 읽되 기존 두 client façade가 각각 호출자 반환 의미를 유지한다. pairing/storage/만료는 각 session owner가 제공한다. Robot/Fleet credential을 Pilot 전역 store로 합치지 않는다.
3. Robot을 먼저 전환·회귀하고 Pilot을 전환·회귀한다. Pilot `DeviceSession`은 hold-to-drive·hidden·conflict·재개 규칙을 계속 소유한다.
4. Robot state socket과 Pilot link에서 실제로 같은 취소/backoff 원리가 필요한 경우에만 `src/hmi/web_common/socket-lifecycle.js`와 `test/transport/socket-lifecycle.test.mjs`를 추가한다. close-code별 조치·재인증·motion는 콜백 owner 정책이다. 두 소비자를 함께 전환하며 manifest/CMake도 갱신한다.
5. `node --test src/hmi/web_common/test/transport/core-client.test.mjs`, Pilot link/browser·CORE pilot/UI route 시험을 실행한다. disconnect→reconnect→held input을 주입해 새 명시 입력 전 조종 POST가 0건임을 확인하고 커밋한다: `refactor: share CORE client without sharing drive policy`.

**출구:** 서비스별 adapter 공유와 caller 호환, 자격 격리, 재연결 후 자동 명령/자동 조종 재개 없음.

## Task 5: 화면 책임과 이동 링크 정리

**Modify:** `src/hmi/dashboard/panels.yaml`, `src/hmi/dashboard/panels`, `src/hmi/pilot/screens`, `src/site/fleet/fleet/server/web/index.html`, `install.html` (동일 디렉터리), `src/hmi/web_common/surfaces.yaml`.

**Test:** `test/test_app_ownership_contracts.py`, `src/hmi/dashboard/test/test_surface_home_link.py`, `src/hmi/pilot/test/test_calibration_view.py`, `test/test_web_visible_roles.py`, 기존 Pilot/Robot browser 시험.

1. Task 0 표에서 중복 편집 흐름을 골라 영구 설정은 Robot, 세션 입력은 Pilot, 사이트 설치는 Console install로 연결하는 red browser 사례를 만든다. placeholder 탭·새 가상 Cell 화면은 만들지 않는다.
2. 기존 route와 권한으로 링크·진입 설명을 정리하고 필요 없는 편집 복제만 제거한다. 설정 저장이 필요한 Pilot 흐름은 Robot 설정으로 안내한다. 읽기와 일시 입력까지 일괄 금지하지 않는다.
3. Robot teleop 제거는 Pilot DEVICE gate가 충족된 경우에만 별도 커밋한다. 미충족이면 예외·추후 검사 위치를 기록하고 유지한다.
4. viewer/operator/admin에서 허용·거절·빈 capability·연결 단절 상태와 긴급 정지 도달성을 렌더링으로 확인한다. UI 권한 조작을 주입해도 서버가 거절해야 한다.
5. 위 pytest/browser suite를 실행하고 커밋한다: `refactor: align app workflows with state owners`.

**출구:** 사용자가 어느 화면에서 작업/설정을 해야 하는지 알 수 있고 이행 예외의 제거 조건이 남아 있음.

## Task 6: 이동 전에 설치·정적 서빙 계약 고정

**Create:** `test/test_ui_installed_assets.py`, `tools/ui/check_installed_assets.py`, `ui/assets.schema.json`.

**Modify:** `src/runtime/api_web/test/test_ui_manifest.py`, `test_ui_route.py`, `test_pilot_route.py` (동일 디렉터리), `src/site/fleet/test/test_package.py`, `src/site/fleet/setup.py`, `src/site/fleet/fleet/server/static_routes.py`.

1. shared manifest, Robot/Pilot entry asset 목록, Fleet HTML의 import graph를 읽고 manifest 자산 제거·미허용 파일·traversal·없는 JS를 주입한다. 각각 누락 실패/404여야 한다. 명시된 자산만 설치하는 계약을 고정한다.
2. 검사기는 설치 root를 인자로 받고 entry HTML/ES import/CSS url/manifest/icon까지 재귀 확인한다. repo fallback을 금지한 모드에서 CORE/Fleet test server의 실제 HTTP로 확인한다. 외부 endpoint 응답은 fake지만 자산은 실제 설치 파일을 사용한다.
3. Fleet build_py/sdist 수집 hook을 private `src/site/fleet/build_assets.py`에 구현하고 checkout/내장 sdist 자산의 입력 선택을 명시한다. sdist staging 이름은 `ui_assets`, wheel 목적지는 기존 `fleet/server/web`이다. 빌드 outputs는 X: 지정 경로에 둔다.
4. 깨끗한 X: staging에 source를 준비하고 sdist→wheel→별도 venv 설치를 수행한다. repo를 PYTHONPATH/cwd에서 제외한 뒤 static 서버와 검사기를 실행한다. 빌드 중 source tree가 변하지 않았는지 `git status --short`로 확인한다.
5. 위 installed/route/package 시험을 실행하고 커밋한다: `test: enforce repository-free UI installation`.

**출구:** 현재 설치의 보장과 이후 이전의 red 시험이 있으며 source fallback이 누락을 감추지 않음. UI 원본은 아직 기존 경로다.

## Task 7: 공유 UI 원본을 ui/shared/web으로 이전

**Move:** `src/hmi/web_common`의 자산·라이브러리·등록부·시험·harness 기록 → `ui/shared/web`. **Keep:** 기존 `package.xml`, `CMakeLists.txt`는 설치 wrapper.

**Modify:** wrapper CMake, `src/runtime/api_web/core_api_web/api/app.py`, `src/site/fleet/fleet/cli.py`, `src/site/fleet/build_assets.py`, `deploy/site/Dockerfile.fleet`, `.github/workflows/android.yml`, `tools/harness/harness.yaml`, `test/architecture/test_target_layout.py`, `test_folder_layout.py`, `test_folder_package_names.py` (동일 디렉터리), 공유 자산을 읽는 기존 시험.

1. source fallback과 설치 share lookup을 별도 시험한다. 목표 경로의 JS/registry/아이콘을 삭제하면 검사기가 실패하도록 먼저 red를 확인한다.
2. `git mv`로 원본을 이동하고 CMake의 source root만 새 경로로 연결한다. 공유 자산 manifest가 원본/설치 목록의 단일 기준이다. 설치 전용 wrapper 예외는 정확한 경로·목적·제거 조건을 기록한다.
3. CORE fallback, Fleet 빌드/Docker, Android icon 참조, CI path filter, harness module path를 같은 변경에 연결한다. 도메인 규칙까지 `shared`에 이동하지 않는다.
4. `python -B -X utf8 -m pytest ui/shared/web/test test/test_ui_installed_assets.py test/architecture/test_app_roles.py`와 기존 API route 시험을 실행한다. Linux/Jazzy에서 외부 build/install/log 위치로 web_common을 non-symlink colcon install하고 share 자산을 검사한다.
5. 커밋: `refactor: move shared web sources with install compatibility`.

**출구:** 공유 원본 한 곳, ROS share identity 유지, source/installed 서빙 모두 통과.

## Task 8: Robot과 Pilot을 하나씩 이전

**Move:** `src/hmi/dashboard` 자산·시험·기록 → `ui/robot`, `src/hmi/pilot` 자산·시험·기록 → `ui/pilot`. **Keep:** 두 기존 ament package.xml/CMake 설치 wrapper.

**Modify:** wrapper CMake, CORE `app.py`·`ui_manifest.py`·`ui_registry.py`, `tools/sync_pilot_files.sh`, `tools/run_pilot_sim.sh`, `deploy/robot/omx/Dockerfile.pilot`, `.github/workflows/ci.yml`, `tools/harness/harness.yaml`, 기존 구조/route/browser 시험.

1. Robot의 `panels.yaml`/surface assembly와 Pilot manifest/sw/import/icon을 대상으로 누락된 installed asset의 red 시험을 확인한다.
2. Robot만 이동해 fallback·share/dashboard·`/dashboard`·`/console`·`/setup`·`/device`를 확인하고 커밋한다: `refactor: move Robot UI with existing routes`.
3. Pilot을 이동해 share/pilot·`/pilot`·scope/start_url·service-worker cache 갱신·driver/screen import를 확인한다. URL/public surface ID는 변경하지 않는다.
4. 각각 `ui/robot/test` 또는 `ui/pilot/test`, CORE UI/pilot route 시험, Task 6 설치 시험을 실행한다. colcon non-symlink install에서 wrapper→ui 연결도 확인한다. 이후 Pilot을 커밋한다: `refactor: move Pilot UI with PWA compatibility`.
5. Robot/공유 자산 버전 A와 Pilot 버전 B의 혼합은 배포 manifest가 막거나 호환돼야 한다. 이전 UI cache로 새 manifest를 연 경우 blank screen 없이 갱신/오류 안내가 나오는지 실제 브라우저로 확인한다.

**출구:** 두 UI 원본 이전, 기존 route/ament identity/PWA 경로 유지, 파일 복사로 설치 누락을 가리지 않음.

## Task 9: Console operate/install 원본 이전

**Create:** `ui/console/assets.json` (Task 6 schema 사용). **Move:** `src/site/fleet/fleet/server/web`의 HTML/CSS/JS·Node 메타데이터 → `ui/console`; 운용 문서는 `operate`, 설치 문서는 `install`, 둘이 실제 소비하는 모듈은 `shared` 하위에 둔다. 기존 Python `web/__init__.py`는 wheel 설치 package scaffold로 남기며 UI 자산 사본은 두지 않는다.

**Modify:** Fleet `build_assets.py`·`setup.py`·`fleet/server/static_routes.py`, `deploy/site/Dockerfile.fleet`, Fleet web 시험, harness/CI/구조 path, UI source 참조.

1. manifest의 `version`, `entrypoints`, `assets`를 정의하고 각 asset의 `source`, 기존 `installed_relative_path`, `media_type`을 기록한다. manifest 자체도 wheel에 설치해 runtime allowlist의 기준으로 사용한다. 두 entry HTML의 import/공통 자산 그래프를 검사하고 manifest 누락·서빙 allowlist 밖 경로로 red를 확인한다.
2. 파일을 이동하고 wheel 설치 목적지는 기존 Fleet web으로 유지한다. 브라우저 URL `/console`, `/console/install`, 자산 URL, CSP, same-origin session은 유지한다.
3. Fleet runtime은 설치된 자산을 우선 사용하고 개발 fallback만 `ui/console`을 찾는다. Docker는 동일 manifest를 사용해 설치/수집한 자산을 포함한다. source checkout 전체를 runtime dependency로 만들지 않는다.
4. Fleet Node web suite와 static/package 시험, sdist→wheel 설치 시험을 실행한다. Docker smoke에서 두 문서·공유 아이콘·client JS·없는 asset 404·traversal 거절을 확인한다.
5. 커밋: `refactor: separate Console sources from Fleet runtime package`.

**출구:** Console 원본/설치 대응이 명시되고 같은 Fleet 서버·같은 인증으로 두 문서가 동작함.

## Task 10: Cam과 Face의 독립 설치 이전

**Move:** `src/site/cam` → `ui/cam`, `src/hmi/face` → `ui/face` (별도 커밋). **Modify:** `.github/workflows/android.yml`, `.github/workflows/ci.yml`, deploy/release colcon 호출, `tools/harness/harness.yaml`, `test/architecture/test_app_identity.py`, 구조/토큰 parity 시험.

1. Cam Android applicationId·wire fixtures·아이콘 parity·Gradle working-directory/path filter를 red 시험으로 고정한다. X:의 staging에서 `gradlew.bat testDebugUnitTest assembleDebug --project-cache-dir "$env:ROSY_SCRATCH/gradle-cache" --gradle-user-home "$env:ROSY_SCRATCH/gradle-home"`를 실행한다. staging은 시험용이며 제품 원본은 `ui/cam`이다.
2. Cam을 이동·참조 갱신하고 단위시험/APK 구성 identity를 확인한다. APK 조립은 실제 설치/카메라 수용이 아니다. 커밋: `refactor: move Cam Android source under UI`.
3. Face의 기존 Python import/console scripts/resource/GIF 목록을 시험한다. 패키지를 이동한 뒤 `colcon --log-base "$ROSY_SCRATCH/colcon-log" build --base-paths src ui/face --build-base "$ROSY_SCRATCH/colcon-build" --install-base "$ROSY_SCRATCH/colcon-install" --packages-select emotion`를 Linux/Jazzy에서 실행한다.
4. 모든 현재 colcon discovery 및 release payload source 목록에 Face의 새 경로를 포함한다. `deploy/robot/pinky_pro/release/build_payload_release.py`, `arm64_release_builder.py`, `.github/workflows/ci.yml`과 실제 Task 0 caller 목록을 확인한다. wheel/ament 설치 root에서 import·entrypoint·GIF 조회를 검사한다. display는 fake로 분리한다.
5. 관련 역할/identity/parity/설치 시험 후 커밋: `refactor: move Face package with explicit build discovery`.

**출구:** 언어별 독립 빌드·기존 public identity 유지. Cam DEVICE 촬영/전송과 Face LCD DEVICE 표시는 별도 남은 gate다.

## Task 11: 이전된 UI의 브라우저·설치 종합 수용

**Create:** `docs/validation/app-ownership-migration-2026-10-03/browser-matrix.md`, `installation-matrix.md`. **Modify:** 기존 Robot/Pilot/Fleet browser 시험과 Task 6 설치 검사.

1. viewer/operator/admin 및 만료 credential로 Robot·Pilot·Console 두 문서를 실제 렌더링한다. 상태 loading/empty/error/retry와 서버 거절 메시지가 보여야 한다.
2. 느린 응답→화면 종료→응답 도착, WS 단절→재연결, 탭 hidden→visible, conflict를 주입한다. 종료 후 repaint/새 polling 없음, 새 입력 전 Pilot motion 없음, 기존 site stop 도달성을 확인한다.
3. 명령 수락 뒤 timeout/연결 단절은 성공으로 표시하지 않는다. 기존 결과 ID로 조회하며 Fleet UNKNOWN/HOLD와 완료 증거를 보존한다. 임의 자동 재발행 0건을 서버 요청 기록으로 확인한다.
4. CORE 최소 이미지/ament 설치·Fleet sdist/wheel·site Docker·Cam APK·Face 설치 각각 commit/digest/manifest/검사 결과를 기록한다. 사이트 의존성이 로봇에, ROS/학습 의존성이 site static에 추가되지 않았는지 검사한다.
5. 아래 회귀와 harness를 실행한다. browser-matrix에는 테스트 환경·실패 주입·요청 횟수·스크린샷의 X: 위치를 적고 커밋한다: `test: accept migrated UI across browser and installation boundaries`.

```text
python -B -X utf8 -m pytest test/test_app_ownership_contracts.py test/test_ui_installed_assets.py test/architecture/test_app_roles.py test/architecture/test_app_identity.py
python -B -X utf8 -m pytest ui/shared/web/test ui/robot/test ui/pilot/test
python -B -X utf8 -m pytest src/runtime/api_web/test
python -B -X utf8 -m pytest src/site/fleet/test
python -B -X utf8 tools/harness/rosy_harness.py generate
python -B -X utf8 tools/harness/rosy_harness.py lint
git diff --check
```

**출구:** 실제 렌더링/실패 복구/설치가 함께 증명됨. 실행 못 한 platform을 통과로 표기하지 않는다.

## Task 12: 이미 존재하는 얇은 실행 조합의 경로 명확화

**Dependency:** D-413 Task 6의 관련 install/composition 시험이 착지했고 변경 담당과 겹치지 않음. **Move:** `apps/gateway` → `apps/site/fleet`, `apps/agent` → `apps/device/omx`.

**Modify:** 두 pyproject/package source·각 시험·`tools/harness/platform_dependencies.yaml`, `.github/workflows/ci.yml`, `deploy/site/Dockerfile.fleet`의 PYTHONPATH/COPY, D-413 계획의 현재 실행 경로 참조, 구조/harness/설치 검사. `rosy_gateway`·`rosy_agent` import 및 wheel/CLI identity는 보존한다.

1. 새 경로로 만든 wheel이 기존 CLI/import를 제공하고 기존 profile 선택만 조합하는 red 설치 시험을 추가한다. 구 경로가 PYTHONPATH에 남으면 시험은 실패해야 한다.
2. Fleet 조합을 먼저 이동하고 설치·fake lifespan·기존 route·프로파일 회귀를 실행한다. `rosy-site-gateway`는 여전히 같은 Fleet 동작을 조합한다. 커밋: `refactor: name site Fleet composition explicitly`.
3. OMX 시뮬 조합을 이동하고 같은 설치 검사를 실행한다. hardware dispatch가 기존처럼 닫혀 있고 ROS-free import를 유지해야 한다. 커밋: `refactor: name OMX device composition explicitly`.
4. CI의 명시적 wheel 설치 목록·Docker·profile caller를 같은 커밋에 맞춘다. 기존 D-413 Task 6/7 시험의 경로만 이전하며 검증 의미/미완료 gate를 보존한다.
5. 저장소 없는 venv에서 각 composition import/CLI/lifespan과 기존 최소 설치 검사를 실행하고 migration.csv를 갱신한다.

**출구:** gateway/agent의 모호한 source 이름이 실제 실행 대상 이름으로 바뀌고 새 프로세스/원장은 생기지 않음.

## Task 13: 준비된 CORE·Vision 조합과 호환 경로 정리

**Reuse:** `src/runtime/gateway/core/main.py`, `src/runtime/api_web/core_api_web/api/app.py`, 기존 DI/서비스·`src/site/vision/rosy_vision` 실행 코드, D-413 기능 경계/설치 시험.

**Create when ready:** `apps/device/pinky/pyproject.toml`, `apps/device/pinky/src/rosy_pinky/compose.py`, `apps/device/pinky/test/test_composition.py`; `apps/site/vision/pyproject.toml`, `apps/site/vision/src/rosy_site_vision/compose.py`, `apps/site/vision/test/test_composition.py`.

1. Task 0 표에서 `core.main`의 구성/lifespan 부분과 기능 규칙의 실제 owner/import를 분리한다. 아직 D-413 경계가 준비되지 않은 규칙은 기존 패키지에 두고 **BLOCKED BY 해당 작업/증거**로 표시한다. 폴더 전체 이전은 하지 않는다.
2. 준비된 Pinky 조합만 새 앱에서 기존 CORE 서비스·API factory·ROS bridge에 연결한다. 테스트는 ROS executor/uvicorn 각 1개, 최종 command publisher 기존 1개, 종료 순서/시작 실패 cleanup을 fake와 ROS-SIM에서 검증한다. 기존 `core` entrypoint는 얇은 compatibility delegation으로 유지한다.
3. Vision은 기존 ingest/관측 코드에 얇은 composition을 연결한다. 직접 stop/drive 의존성이 없어야 하며 ingest wire·preview lease·배포 포트는 유지한다. 아직 기능 owner 분리가 안 된 관측 규칙은 기존 생산자가 소유한다.
4. 각각 새 경로에서 wheel 설치/기존 CLI 실행·최소 의존성·Task 11 자산 검사·기존 API/vision 회귀를 수행하고 별도로 커밋한다: `refactor: compose Pinky runtime through device app`, `refactor: compose Vision through site app`. ROS/device 환경이 없으면 해당 검증 gate는 남긴다.
5. 마지막으로 구 source 경로·fallback·임시 facade caller를 `rg`와 설치 시험으로 확인한다. 이관된 caller와 설치 증거가 있는 호환층만 제거한다. 남는 ament 설치 wrapper와 미완료 기능 경로는 목적/owner/제거 조건을 기록한다. 커밋: `refactor: retire verified migration compatibility paths`.

**출구:** 이전 단위마다 실행·설치 검증이 있고 아직 준비되지 않은 backend와 DEVICE 이행 예외가 구체적으로 남아 있음. Task 13 일부를 완료했다고 전체 CORE 기능 이전이나 최종 플랫폼 DEVICE 수용을 선언하지 않는다.

## 롤백과 최종 완료 판정

각 Task 7–10/12–13은 자산·빌드·호출자 변경을 같은 제한 커밋에 담아 되돌릴 수 있게 한다. DB schema·wire·ROS identity를 바꾸지 않으므로 경로 이전 롤백에 데이터 변환을 요구하지 않는다. release 롤백은 기존 설치 계약으로 처리하며 실행 중인 motion를 재개하는 동작을 포함하지 않는다. 공유 자산과 각 UI의 manifest/version은 같은 배포 묶음으로 검증한다.

완료 기록에는 `task,commit,platform,command,result,evidence_tier,remaining_gate,rollback`을 남긴다. SOURCE/LOCAL, ROS-SIM, ARTIFACT, DEVICE, FIELD를 구분한다. 실제 사용되는 화면·클라이언트·설치 단위의 이전과 필요한 gate가 충족된 범위만 완료로 표시한다. Pilot teleop 이행과 실제 Cam/LCD/로봇 수용이 남으면 남은 항목으로 명시한다.
