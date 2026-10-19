# D-807 Account 서비스 구현·원격 검증

2026-10-19 기록. 작업 브랜치 `feat/account-service-completion`, 출발 main commit `48fdd711ae96cf394e1a43f264c35d84855cedff`. 최종 제품/시험 소스 `30acdffbfb`. [실행 계획](../../plans/2026-10-19-account-service-rollout.md), [D-807](../../adr/D-807-account-service-credential-ownership-and-acceptance.md), [설치 절차](../../../deploy/site/README.md)를 함께 본다. 이 기록은 source·명시한 원격 시험의 증거이며 CI·설치·운영 수용 판정이 아니다.

## 변경과 판정

기존 Fleet Authority·SQLite·AccountClient를 재사용했다. 일반 Access/Refresh·브라우저 세션·장치/기계/업무 자격의 책임과 기존 회수 계약을 D-807에 기록했다. 사용자 계획 승인으로 Accepted가 되었으며 운영 활성화를 뜻하지 않는다.

실제 Chromium 회귀에서 조회 전용 사용자는 Pilot 조종 차단 화면에 로그아웃 버튼이 없어 회수를 시작할 수 없었다. `41e03f029e`에서 기존 로그아웃 동작을 차단/준비 화면에 공유하고 중앙 사용자에게 무의미한 로컬 토큰 초기화를 숨겼다. 조작 gate는 유지했다. `b33b8d46e6`의 PWA 캐시 갱신으로 새 화면을 받게 했다.

공통 receiver 재생성 후 암호화된 회수 큐 복구, CORE 실제 HTTP 503/pending·쿠키 삭제·lifespan 재시도, 일반 세션 캐시가 유효해도 중앙 단절/회수 시 미디어 갱신 거부, 옛 family의 대기 회수가 새 로그인 family를 회수하지 않는 검사를 추가했다. 정상/실패 브라우저 로그아웃은 실제 버튼을 누른다. 공통/CORE 인증 제품 구현은 변경하지 않았다.

## 실행 증거

pytest 명령은 `python tools/remote/remote_pytest.py --sha <아래 SHA> --log-dir <외부 로그 디렉터리> -- <시험 경로> -q`다. 브라우저 묶음은 시험 경로 앞 `ROSY_RUN_BROWSER_TESTS=1`, native proxy 포함 묶음은 추가로 `ROSY_ANDROID_HOME=<기존 SDK 루트>`를 전달했다. 로그는 저장소 밖 `%TEMP%/rosy-account-rollout-20261019/<묶음>/run-1.txt`에 있다. 아래 성공 pytest 로그 각각을 `python test/known_failures.py <로그>`로 비교해 NEW 0을 확인했다. 서로 겹치는 시험이므로 수치를 합산하지 않는다.

| 묶음 | 커밋 | 호스트 역할 | 실제 결과 | 로그 SHA-256 |
|---|---|---|---|---|
| task1 | c22ee485ad | 모델 PC | 15 passed, 0 skipped | SHA-256 `511fb971caf59261241ec2a3919d9d10c7dcb9ec044ee07d50b2db465184f057` |
| task2-fixed | 41e03f029e | 모델 PC | 14 passed, 0 skipped | SHA-256 `3b5afd355f1ef5672b3888f295948ee5359e05ebeb52175a1c1ad764f9ada8f1` |
| task3-apps | 41e03f029e | 모델 PC | 170 passed, 0 skipped | SHA-256 `59068dfd0208c22b7c93baf69805c65192aea643da2844546e038d6a9fce5cd5` |
| final-runtime-online | ce2f94e833 | 모델 PC | 34 passed, 0 skipped | SHA-256 `257641c2246fba9de3639d5fc2560abd47e2f568eb9868ad9111f1495329130c` |
| final-security | d58258fee6 | 모델 PC | 35 passed, 0 skipped | SHA-256 `2de617cc7e72e752873e7dba940062c3bb98fa553927a8747ce2be1d5cead147` |
| task3-games-browser | d58258fee6 | 현장 시험 PC | 38 passed, 0 skipped | SHA-256 `8e0dd3e259f68c193f05e3e04acef6407a9ed36e5124438d9f9a04fbd0db33db` |
| final-source-launcher | 30acdffbfb | 모델 PC | 2 passed, 0 skipped | SHA-256 `99db33d5c94c6f7da021687c7391181685cc33299c5435b1c861e2db3be3ec87` |

시험 경로:

- task1: `contracts/foundation/test/test_account_client.py`.
- task2-fixed: `middleware/core/gateway/test/test_account_pipeline.py`, `test_media_grant_api.py`.
- task3-apps: `operations/fleet/test/`의 `test_account_authority.py`, `test_account_authority_routes.py`, `test_account_ledger.py`, `test_account_deployment.py`, `test_account_setup.py`, `test_account_admin_browser.py`, `test_fleet_account_browser.py`; `test/learning/perception/`의 `test_rosy_accounts.py`, `test_learning_accounts.py`, `test_learning_cycle_authority.py`, `test_review_bridge_authority.py`, `test_learning_accounts_browser.py`; `operations/apps/games/test/test_preview.py`; `middleware/core/gateway/test/test_account_sessions.py`; `contracts/foundation/test/test_account_access.py`.
- final-runtime-online: 공통 AccountClient·CORE pipeline/media·Pilot `test_shell_assets.py`, `test_pilot_app_proxy.py`. final-security는 같은 경로의 새 family 분리/실제 정상 로그아웃 버튼 검사를 포함한 재실행이다.
- task3-games-browser: `test/test_games_board_browser.py`.
- final-source-launcher: `test/test_android_ci_launcher.py`.

### 실패 이력과 native 빌드

최초 task2 브라우저는 로그아웃 버튼 부재로 실패했다. 수정 뒤 task2-fixed에서 통과했다. 최초 전체 Pilot pytest(`task3-pilot`, 41e03f029e)는 성공 결과 264개와 실패 1개, skip 0이었다. SDK 미전달로 Gradle proxy가 실패했으므로 전체 통과로 판정하지 않는다. 로그 SHA-256은 `fc58cc316bfea98be76b42d69a819751d2f4f1fcae9e1d001d0b555665a16cfb`다. launcher는 원격 runner가 허용하는 `ROSY_ANDROID_HOME`을 기존 SDK 환경으로 전달하고 강제 offline 실행을 제거했다. 선언된 고정 의존성만 받으며 새 의존성을 추가하지 않았다. 해당 실제 JVM→Chromium 경로는 final-runtime-online/final-security에서 통과했다.

native 전체 시험은 모델 PC에서 원격 전달된 SHA의 `git archive`를 저장소 밖 임시 폴더에 풀어 실행했다. 기존 Gradle wrapper, 기존 SDK, `testDebugUnitTest assembleDebug --max-workers=1 --no-daemon`, `systemd-run --user --scope`의 MemoryMax=6G/CPUQuota=200%, nice 15, timeout 600초를 사용했다.

| 앱 | SHA | 실제 결과 | 외부 원격 증거 폴더 이름 |
|---|---|---|---|
| Cam | d58258fee6 | JVM 440 tests, failures/errors/skipped 0, debug APK 1 | `rosy-native-d58258fee-PrJj0i`의 cam.log/XML/APK |
| Pilot 최초 | d58258fee6 | JVM 111 tests, failures 3, errors 0, skipped 1; APK 미생성 | 같은 폴더의 pilot.log/XML |
| Pilot 기준선 | 48fdd711ae | 선택한 동일 3개 시험 모두 실패, 같은 모델 PC·SDK | `rosy-native-baseline-48fdd711-QPdvil` |
| Pilot 수정 | 30acdffbfb | JVM 111 tests, failures/errors 0, skipped 1, debug APK 1 | `rosy-native-final-30acdffbfb-EIspRA` |

Pilot의 기존 mock은 identity 확인 뒤 추가된 `/pilot` CSP 요청의 응답을 준비/소비하지 않았다. 별도 `fix/pilot-native-fixtures`의 `b83c616cd7`에서 두 Kotlin 시험만 수정했고 작업 브랜치에 `30acdffbfb`로 반영했다. 실제 제품의 stop·세션 경로를 바꾸지 않았다. 두 로봇의 identity→CSP 순서와 bounded-zero 요청/자격 검사를 유지한다. 최종 pilot.log SHA-256: `2e925b37ff3d0c171ef1508038a9500603f26a34b7e508cff0c7f2dc482f2629`.

전체 Pilot Gradle의 skip 1개는 `ShellPageProbe.bundledPageThroughTheAppProxy`의 opt-in 조건이다. 이 경로는 별도의 pytest launcher+실제 Chromium에서 실행·통과했다. APK는 기본 debug 설정으로 만들었으며 운영 Account 설정/서명 포함 빌드나 실물 설치를 입증하지 않는다. Cam 소스는 이후 커밋에서 변경하지 않았다.

## 표면별 인수 상태

SOURCE는 기존 연결/이번 소스 조사 범위, REMOTE TEST는 위 시험 범위다. CI는 실행하지 않았다. 설치 이후 열의 미확인은 실제 설치 부재의 단정이 아니다.

