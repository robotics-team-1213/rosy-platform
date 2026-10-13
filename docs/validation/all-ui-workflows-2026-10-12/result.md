# 전체 활성 UI/UX 정보 배치·작업 흐름 검증

## 후속 통합·푸시·CI 상태

commit `e94a0ae515`의 최종 착지 gate는 적정 AI PC 22.7 cores/10.2 GB와 Model PC 23.8 cores/8.2 GB에서 5478 + 4631 = **10,109 passed**, 각 종료 0·NEW 0, Node **322 passed/0 failed**였다 (`logs/land-profile-preflight-green/uiux-header-all-surfaces/`). 해당 후보는 main에 반영됐다. canonical pre-push의 누적 영향 검사는 514 + 5601 + 5377 = **11,492 passed**, 각 종료 0·NEW 0이며 같은 commit을 푸시했다 (`logs/prepush-final/`).

Cam·Pilot Android CI [38179188636](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38179188636)은 성공했다. 주 CI [38179188613](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38179188613)은 누적 Fleet 안전 커밋 열 개의 검토 trailer 누락으로 scope에서 실패해 시험 job이 실행되지 않았다. [독립 소급 검토](../fleet-continuation-safety-review-2026-10-12/result.md)로 실제 diff와 필수 후속 수정을 검토했으며 기존 이력 기록 방식으로 보완한다. 실패한 SHA의 이미지 빌드는 취소했다. CI 통과·서명·설치·팀원 계정 발급은 아직 완료가 아니다.

재부팅 뒤 gate의 부분 실행, main 이동으로 반복한 성공 회차와 공개 commit 표기 탐지 실패는 이전 로그에 보존한다. 비밀 탐지 기준이나 기존 실패 목록을 완화하지 않았다. 최신 후보의 production 비밀 탐지 사전 점검은 0건이었다. 설치본 비교는 Windows 작업 파일 대신 후보 Git blob의 SHA-256을 사용한다.

## CI 설치·Android·브라우저 후속 검사

commit `9d5b7d0a6446`의 canonical G1은 **5,397 passed**, exit 0/NEW 0, Node **318 passed/0 failed**이다(`logs/land-ci-helper/`). 실제 pre-push 네 묶음은 516 + 9252 + 4550 + 4624 = **18,942 passed**, 각 exit 0/NEW 0이다(`logs/prepush-ci-compat/`). 다른 세션이 검사 중 같은 SHA를 먼저 푸시하여 이번 push 명령은 ref 경합으로 종료 1이었다. fetch 및 원격 ref 직접 읽기로 origin/main이 검사한 동일 SHA임을 확인했다. 이번 명령 자체의 push 성공으로 계산하지 않는다.

해당 SHA의 GitHub FULL CI `38184558238`과 Android CI `38184558259`는 실패했다. Fleet pytest 도우미·센싱 설치 의존성 보완은 통과했지만 공통 colcon 설치 다섯 job, Pilot Kotlin 컴파일, Fleet 브라우저 두 기대값은 별도 보완이 필요하다. Cam job은 fail-fast로 취소되어 통과로 계산하지 않는다. unsigned site build `38184558208` 성공은 서명·배포 증거가 아니다. 설치본은 종전 SHA이며 사람 계정을 변경하지 않았다.

colcon 외부 package_dir 임시 링크 정리가 실제 Discord 소스 디렉터리를 unlink하려는 원인을 확인했다. Fleet에 한해 colcon의 기존 full-install fallback을 사용하며 wheel/sdist·설치 자산 검사를 유지한다. 이 구성에서 Fleet은 `--symlink-install`에도 복사 설치되므로 편집 뒤 다시 빌드해야 한다. Pilot 공유 소스에 기존 PhoneHeat를 추가한다. 브라우저 검사는 동적으로 생성되는 이유 설명 ID를 구조 비교에서 제외하고 독립 로그인·안전한 복귀·고급 토큰 복구 흐름을 검증한다. 원격 Chromium 두 기대값은 `a73d0761b`에서 **2 passed**, exit 0/NEW 0이다(`logs/ci-browser-fix-green/`). 초기 수정의 잘못된 안내 selector는 1 NEW로 보존하고 실제 가용성 상태 요소의 정확한 문구·숨긴 로그인 form으로 보완했다. native_games_ui가 구조 검사와 복구 단언 보존을 승인했다.

