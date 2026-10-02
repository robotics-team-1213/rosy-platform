# D-425 앱·웹 책임·설치 이전 기준선

작성일: 2026-10-03. 기준 commit: `d10c77e89`. 실행 브랜치: `refactor/ui-ownership`, 등록 worktree: `.worktrees/ui-ownership`. [실행 계획](../../plans/2026-10-03-app-ownership-shared-transport-and-layout-migration.md) Task 0의 증거다. 이 기록은 SOURCE/LOCAL 조사이며 설치·장치·현장 수용을 대신하지 않는다.

## 현재 책임과 설치

[ownership.csv](ownership.csv)는 실제 사용자 작업을 화면/API/자격 audience/정본/writer로 나눈다. [migration.csv](migration.csv)는 현재 원본·소비자·빌드·설치 identity와 목표 경로를 연결한다. 표의 target은 목표이며 해당 파일이 이미 이동했다는 뜻이 아니다.

- Robot·Pilot은 `core_api_web`의 in-process 정적 서빙을 사용한다. CORE API 라이브러리에는 독립 서버 entrypoint가 없다. `core/main.py`가 ROS와 API 수명주기를 조합하며 `core/bridge/ros_bridge.py`가 기존 Command Manager의 최종 명령을 ROS에 연결한다.
- Robot에는 `/dashboard`와 `panels.yaml`의 `/console`·`/setup`·`/device` 조립 경로가 있다. Fleet의 `/console`과 이름이 같지만 origin·API·정본은 다르다. 문자열 `/console`만으로 서버 owner를 추론하면 안 된다.
- Console 운용 문서는 `fleet/server/web/index.html`, 설치 문서는 `install.html`이다. 둘은 같은 Fleet 서버/CSP/sessionStorage key를 사용한다. Fleet 운용 원장과 장치 Action 원장은 별개다.
- CORE 역할은 viewer/operator/administrator이고 Fleet 사이트 principal은 viewer/operator/policy-admin/service다. 두 서비스의 역할 이름과 자격을 하나의 전역 계정/store로 합치지 않는다.
- Cam은 Android 입력 앱이며 Vision ingest와 Fleet pairing 계약을 소비한다. 영상은 Vision이 생산/서빙하고 Fleet은 관측과 lease를 제공한다. Face는 `emotion` Python/ament 표시 패키지이며 HTML 자산만 옮기는 방법을 적용할 수 없다.
- 현재 `ui` 루트는 colcon 자동 검색 대상이 아니다. 기존 CMake share 설치와 Fleet wheel package_data에 실제 UI가 포함된다. source fallback이 설치 누락을 숨기지 않도록 이후 Task 6에서 저장소 없는 시험을 먼저 추가한다.

## 통신·자격·수명주기 기준

| 소비자 | 현재 계약 | 이전 때 지킬 의미 |
|---|---|---|
| Robot `client.js` | CORE API 성공 body; CORE `error` 해석 및 throw; 세션과 운영 감사 책임 포함 | 저장/만료/감사 정책은 Robot에 남김 |
| Pilot `client.js` | JSON 요청은 `{status,ok,body}`; HTTP 오류를 반환; network/AbortError는 reject; blob은 별도 경로 | CORE adapter를 공유해도 caller 반환 의미 보존 |
| Console 두 `call()` | 성공 body; Fleet `detail.message/code`; 401에서 잠금 표시와 사용자 메시지 | 동일 Fleet adapter로 추출하고 잠금/DOM은 화면에 남김 |
| 공통 자산 | `shared-assets.json` allowlist와 CMake install 목록 | 새 JS는 두 목록에 함께 포함 |

Robot의 만료 없는 token은 sessionStorage에 두고, paired token만 명시적 remember 선택 및 최대 7일 조건으로 localStorage에 남긴다. Pilot은 `rosy.pilot.token`, Robot은 `rosy.dashboard.token`/`rosy.dashboard.paired`, Console 두 문서는 `rosy-console-token`을 사용한다. 공유하는 것은 코드이며 credential/store 인스턴스는 서비스와 origin별로 분리한다. 실제 자격이나 장치 주소는 이 기록에 포함하지 않는다.

Pilot `link.js`는 100ms 입력 주기, 400ms POST timeout, 1–30s backoff, close 4401의 whoami 재검사, 4403의 재시도 중단을 소유한다. `hidden`과 `conflict` 차단이 독립적이다. disconnect 시 zero 전송과 재연결 뒤 새 입력의 관계는 Task 4에서 별도 재생으로 검증한다. 기존 시험이 통과했다는 사실만으로 모든 재개 경우를 증명하지 않는다.

Console 두 문서는 현재 `setInterval`을 각각 등록한다. 운용은 상태·discovery·map·vision 등을, 설치는 discovery·vision 등을 주기적으로 읽는다. 새 scope 도구로 바꾸기 전에 dispose 이후의 요청과 늦은 repaint를 실패 주입으로 확인한다. 서버 freshness 판정이나 polling interval은 통신 추출 과정에서 재정의하지 않는다.

