# Account 변경 기록

## 2026-11-02 · uncommitted · 인증 계약의 실제 응답 증거 갱신

- 변경: 공통 Account로 이동한 13개 handler의 검증표 소유 경로를 바로잡고, 개발 세션 발급은 403 거절로 검증한다. Fleet 호환 import 검사는 기존 alias와 Account 모듈의 동일성을 명시적으로 확인한다.
- 증거: `e82b3cfc73` 소유·호환 import 원격 3 passed. `023d9915a3` 실제 HTTP 수집 9 passed, 인증 요청 15종의 응답·passing node 수집. 같은 SHA의 sample 로그인·거절·로그아웃과 Chromium 전송 흐름 2 passed, skip 0. 이 증거는 운영 사용자 로그인 수용을 대신하지 않는다.
- 경계: 운영 PC의 기존 인증서 호스트 매핑은 관리자 승인 뒤 기존 파일 바이트를 보존해 한 줄만 추가했다. 일반 이름 해석과 인증서 검증을 유지한 Python·Edge의 기존 Fleet health 응답 200을 확인했다. 계정 DB·서비스 전환은 아직 적용하지 않았다.
- CE: 검증표·호환 import 수정은 코드와 회귀 시험이 설명한다. 기존 로그인 화면 교훈 외의 새 교훈은 추가하지 않는다.
- gate 변화: SOURCE·LOCAL GO, ARTIFACT·FIELD HOLD. 이번 검증은 서명 설치나 운영 사용자 수용을 증명하지 않는다. ROS-SIM·DEVICE N/A.

## 2026-11-02 · uncommitted · D-962 독립 인증 소유 모듈

- 변경: 기존 계정·비밀번호·프로필·grant·세션·OAuth·감사를 독립 모듈로 이동했다. 활성 authority의 열 개 테이블·원자적 회수·계정 식별자를 보존하며 Fleet은 서명 자격을 검증하는 receiver가 된다.
- 증거: `da5aab6c09` 원격 Account/브라우저 279 passed, 공유 클라이언트·수신 66 passed, skip 0/NEW 0. `dd9d55404f` 모듈 소유 표식·크기·중복·독립 import 58 passed. 최종 설치와 실제 사용자 수용은 별도다.
- 경계: 서명 이미지 공유가 프로세스·원장·키 공유를 뜻하지 않는다. Account는 Fleet·ROS를 import하지 않는다. 복구 권한은 보존된 receiver 세션의 최신 서명·온라인 회수 상태를 요구한다.
- CE: 로그인 화면과 개발 모드의 결합 교훈은 공통 solutions에 기록했다. 추가 인증 로직은 코드·회귀 시험·D-962가 설명한다.
- gate 변화: SOURCE·LOCAL GO, 서명 설치 ARTIFACT·운영 수용 FIELD HOLD. ROS-SIM·DEVICE N/A.

## 2026-11-02 · uncommitted · 독립 배포 의존성과 통합 검사 보완

- 변경: Fleet은 `rosy-account==0.1.0`을 별도 배포 의존성으로 요구한다. CI wheel 목록·기존 Fleet 조건부 설치·이미지 시험 구성에 Account를 포함하고 Fleet 배포물의 중복 소유를 없앴다. API 이력 행과 추가 서비스의 로그 제한 검사도 보완했다.
- 증거: `8ec7d66580` API·공개 출처·로그 검사 24 passed. `3286f5528e` 실제 wheel·sdist·설치·CI 관련 24 passed와 기존 실패 네 항목의 격리 재실행 4 passed, isolation complete 4, skip 0/NEW 0. 같은 head의 독립 검토 지적 없음.
- 경계: 과거 공개 Actions pin은 독립 검토로 upstream commit API·태그를 확인한 정확한 과거 commit/path/rule 기록만 사용한다. 비밀 탐지 정책은 바꾸지 않는다. 런타임 인증·grant·장치 제어 계약은 그대로다.
- CE: 추가 패키징 판단은 의존성 선언·실제 설치 회귀 시험이 설명한다. 기존 로그인 화면 교훈 외의 새 교훈은 늘리지 않는다.
- gate 변화: 통합 FULL은 실패 수정 후 재실행 대기다. 서명 산출물 ARTIFACT·운영 수용 FIELD HOLD를 유지한다.

## 2026-11-02 · uncommitted · 사람 로그인 보완과 읽기 전용 기계 자격 보존