Pilot 원격 Gradle 단위 검사·debug APK와 실제 bundled page proxy는 **BUILD SUCCESSFUL + 1 passed**, exit 0/NEW 0이다(`logs/pilot-phone-heat-green/`). 첫 실행에서 잘못 지정한 pytest 경로의 종료 4는 보존하며 전체 성공으로 계산하지 않는다.

최신 main의 설치 계약도 보존했다. `fc055ee116`의 wheel·sdist·계약 회귀는 CI pytest 7.4.4/setuptools 68.1.2와 최신 도구에서 각각 **4 passed**, exit 0/NEW 0이다(`logs/fleet-packaging-compat-green/`, `logs/fleet-packaging-modern/`). 이전 raw Requires-Dist 단언의 2 NEW는 이름·정확한 specifier·extras/marker/URL을 PEP 508로 확인해 해결했다. 실제 colcon-core 0.21.3/setuptools 68.1.2의 clean `--symlink-install` 및 legacy editable marker 정리는 종료 0이며 설치 import/alias·계약 버전·Discord Python 4개 원본·Console 76개 자산 바이트를 확인했다(`logs/colcon-fleet-migration-2/`). 최초 migration fixture의 누락된 내부 package symlink 실패도 원본 로그에 남겼다. 최신 setuptools는 upstream에서 develop uninstall 지원을 제거했으므로 이 legacy 전환 검증 범위는 명시한 68.1.2다. 통합 후보의 전체 CI·서명·설치는 다음 gate다.

native_games_ui가 legacy 정리·현대 도구 조건부 검사 및 정확한 Requirement 계약 비교를 최종 승인했다. robot_pilot_ui는 PhoneHeat 공유 소스의 직접 의존성·생성 경로를 승인했다.

## 전체 CI 호환성 보완

commit `40e7287971`은 추가 G1 **307 passed**와 canonical pre-push **7,828 passed**를 거쳐 push했다. 전체 CI [38180852375](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38180852375)의 scope·hardware-safety는 성공했으나 Fleet 시험 hook, Cell 인증 안내 기대 문구, 센싱 고립 설치 의존성 문자열 비교가 실패했다. unsigned 후보 빌드 성공은 CI 통과·서명·설치를 대신하지 않는다.

CI와 같은 pytest 7.4.4/setuptools 68.1.2/wheel 0.42.0을 canonical 원격 실행의 독립 작업 폴더에만 설치했다. 공유 시험 venv는 변경하지 않았다. diagnostic RED에서 `core-common >=0.0.1` 원문을 확인했고 PEP 508의 정규 이름·정확한 `>=0.0.1` 조건·extras/marker/URL 없음으로 검증을 바꿨다. provider identity·실제 설치 경로·버전·지도 바이트 조건은 유지한다. 예약된 `setup` helper만 이름을 바꿨으며 Cell의 401 기대를 실제 로그인·고급 접속 안내로 맞췄다.

수정 후 선택 원격 **95 passed**, 실제 Chromium Cell 거절·세션 초기화 **6 passed**, 각각 exit 0/NEW 0이다. RED는 1 NEW이며 기존 실패로 분류하지 않았다. `logs/ci-compatible-diagnostic/`, `logs/ci-compatible-green/`, `logs/ci-compatible-cell/`에 보존한다. 최신 통합·전체 CI·서명·설치·팀원 초기 계정 발급은 아직 진행 중이다.

최신 도구의 선택 회귀는 **101 passed**, exit 0/NEW 0이다(`logs/compat-modern-green/`). canonical G1은 최신 main 이동에 따라 두 회차를 수행했다. commit `c624339426`은 6165 + 4371 = **10,536 passed**, commit `03378323ea`는 6165 + 4396 = **10,561 passed**, 각 묶음 exit 0/NEW 0, Node 각각 **318 passed/0 failed**이다. 두 번째 후보는 로컬 main에 착지했다(`logs/land-ci-compat/uiux-header-all-surfaces/`).