## 진행 중 작업과 과거 계획 대응

| 항목 | 현재 확인 | 이번 작업의 처리 |
|---|---|---|
| D-413 고정 셀 이전 | Tasks 0–3 SOURCE, 6 isolated install LOCAL; 4–5/7 진행, 8–9 미실행으로 기록됨 | 기존 조합/Skill/두 원장 재사용; UI/경로 이전으로 수용 gate를 올리지 않음 |
| `apps/gateway` | `rosy-app-gateway`, `rosy_gateway`, `rosy-site-gateway` 이미 존재 | Task 12는 composition 설치 계약이 준비된 뒤 경로만 먼저 명확화 |
| `apps/agent` | `rosy-app-agent`, `rosy_agent` OMX 시뮬 composition 존재 | 공통 agent를 새로 만들지 않고 OMX 조합을 재사용 |
| `refactor/web-transport` | main 미착지 commit `2d6e92462`/`211fb4071`; worktree에 다수 staged 변경과 Console merge conflict | worktree/충돌 보존. 과거 시험·원리 참고; branch 전체 병합하지 않음 |
| 과거 transport 구현 | 같은 모듈에서 CORE/Fleet 오류를 해석하고 성공 body/throw로 반환; 이전 manifest 이름 사용 | 현재 Pilot 반환 계약·새 request/scope 및 서비스별 adapter와 대조해서 필요한 부분만 재사용 |
| Sep30 S1 discovery | `core_common/protocol/discovery_txt.py`와 공통 fixture/소비자 존재 | 새 parser를 만들지 않음 |
| Sep30 이름/아이콘 | `surfaces.yaml`, shared icon manifest, Cam applicationId, Pilot manifest 존재 | 현재 identity 유지하고 이전 caller/parity 검사 |
| Sep30 pairing/failure/WS | 공통 protocol fixtures, Cam Gradle 입력, Pilot link 시험 존재 | fixture와 거절/복구 시험 재사용; 실제 새 실패 사례만 추가 |

main checkout은 시작 시 clean이었다. 다른 worktree의 dirty/staged/conflicted 파일을 수정·stash·reset하지 않았다. D-413의 남은 DEVICE/ROS-SIM gate는 이 계획의 의존 항목으로 유지한다.

## 기준선 시험

Windows 호스트 Python 3.14.5, pytest 8.4.2, Node v24.15.0. 각 suite는 중복 basename을 피하려고 별도로 실행했다. 모든 Python 실행에 `-B -X utf8`, pytest에 `-q -rfE -p no:cacheprovider --basetemp X:/DevTemp/rosy-ui-ownership/baseline/pt-<suite>`를 사용했다. bytecode/cache/TEMP/TMP와 실행 로그는 X:에 두었다.

| Suite | 결과 | 알려진 실패 비교 | 로그 |
|---|---|---|---|
| `test/architecture/test_app_roles.py` | 7 passed | 0 new / 0 known | `X:/DevTemp/rosy-ui-ownership/baseline/roles.txt` |
| `src/hmi/web_common/test` | 209 passed / 24 skipped | 0 new / 0 known | `X:/DevTemp/rosy-ui-ownership/baseline/shared.txt` |
| `src/hmi/dashboard/test` | 78 passed / 58 skipped | 0 new / 0 known | `X:/DevTemp/rosy-ui-ownership/baseline/robot.txt` |
| `src/hmi/pilot/test` | 58 passed / 37 skipped | 0 new / 0 known | `X:/DevTemp/rosy-ui-ownership/baseline/pilot.txt` |
| `src/runtime/api_web/test` | 73 passed / 13 skipped | 0 new / 0 known | `X:/DevTemp/rosy-ui-ownership/baseline/api.txt` |
| `src/site/fleet/test` | 1514 passed / 7 skipped | 0 new / 0 known | `X:/DevTemp/rosy-ui-ownership/baseline/fleet.txt` |

합계: **1939 passed / 139 skipped**, 모든 suite에서 새 실패 0건. skip 항목은 수용 증거에서 제외한다.

browser opt-in을 활성화하지 않았으므로 브라우저 시험의 skip은 미검증으로 취급한다. 필요한 ROS 의존성이 없어 발생한 skip도 마찬가지다. Task 11의 실제 렌더링, Linux/Jazzy non-symlink install, Android/LCD DEVICE, ARM64 artifact, FIELD는 미실행이다.

## 다음 출구

Task 1에서는 등록부의 소유 선언과 대표 API의 실제 허용/거절을 연결한다. Task 2에서는 명령 자동 재전송을 하지 않는 request와 화면 scope를 먼저 시험하고 Task 3/4에서 Fleet/CORE의 실제 소비자로 연결한다. 이후 이전은 해당 단위의 manifest·CI·harness·서빙·installed-only 검증과 함께 수행한다.