- 변경: 천장 marker 도구의 폐기된 Fleet 개발 로그인 옵션은 네트워크 전에 사람 로그인과 `ROSY_FLEET_TOKEN`을 안내하고 종료한다. 기존 상태 점검 viewer는 권한·토큰을 유지하고 `machine: true`인 token-only viewer만 receiver에서 명시적으로 보존한다. 기존 점검 계정 생성기도 같은 표식을 보존한다.
- 증거: `643c3b399c` 적색 뒤 `453d43267f` 원격 보정 도구 11 passed. `b2537af54b` 적색 세 항목 뒤 `8faa6099e1` loader·receiver·writer 126 passed. `ca93b3dddb` 점검 계정 생성기 35 passed. 모두 skip 0이며 실제 시험 API에서 상태·비전 조회 허용, 정지·작업 제안 거절과 사람의 이전 Bearer 거절을 확인했다.
- 경계: YAML·직접 구성·registry writer는 사람 로그인·비밀번호·정책 권한과의 결합 및 잘못된 marker를 거절한다. CORE의 별도 개발 인증과 보정 계산·동작은 그대로이며 실물 주행은 실행하지 않았다. 운영 계정 설정은 아직 적용하지 않았다.
- gate 변화: SOURCE·LOCAL GO, ARTIFACT·FIELD HOLD. 통합 FULL과 서명 설치·운영 수용은 별도 증거다. ROS-SIM·DEVICE N/A.
- CE: 경계 판단은 명시적 설정 계약과 회귀 시험이 설명한다. 기존 로그인 화면 교훈 외의 새 교훈은 늘리지 않는다.

## 2026-11-02 · uncommitted · 유지보수 상태 조회의 등록된 기계 자격 사용

- 변경: 유지보수 guard는 현재 functional_checks에 같은 경로로 등록된 상태 점검 토큰이 실제로 있을 때 그 읽기 전용 자격을 사용한다. 초기 설치는 기존 bootstrap 경로를 유지하며, HTTP 실패 뒤 다른 자격으로 재시도하지 않는다. 작업·목표·hold 검사 조건은 그대로다.
- 증거: `95ae8d2414` 원격 적색 뒤 `a1ad46665c`의 guard·receiver 검사 48 passed, skip 0. 등록되지 않은 미리 생성된 토큰은 사용하지 않으며 기계 viewer의 실제 API 상태 조회를 확인했다. 독립 계약 검토 지적 없음.
- gate 변화: SOURCE·LOCAL GO. 통합 FULL, 서명 설치와 실제 사용자 로그인 수용은 아직 완료되지 않았다.
- CE: 해당 없음 — 선택 조건과 권한 경계는 최종 코드·회귀 시험이 설명한다.

## 2026-11-02 · e81af2d7c3 · D-962 independent Account artifact

- Change: Account image is independently built from Account and its minimal foundation contract; no Fleet or Control Unit runtime/build service is required. Fixed UI bundle keeps three pages, eight Account assets and twelve common assets. Account has UID/GID10001 and no setuid capabilities. Remote minimal-source startup and real TLS login/initial-password/profile/admin passed. ARTIFACT/FIELD stay HOLD pending OCI construction and independent-image deployment. CE: no separate lesson; the artifact boundary and regressions encode this change.
- Evidence: D-962 independent image scope: remote AI-PC closure at e81af2d7c3 passed 320 tests, 0 skipped, 0 NEW. Account TLS login/initial-password/profile/admin, minimal Account/foundation startup, stdlib-only fixed assets, signed legacy/new inventories and reuse, and Fleet header browser/Node compatibility. OCI build and live independent-image acceptance were not run.
- Log: `rosy-account-image-closure/run-1.txt`; native `size_range.py d7fcc74e43 b9424451a0` checked four commits successfully; native static secret scan found zero findings.
- Gate: scoped SOURCE/LOCAL verification only; existing artifact, device and field limits remain.


## 2026-11-02 · 5f02d723d1 · D-962 independent identity backup and presentation

- Change: Independent identity maintenance uses the dedicated signed Account image and exact existing external Account volume, never a replacement empty volume or Fleet fallback. Existing stdlib SQLite utility is packaged unchanged. Explicit history/audit retention0 preserves every authority table, including account_http_audit; daily backup keeps14 files and six-hour checks require integrity and age<=48h. Backup/check units are opt-in only after healthy migration; no timer was enabled. Account identity pages use the common Account brand. CE: no new lesson; code, tests and runbook encode the new boundary.
- Evidence: D-962 independent image and identity backup scope at 5f02d723d1: remote 335 backend/signing/image/backup cases plus 71 opted-in identity TLS/browser cases passed, 0 skipped, 0 NEW. Full Account tables including HTTP audit preserved; stale/corrupt backup refusal, strict signed legacy/new groups, reused image pins, branding, login/profile/admin and first-password flows verified. Prior e81af2d7c3 closure also passed 320 cases including Fleet header browser/Node compatibility. OCI construction and live independent-image/timer acceptance remain pending.
- Logs: `rosy-account-backup-replay/run-1.txt` (335 passed), `rosy-account-identity-replay/run-1.txt` (71 passed); known-failure comparison 0 new/known/flaky. Native size range checked eight commits without a violation.
- Gate: scoped SOURCE/LOCAL GO; image artifact, installation, timer activation and human field acceptance remain separate.