새로 합쳐진 `test_channel_incidents.py` 도우미도 같은 pytest 7.4 hook 충돌을 일으켜 원격 **9 NEW**를 재현했다. 정의·호출 세 곳의 이름만 바꾼 commit `1e29edaed`는 같은 CI 도구와 최신 도구에서 각각 **9 passed**, exit 0/NEW 0이다(`logs/ci-peer-helper-red/`, `logs/ci-peer-helper-green/`, `logs/peer-helper-modern-green/`). native_games_ui가 의미·단언 보존과 확정 UX 문서 범위를 독립 승인했다. 출하 범위의 안전 검토 기록 **171 commits**도 통과했다(`logs/safety-ci-compat-range.txt`). 최신 main의 초기 API 제한·본인 프로필·초안 보존은 robot_pilot_ui가 추가 검토했다. 현장 선택적 Discord 설정 파일이 없는 것만 확인했고 외부 메시지를 보내거나 활성화하지 않았다.

최종 후보 전체 CI·서명·설치·초기 계정 발급은 아직 완료하지 않았다. 당사자 최종 비밀번호와 실제 로봇/폰/LCD 수용은 대신 완료하지 않는다.

## 첫 로그인·기본 내 프로필 — D-686/D-689

사용자는 팀원 네 명에게만 사람 계정을 발급하고 초기 비밀번호를 로그인 ID와 일치시키되 첫 로그인에서 반드시 변경하도록 요청했다. 기본 프로필은 표시 이름 수정·현재 비밀번호 확인 변경·ID/이메일/권한 조회로 확정했다. 기존 기계·운용·AI 자격은 보존하며 실제 명단·자격을 이 문서에 기록하지 않는다. 서버는 초기 쿠키의 운용 API 접근을 거절하고 기존 SQLite에서 자격·프로필·세션 회전을 관리한다. 화면 이름과 우상단 링크는 운용 용어 규칙에 맞춰 **내 계정**으로 통일했다. Map/Cell 새 탭으로 입력을 보존한다.