| 표면 | SOURCE | REMOTE TEST | CI | INSTALLED | RUNTIME | USER ACCEPTANCE |
|---|---|---|---|---|---|---|
| console / Account | 기존 Authority 재사용 | task3-apps | 미실행 | 미확인 | 운영 미확인 | 미실행 |
| robot / Pilot web | 로그아웃 누락 수정 | task2-fixed, final-security | 미실행 | 미확인 | 운영 미확인 | 미실행 |
| pilot-shell | 기존 연결·시험 fixture 수정 | JVM·proxy/Chromium·APK | 미실행 | 실물 미확인 | 실물 미확인 | 미실행 |
| cam | 기존 연결 유지 | JVM·debug APK | 미실행 | 실물 미확인 | 실물 미확인 | 미실행 |
| pinky-review / Learning | 기존 연결 유지 | task3-apps의 명시한 시험 | 미실행 | 미확인 | 운영 미확인 | 미실행 |
| game-board | 기존 연결 유지 | task3-apps, games-browser | 미실행 | 미확인 | 운영 미확인 | 미실행 |
| 미디어 | strict-online 계약 유지 | CORE issue/validate/renew | 미실행 | 미확인 | 실제 연결 종료 미계측 | 미실행 |
| lane-live-view | 읽기 전용 표면 유지 | 이번 별도 실행 없음 | 미실행 | 미확인 | 미확인 | 해당 업무 확인 필요 |
| Face / web-common / control-diagnostic | LCD / 라이브러리 / PARKED 유지 | 새 로그인 앱으로 확대 안 함 | 미실행 | 미확인 | 미확인 | 각 표면 기존 범위 |

## 운영 입력과 남은 작업

사용자가 기존 private 설정 조회·사용을 승인했다. 파일명/존재/접근 가능 여부만 조사하고 비밀 원문은 출력하지 않았다. canonical private에서 Account 설정 후보를 찾지 못했다. 현장 기본 `/etc/rosy/account`는 접근 가능하지만 JSON 0개이며 기본 authority.json이 없다. 보호 site.env는 현재 SSH 계정으로 읽을 수 없고 비대화식 sudo도 거부됐다. 문서화된 loopback probe 연결 실패만으로 실제 서비스 중단을 판단하지 않는다. 실제 설정이 다른 위치에 있는지는 확인하지 못했다.

실제 설정 경로·승인된 HTTPS issuer·bootstrap 계정 입력을 요청한 상태다. 주소/계정/키를 임의로 정하지 않았다. 설정 생성·마이그레이션·운영 계정 변경·서비스 재시작·서명 배포·로봇 운동은 수행하지 않았다. 기존 비밀번호·프로필·회수 상태를 보존한다.

남은 관문은 보호 설정 readback 및 정확한 callback/resource/receiver 키 확인, 같은 시점 DB/키 백업, 운영 설정 포함 서명 native 빌드, 기존 배포 관문, 실제 사용자 로그인/동의/앱 복귀/권한 거부/업무 결과 재조회, 열린 WS/native/worker의 회수 계측, 실제 미디어 종료 계측, 격리 DB/키 복원 후 옛 자격 부활 방지 확인이다. Task 4–5와 지속 목표는 완료 처리하지 않는다. main 착지·push·전체 CI도 수행하지 않았다.

## 리뷰와 실행 판단

계약/운영 증거 토론 후 마지막 독립 계약 리뷰를 수행했다. base48f→ce2 범위와 d582→30acd 추가 범위에서 근거 있는 Critical/Important/Minor finding은 없었다. 리뷰어는 시험을 직접 실행하지 않았으며 source 판정만 했다. 이후 실제 정상 버튼 클릭·새 family 분리 시험과 native 최종 실행 증거를 위에 별도로 기록했다. 실물·TLS·키/DB 복구·여러 실제 사용자/owner 격리는 리뷰 통과로 대신하지 않는다.

- 저장소 scratch 금지에 따라 실행 ledger와 raw pytest 로그는 외부 TEMP에 보존했다. 영속 판정은 이 기록과 커밋이며 TEMP의 장기 보존은 보장하지 않는다.
- 미디어 회귀는 실제 Authority fixture를 공유하는 기존 pipeline 시험에 넣고 HTTPS browser 시험을 매개변수로 확장했다. 별도 인증 fixture/API를 만들지 않았다.
- 승인된 현재 세션 직접 구현과 마지막 독립 리뷰를 사용했다. 별도 기능별 구현 에이전트는 만들지 않았다.
- 기존 SDK가 있는 승인 모델 PC를 사용했다. SDK 설치·새 IdP·provisioning CLI·일반 비밀 저장소는 추가하지 않았다.
- 기존 native fixture 결함은 별도 주제 브랜치에서 재현/수정 후 반영했다. 공통 foundation 변경은 FULL 착지 관문을 면제하지 않는다. 실제 착지 전에 모듈별 분리와 최신 main 기준 검사가 남아 있다.