## 2026-11-02 · d90ee50ad3 · 독립 Account 페이지의 명시적 제품 맥락

- 변경: Account 정적 페이지 owner가 로그인·프로필·계정 관리에 Account 맥락과 이름·아이콘을 표시한다. 공용 로그인 모듈은 이 표시를 사용하고 기존 authorize 복귀 판단과 검증은 유지한다. 독립 프로필의 기본 복귀가 자기 화면으로 되돌아가는 링크는 숨긴다. Fleet 페이지·쿠키·scope·권한·이관·writer는 바꾸지 않는다.
- 증거: 최신 main 통합의 독립 검토에서 직접 로그인과 프로필 경유 로그인에 Fleet 이름이 남음을 발견했다. 추가한 committed 서버·실제 TLS Chromium 회귀는 적색 4 failed/6 passed로 재현했다. 구현 후 같은 경로와 기존 등록 앱·최초 비밀번호 흐름을 함께 검증한다.
- gate 변화: 없음. 소스·브라우저 확인은 서명 배포나 운영 단일 writer 이관·실제 사용자 로그인 수용을 대신하지 않는다.
- CE: 해당 없음 — owner 표식과 회귀 시험이 제품 맥락 보존 조건을 설명한다.

## 2026-11-03 · 472c6ab842 · CI가 Account의 oauthlib를 시스템에 설치

- 변경: CI는 `oauthlib==4.0.0`을 `/tmp/rosy-receiver-crypto` target 대신 시스템 Python에 설치한다. 설치 패키지 시험과 Account 경계 시험은 `python3 -I`나 바꾼 `PYTHONPATH`로 하위 프로세스를 띄워 target 폴더를 보지 못했다. `test_ci_dependencies`가 pin을 target에 다시 넣으면 실패한다.
- 증거: 게시 PR 228 CI의 root-test-1of3·site-vision-cell이 `ModuleNotFoundError: oauthlib`로 적색. 수정 뒤 `test/test_ci_dependencies.py` 38 passed, 옛 ci.yml에서는 강화한 시험이 실패. 시험 PC는 시스템에 oauthlib가 있어 착지는 녹색이었다.
- gate 변화: 없음. 공개 CI 녹색은 다음 게시 PR에서 확인한다.
- CE: 해당 없음 — 재발은 강화한 CI 의존성 시험이 막는다.

## 2026-11-03 · e84e4f46b3 · 로그인 전 자기 화면 복귀 제거

- 변경: Account owner의 로그인 전 복귀 링크를 숨겨 직접·프로필·관리 진입에서 같은 로그인 요구 화면으로 되돌아가는 동작을 없앤다. authorize 복귀 검증·자동 계속·등록 앱 callback은 유지한다.
- 증거: 실제 owner HTML의 최신 소스 캡처와 원격 TLS 브라우저 회귀의 적색 1건. 직접·프로필·관리 진입의 숨김을 회귀로 보존한다. 운영 authority·세션·권한·설정·writer는 바꾸지 않는다.
- Gate: 원격 수정본 확인 및 배포 전. CE: 해당 없음 — 공유 조건과 회귀로 동작을 복원할 수 있다.

## 2026-11-03 · 50b5b4340d · 최소 Account 이미지의 공용 작업면 통합

- 변경: 최소 Account 자산 묶음은 기존 공용 조작 스타일의 정확한 파일을 포함한다. static module의 표준 라이브러리 전용 import를 보존하며 FastAPI 응답은 설치 함수 안에서 가져온다. 실행 시 Account owner 표식·제품 제목·CSP·경로 검증을 보존한다. 익명 직접·프로필·관리 진입과 로그인 후 흐름 모두 자산 오류를 수집한다.
- 증거: 새 committed 통합본의 독립 import·bundle 폐쇄성·실제 TLS 브라우저 확인이 필요하다. 이전 소스의 통과는 해당 소스의 범위로 남긴다.
- Gate: 통합 SOURCE 검증 전이며 운영 authority의 계정·세션·토큰·비밀번호·키를 변경하지 않았다. CE: 해당 없음 — 설치 자산 검사와 owner 회귀로 검증한다.