| 증거 | 결과와 범위 |
|---|---|
| `3704d9615` G1 영향 gate | 첫 묶음 6,511 passed / 1,049 skipped / 2 NEW, 둘째 521 passed / 48 skipped / 3 NEW. 버튼 disabled 사유, Fleet 크기 재판정, 문서 credential 오검출, 새 자산 3개 추가에 따른 wheel/sdist closure 기대를 수정 중이다. 착지되지 않았다. `logs/land-g1/uiux-header-all-surfaces/` |
| `afe5873f1` 강제 변경 UI RED | 2 NEW/known 0. 미구현 서버 전제의 강제 변경 시나리오와 D-686 prose 오검출을 확인했다. 같은 묶음의 지도 충돌 3개 크기·사유·wheel/sdist 검사는 통과했다. `logs/first-login-ui-red/run-1.txt` |
| `a7cf1b28a` 통합 첫 변경 | 2 NEW/known 0. 브라우저의 암시적 단일-page context와 long-ID 시험 fixture가 scanner에 걸린 것을 수정했다. 전체 묶음은 통과로 표시하지 않는다. `logs/first-login-integrated/run-1.txt` |
| `7ae3c7a67` 프로필 UI RED | 서버를 합치기 전 6 NEW/known 0, 네 진입 경로/비밀번호/실패 복구 시나리오의 미구현 endpoint를 확인했다. `logs/self-profile-ui-red/run-1.txt` |
| `73b23b956` 프로필·전체 인증/문서 호출자 | 적정 AI PC 22 cores/9 GB에서 173 passed, 종료 0, NEW 0. `logs/profile-green/run-1.txt` |
| `70e970acb` 잘못된 Unicode 입력 수정 | 같은 자격 원격 PC에서 프로필 20 passed, 종료 0, NEW 0. 단일 surrogate 거절과 기존 이름 보존, 정상 한국어/emoji 수용. `logs/profile-surrogate/run-1.txt` |
| `197b3d31f` 계정·첫 변경 화면 캡처 | 적정 Model PC 원격 Chromium 5 passed, 종료 0, NEW 0. 네 업무 진입의 320/1366px 계정 화면과 첫 변경 화면 9 PNG를 관측했다. 이후 제목은 내 계정으로 정렬했다. `logs/profile-capture/run-1.txt`, `evidence/profile-screens/sha256.csv` |
| `d002c579d` 최신 main 통합 영향 gate | 첫 묶음 6921 passed / 800 skipped / 2 NEW, 둘째 537 passed / 309 skipped / 1 NEW, known 0. 계정 화면 용어·CORE API 설명 핀·합친 계획 문서의 공개 commit 표기 문제가 남아 착지하지 않았다. `logs/land-profile-final/uiux-header-all-surfaces/` |
| `900bd1f708` 세 실패 수정 재검증 | 적정 Site PC 3.3 cores/8.6 GB에서 실패한 세 시험 3 passed, 종료 0, NEW 0. 용어·API 설명·비밀 탐지 기준을 유지하고 소스 표기를 수정했다. `logs/g1-corrections/run-1.txt` |
| `f4022f1d5` G1 재검사 첫 회차 | 적정 Site PC 4.6 cores/8.6 GB에서 5459 passed/847 skipped와 4525 passed/275 skipped, 각각 종료 0/NEW 0. Node 321 passed/0 failed. 검사 중 main이 바뀌어 착지하지 않고 다음 회차를 시작했다. `logs/land-profile-retry/uiux-header-all-surfaces/run-1-*.txt`, `node-1.txt` |
| `c4e589628c` 추가 main 통합 회차 | 적정 Model PC 22 cores/9 GB에서 첫 묶음 5459 passed/847 skipped/30 subtests passed, 종료 0/NEW 0. Fleet 묶음은 SSH 연결 종료로 중단되어 통과로 인정하지 않는다. 뒤이은 SSH 접속도 timeout이었다. known_failures 출력 0 NEW는 최종 pytest 결과를 대신하지 않는다. 착지·push·배포되지 않았다. `logs/land-profile-retry/uiux-header-all-surfaces/run-2-*.txt` |
| `e2d8a0f417` 현장 PC 재시도 | 최초 5.3 cores/8.7 GB의 적정 자원에서 시작했으나 첫 묶음은 SSH 연결 종료, 둘째는 접속 timeout으로 중단됐다. 뒤이어 host uptime이 Site 1분/AI 10분인 재부팅 상태임을 확인했다. 이번 묶음의 최종 pytest 결과와 착지 증거는 없다. 현장 설치 SHA는 종전 설치본이며 사람 계정을 변경하지 않았다. `logs/land-profile-network-retry/uiux-header-all-surfaces/` |
| 독립 검토 | D-686 원본 설정 변경 세션 무효화, D-689 Unicode 경계, 키보드 초점, 만료 시 비밀 삭제와 타 탭 계정 변경을 발견하고 수정했다. 수정된 서버 명세/품질과 UI에 추가 blocker 없음. 실제 시험과 배포 증거를 대신하지 않는다. |

`83c2a49fd` 통합 브라우저/인증/자산 검사는 통과했으나 비밀 탐지 1 NEW가 남아 전체 실패였다. 변수 참조와 이미 허용된 합성 fixture 표현을 정리하고 탐지 기준을 유지했다. `e592eb8e8` 최종 인증/프로필/실제 Chromium/disabled 사유/비밀 탐지/P6는 143 passed, 종료 0, NEW 0이다 (`logs/profile-final/run-1.txt`, 적정 AI PC 22 cores/9 GB). 최신 main 영향 gate·해당 SHA CI·서명·설치·실제 팀원 발급은 아직 확인하지 않았다. 당사자 대신 최종 비밀번호를 정하지 않았고 실제 첫 변경·실물 수용을 완료로 추정하지 않는다.

## 계정 규칙 후속 정리 — D-683

[공식 참고와 배치 근거](../../plans/2026-10-12-platform-ux-conventions-design.md)를 조사하고 [D-683](../../adr/D-683-fleet-account-entry-and-login-return.md)으로 Fleet 계정 진입 규칙을 채택했다. 네 문서의 우측 로그인/계정, `/console/login`, 허용된 업무 주소 복귀, 서버 세션 확인, 쿠키 로그아웃 결과 검증을 기존 인증 API로 구현했다. 지도·Cell 로그인은 새 탭으로 열고 원래 업무 입력을 보존한다. CORE 권한과 명령을 추가하지 않는다.

| 증거 | 결과와 범위 |
|---|---|
| `2180826c3` 원격 인증 회귀 | 21 passed / 2 failed. 옛 내장 폼 전제와 접힌 토큰 클릭을 수정했다. `logs/account-login-first/run-1.txt` |
| `ab05a034c` 원격 확장 | 66 passed / 2 failed. 390px 안전 그룹 오른쪽 정렬 결함과 지도 보기 선택을 수정했다. `logs/account-login-corrected/run-1.txt` |
| `b9145fa9b` 원격 인증·전체 지도·헤더·백엔드 | 169 passed / 8 failed, NEW 8. 인증/계정은 통과했으나 전체 묶음은 실패다. 재접속 후 편집 선택의 Apply gating 복원, 인증 확인 후 고급 접속 접힘, 새 계정 노드를 포함한 Node fixture를 수정했다. 충돌 초안을 버리는 옛 기대는 로컬 입력 보존과 기존 CAS 거절 검증으로 바꿨다. `logs/account-login-final/run-1.txt` |
| `b9145fa9b` 루트 관제 헤더·개발/paired 연결 | 4 passed, 종료 0, NEW 0. `logs/account-root-header/run-1.txt` |
| `d3dac3633` 전체 Console Node | 312 passed, 종료 0. `logs/account-node-all.txt` |
| `d3dac3633` 수정 후 인증·전체 지도·관제 헤더 | 95 passed / 1 failed, NEW 1. 반복 재접속이 끝나기 전에 펼침을 여는 경쟁 조건을 수정했다. `logs/account-map-restored/run-1.txt` |
| `440385e24` 같은 브라우저 묶음 | 95 passed / 1 failed, NEW 1. 실패는 대기 helper의 문자열 predicate가 CSP eval 거절을 받은 것이며 CSP를 유지하고 함수 predicate로 수정했다. `logs/account-map-settled/run-1.txt` |
| `0d01b320c` 재접속·편집 보존·충돌 최종 | 5 passed, 종료 0, NEW 0. 반복 재접속, 적용 전/후 편집 보존과 3개 크기 충돌 후 CAS 거절을 실제 조작으로 확인했다. `logs/account-reconnect-final/run-1.txt` |
| `06ce50c4a` Android proxy | JVM/assemble BUILD SUCCESSFUL, 실제 번들 proxy 브라우저 1 passed, 종료 0, NEW 0. 앞선 403은 시험의 고정 쿠키 이름을 앱의 세션별 이름으로 전달해 해결했다. Guard와 신원 확인은 보존한다. `logs/pilot-proxy-cookie/run-1.txt` |
| 독립 소스 검토 | `440385e24` 계정/편집 복원과 `06ce50c4a` proxy fixture에 추가 blocker 없음. 현재 검증된 역할로 편집 조작을 복원하며 원래 revision의 CAS를 보존한다. 읽기 전용 검토이며 배포/브라우저 통과를 대신하지 않는다. |

증거 경로는 공용 세션 `X:/DevTemp/projects/rosy-platform/2026-10-12--015344--fleet-header-proof--958a02/` 기준이다. `evidence/account-screens-final/`의 10개 PNG는 시험 서버의 로그인 및 네 계정 메뉴 320/1366px 관측이며 설치본 증거가 아니다. 해당 계정 시나리오는 `b9145fa9b`와 후속 묶음에서 통과했다. 실패한 전체 묶음을 통과로 합산하지 않으며, 나머지 95개 통과와 마지막 5개 재접속 통과를 각 SHA/범위로 구분한다.

계정 변경은 main 및 원격 동일 SHA에 반영됐으나 해당 CI가 실패하여 서명·새 설치·계정 발급·실물 수용은 완료하지 않았다. 아래의 과거 설치 관측과 혼용하지 않는다.

## 범위와 정보 위치