- 후속 검증: 21f1dcd378의 독립 import·최소 bundle·Node·화면 제목 16건 통과 후, 4493982d05에서 정확한 한국어 heading/intro와 static owner 치환을 보정했다. 해당 수정본의 실제 독립 TLS fixture·등록 callback·최초 비밀번호·기존 Fleet·sample을 포함한 브라우저 112건은 원격 PASS/0 SKIP/exit 0/NEW 0이다. 독립 재검토 지적 없음이다. 테스트 authority/합성 fixture와 익명 소스 미리보기의 범위이며 운영 계정이나 운영 callback 수용으로 대신하지 않는다.

## 2026-11-03 · bfd53106b3 · 최소 Account 이미지의 실제 스타일 입력 연결

- 변경: 공용 조작 스타일이 최소 bundle뿐 아니라 Docker COPY·전용 제외 목록·이미지 재사용 입력까지 연결되도록 했다. 고정 자산 목록의 정확성과 공용 원본 바이트 일치를 보존한다.
- 증거: 수정 전 Docker 문맥 시험 1 NEW를 재현했고, 수정본의 이미지·후보·workflow 37건과 원래 파일 전체 단독 실행 1건이 공식 원격 PASS/0 SKIP/NEW 0이다. 독립 경로 검토는 전파 누락·검증 약화 지적 없음이다.
- Gate: 실제 OCI 아티팩트와 운영 수용 전이다. 계정·세션·키·토큰·writer 상태는 바꾸지 않았다. CE: 해당 없음 — 고정 파일 계약과 원본·COPY·허용 검사로 재발 조건을 검증한다.

## 2026-11-07 · uncommitted · Account 화면에서 자기 자신으로 되돌아가는 링크 제거
- 변경: Account가 내는 문서의 브랜드는 /console/profile로 바로 가고, 이 출처에 없는 관제로 돌아가기 링크를 뺀다.
- 증거: 현장 사이트에서 두 링크 모두 303 /console 뒤 /console/profile로 되돌아감을 봤다.
- Gate: 실제 이미지와 운영 수용 전이다. 계정·세션·권한은 바꾸지 않았다.
## 2026-11-07 · uncommitted · Account 진입 문서와 소유자 안내 정정

- 변경: `README.md`를 더하고 앱 책임·이름 문서의 Account 소유자를 D-962 기준으로 고쳤다. Vault 권한은 원장 확인 전까지 남긴다고 프로토콜에 적었다.
- 증거: 문서 변경. 원격 결과는 착지 기록을 따른다.
- Gate: 없음. CE: 해당 없음 — 문서 정정이다.

## 2026-11-07 · uncommitted · feat(account): 연동 등록부 (D-955 2단계)

- 변경: client 목록을 Account DB `account_clients`로 옮겼다. `accounts.manage`가 관리 화면과 API로 재시작 없이 등록·수정·정지한다. 보호 JSON은 빈 등록부에 한 번만 가져온다. 추출 이전은 등록부가 있으면 함께 옮긴다.
- 증거: 원격 시험 결과는 착지 기록을 따른다. 실제 현장 Account의 등록부 전환은 확인하지 못했다.
- Gate: 없음. CE: 해당 없음 — 결정된 단계의 구현이다.

## 2026-11-07 · uncommitted · feat(account): 앱 목록 (D-955 4단계)

- 변경: 등록부에서 그 사람이 권한을 가진 사용 중인 앱을 `/api/fleet/auth/apps`로 준다. 공용 세션 응답과 공용 계정 표시가 이를 앱 전환 메뉴로 보여 Robot·Pilot·Games·Monitoring·Learning·Fleet이 같은 목록을 읽는다.
- 증거: 원격 시험 결과는 착지 기록을 따른다. 실제 현장 앱 사이 이동은 확인하지 못했다.
- Gate: 없음. CE: 해당 없음 — 결정된 단계의 구현이다.

## 2026-11-07 · uncommitted · feat(account): 장비 등록과 등록부 연결 (D-992)

- 변경: Fleet 등록 키로 그 로봇 줄만 쓰는 `PUT /api/fleet/auth/device-clients/{robot_id}`를 더했다. 관리자의 정지는 재등록으로 풀리지 않는다.
- 증거: 원격 시험 결과는 착지 기록을 따른다. 실물 로봇과 현장 Account의 전체 흐름은 확인하지 못했다.
- Gate: 없음. CE: 해당 없음 — 결정된 단계의 구현이다.