사용자 요청은 Fleet 네 화면의 공용 헤더에서 모든 활성 UI의 본문·작업 흐름까지 확대되었다. 기준은 `shared/web/surfaces.yaml`, D-658, 기존 표면별 계약이다. 변경은 `uiux/header-all-surfaces`에서 통합했다. 공유 main의 다른 작업은 수정하지 않았다.

| 화면 | 정보가 그 자리에 있는 이유 | 이번 변경 또는 유지 근거 |
|---|---|---|
| Fleet 관제·설치·지도·Cell | 상단의 제품·현장은 작업 대상을 식별하고, 연결·권한은 가능한 행동을 설명한다. 알림·접속은 보조 조작이며 비상 정지는 계속 노출된다. 본문은 각 역할의 작업을 맡는다. | 기존 D-658 공용 헤더를 네 화면에서 검증했다. 명시된 아이콘 전용 속성을 보존하도록 공용 부품 회귀를 고쳤다. |
| Cell 준비·저장·미리보기·제안 | 단계 안내는 다음 작업을 설명한다. 미구성 안내와 비활성 이유는 서버 작업을 다시 눌러도 해결되지 않는 원인을 알려 준다. | 미구성 응답 뒤 서버 작업을 차단하고 구성 확인 사유를 표시한다. 로컬 입력·접속·비상 정지는 유지하며 정상 재접속 뒤 복구한다. |
| Robot 접속·운용·작업 준비·설치 정비 | 제품·화면 이름은 현재 역할, 권한 표시는 가능한 작업, 본문의 실패 안내는 재시도 경로를 설명한다. | 역할 이름과 접근성 설명을 정리했다. manifest 실패에 수동 재시도를 제공하며 좁은 화면에서 권한 표시 잘림을 막았다. |
| Pilot 웹 접속·조종 | 대상·비상 정지는 가장 먼저 보인다. 연결·지도 근거와 접속 안내는 다음 줄, 현재 대상과 로그인은 최근 기록보다 먼저 둔다. | 잘못된 최근 기록과 다른 대상 기록을 제외하고 이전 토큰을 제거한다. 지연·끊김·증거 없음은 현재 정지로 표시하지 않는다. 안전 정지 보고는 safety evidence로 판정한다. 연결 상태와 검색 요약의 겹침을 막았다. |
| Learning 작업·객체·픽셀·자료 | 첫 줄은 자료 검수의 역할과 화면 설정, 둘째 줄은 작업 전환이다. 본문은 출처·초안·저장·승인을 구분한다. | 320px에서 세 줄로 늘어나던 헤더를 두 줄로 정리하고 픽셀 화면의 테마 설명을 맞췄다. 기존 검수·승인 흐름을 회귀 검사했다. |
| Pilot Android | 로비는 대상 발견·선택·접속을 담당한다. 함께 조종 버튼 바로 아래는 차단 이유와 다음 행동을 설명한다. | 기존 활성 조건과 같은 연결 가능 수·발열 상태로 안내를 표시한다. 좁은 로비에도 Pilot 정체성을 남긴다. |
| Cam Android | 영상이 중심이고 송출 상태·설치·복구는 기존 전용 영역에 둔다. | 역할별 소스 검토 후 기존 배치를 유지했다. 실물 송출·승인 확인은 별도다. |
| 경기 보드 | 경기 단계·수신 근거는 상단, 점수·관측은 본문, 두 로봇 정지와 요청 결과는 고정 조작 영역에 둔다. | 기존 역할과 지연·끊김·정지 요청/확인 구분을 유지하고 브라우저 회귀에 포함했다. |
| 로봇 LCD | 작은 표시 장치에서 로봇 정체성·부팅·로그인 코드를 판독하도록 기존 표시 문법을 쓴다. | 소스 검토와 기존 그림 회귀에 포함했다. 입력 권한이 없는 매체에 웹 조작을 복제하지 않았다. |

PARKED 진단과 개발용 시뮬레이터를 활성 제품 화면으로 바꾸지 않았다. 상세 native 검토는 `docs/validation/uiux-native-games-2026-10-12.md`에 기록했다.

## 원격 회귀와 검토

시험은 커밋된 HEAD를 원격 시험 PC에서 실행했다. 브라우저 시험은 `ROSY_RUN_BROWSER_TESTS=1`로 활성화했고, 적정 CPU·메모리 placement만 허용했다. 각 종료 로그에 `test/known_failures.py`를 적용했다. 노트북 pytest는 실행하지 않았다.

| 대상 | 커밋 | 결과 | 증거 |
|---|---|---|---|
| Fleet 헤더·역할·Cell / 공용 아이콘 / Learning 검수·픽셀 / 경기 보드 / LCD | `fbd51016f9` | 342 passed, 종료 0, NEW 0 | 공용 세션 `logs/combined-fixed/run-1.txt` |
| Robot/Pilot 전체 관련 회귀 | `039bbbffa` | 176 passed, NEW 0 | Robot/Pilot 작업 세션 원격 로그 |
| Pilot 상태 신선도·잘못된 기록·토큰 제거 | `e01abed518` | 27 passed, NEW 0 | Robot/Pilot 작업 세션 원격 로그 |
| Learning 네 화면 작은 헤더 + Cell 미구성·복구 캡처 | `70cf1fd7c8` | 9 passed, NEW 0 | 아래 공용 세션 `logs/captures-fixed/run-1.txt` |
| Pilot Android 단위 검사·APK | `b3b44ca1a`의 native 변경 | BUILD SUCCESSFUL, 106 tests, 0 failures/errors | `X:/DevTemp/native-ux-a1f3c9/gradle.txt`, XML 및 debug APK |

독립 검토는 Cell·공용 변경과 Robot/Pilot 변경을 각각 검토했다. 오래된 속도를 현재 정지로 단정하던 발견 사항은 기존 `HeadlessState`를 재사용해 수정했고 재검토에서 차단 사항이 없었다.

초기 실패도 보존했다. Cell 재접속 시험의 접힌 접속 버튼 클릭은 기존 펼침 helper로 수정했다. 캡처 실행의 잘못된 원격 사용자 홈 경로는 임시 실행기에서 수정했다. 둘 다 NEW로 분류했으며 기존 실패 목록에 추가하지 않았다. 자원 기준 미달 fallback 실행은 적정 자원 확인 증거로 계산하지 않는다.

## 변경 후 화면 캡처

공용 증거 세션은 `X:/DevTemp/projects/rosy-platform/2026-10-12--015344--fleet-header-proof--958a02/`다. `evidence/shots/`의 Learning 네 화면 320×568·390×844와 Cell 390×844·1440×900을 보관했다. Learning 320px 작업·픽셀 화면과 Cell 390px 화면을 직접 열어 역할·다음 행동·서비스 미구성 안내를 확인했다. 파일별 SHA-256은 같은 세션의 `evidence/capture-sha256.csv`에 기록한다.

## 실제 설치본 확인과 남은 경계

현재 사이트의 Fleet 컨테이너 source revision은 `5f4040f306bf076648993376ed85834824e8d744`였다. 해당 설치본 `/console`, `/console/install`, `/console/site-map`, `/console/cell`을 1366px·320px에서 직접 열었다. **8 조합**에서 네 헤더 영역, 가로 넘침, 48px 정지·이동 조작, 글자/여백, 브랜드 자산 응답을 확인했다. `evidence/live/result.json` 및 8 PNG가 관찰 기록이다. TLS 인증서 신뢰 확인을 생략하는 브라우저 옵션을 사용했다. 이 기록은 새 변경의 배포 증거가 아니다.

이 절의 최초 관측 당시에는 main 착지·push·새 설치를 수행하지 않았다. 이후 명시 승인으로 통합·푸시 검사를 진행했으며 최신 상태는 문서 첫 절의 후속 기록을 따른다. 로봇 접속 실패와 ADB 기기 부재 때문에 실물 Robot·Pilot·Cam·LCD 및 실제 작업 수용은 미확인이다. 비상 정지 해제·주행·페어링·Cell 작업 제안 같은 운영 변경으로 화면 검사를 대신하지 않았다.

## 최종 후속 검증

- `a2357a8504`: responsive tiers, UI token contracts, document placement, folder layout 원격 **64 passed**, 종료 0, NEW 0. 공용 세션 `logs/contracts/run-1.txt`.
- Robot/Pilot 원격 세션: `X:/DevTemp/projects/rosy-platform/2026-10-12--020319--robot-pilot-ux--7d7d85/`. 위 176/27 결과의 정확한 위치는 `logs/browser/run-1.txt`, `logs/captures/run-1.txt`다.
- `ab2f331a4`: Robot 전체 캡처 **3 passed**. `432e39895`: Pilot 겹침·Robot 권한 잘림 회귀 **8 passed**. `855e5b46a`: Robot 입구의 권한 한 줄 회귀 **3 passed**. 모두 종료 0, NEW 0이며 각각 같은 세션의 `logs/robot-captures`, `logs/visual-final`, `logs/entry-final`에 있다.
- 마지막 캡처에서 Robot 입구 권한이 세로로 쌓이던 문제를 발견해 기존 공용 wordmark의 container sizing과 권한 nowrap으로 수정했다. 부모 통합 커밋은 `e6bcbb960`이며 후속 회귀가 해당 소스 변경을 검증했다.
- 같은 세션 `evidence/browser/`에 Pilot 4 화면 크기 × 빈 목록/읽기 실패 8장, Robot 입구·운용·작업 준비·설치 정비 320/390 총 8장을 보관했다. 통합 담당자도 Robot 입구·작업 준비 및 Pilot 실패 화면 320px를 직접 열어 권한 판독·본문 다음 행동·비상 정지 노출을 확인했다.
- 변경하지 않은 Cam·LCD·경기 보드의 기존 배치는 역할 검토를 통해 유지했다. 경기 보드·LCD의 초기 원격 호스트 미확인 기록은 이번 통합 회귀 342 passed의 범위에서만 해소되었다. 실물 장치와 설치된 게임 호스트 검증은 여전히 별도다.

## 승인 후 통합 검사와 발견 사항

사용자는 위 최초 기록 이후 main 착지·push·새 버전 배포 검증을 명시적으로 승인했다. 진행 목표는 `docs/plans/2026-10-12-field-ui-recovery-brief.md`의 현장 운용·오류 복구이며 추가 승인 대기 상태가 아니다.

- `80a12948c`의 적정 자원 전체 영향 검사에서 첫 묶음은 독립 검토의 공용 예외 보존 결함을 재현한 뒤 중단했다. 종료 2, 15 failed / 7204 passed / 68 skipped이므로 이 묶음 전체를 통과로 계산하지 않는다. 두 번째 묶음은 249 passed로 정상 종료했지만 도구는 착지하지 않았다. 원본은 공용 세션 `logs/land/uiux-header-all-surfaces/run-1-1.txt`, `run-1-2.txt`다.
- `known_failures.py`는 관측한 15건을 NEW로 분류했다. 위치 순서에 의존하던 로봇 조작 선택, 이전 헤더 접힘 가정, 지도 저장 응답을 기다리지 않던 관측, 공용 연결 오류의 변경된 안내를 실제 목적·계약과 맞춰 고쳤다. 기존 실패 목록에 추가하지 않았다.
- 공용 오류 어댑터의 null 취소 이유, frozen TypeError, read-only DOMException은 새 Node 세 사례에서 모두 실패했다. 예외 객체·취소·비재전송을 보존하는 수정 뒤 요청 계약 포함 36 passed다. 독립 검토는 동일 수정안을 재검토해 추가 차단 사항이 없음을 확인했다.
- Android 앱 proxy 시험은 Linux에서 Windows 전용 gradlew.bat·JAVA_HOME·X 경로를 사용해 PermissionError로 실패했다. 파일 blob은 기준·main·후보에서 같지만 깨끗한 main 실행 증거 없이 기존 실패로 승격하지 않는다. Linux의 기존 Java/Gradle wrapper는 확인했고 SDK/고정 의존 캐시 준비와 portable 실행 보완이 필요하다.
- Pinky 두 대 오프라인 및 ADB 연결 기기 부재를 다시 확인했다. 실물 화면·사용자 작업 수용을 완료로 표시하지 않는다.
