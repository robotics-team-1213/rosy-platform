# Account 서비스 앱 적용 실행 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox tracking. 기존 제품 계약을 읽고 구현하며 최종 독립 계약·증거 리뷰를 수행한다.

**Goal:** 기존 Rosy Account를 모든 적용 앱이 사용하도록 연결하고, 회수·장애·복구를 원격 시험과 배포본 인수로 입증한다.

**Architecture:** D-757의 Fleet auth·SQLite authority와 기존 AccountClient receiver를 재사용한다. D-807의 자격별 책임과 업무 owner 경계를 유지하고, 확인된 누락만 구현한다. 설치·실사용 증거가 없는 앱은 코드 시험 통과와 구분한다.

**Tech Stack:** 기존 Python/FastAPI/SQLite, oauthlib·joserfc·cryptography, 정적 웹, Android Kotlin/Keystore, native systemd와 기존 서명 배포 경로.

**Spec:** [D-807](../adr/D-807-account-service-credential-ownership-and-acceptance.md), [D-757](../adr/D-757-rosy-account-unified-app-sessions.md), [Account protocol](../reference/rosy-account-protocol.md). 본 계획은 [기존 통합 계획](2026-10-14-rosy-account-completion.md)의 잔여 작업을 구체화하며 역사 검증 기록을 대체하지 않는다.

**Status:** 사용자 계획 검토 완료, 현재 세션에서 직접 구현·검증 진행 승인(2026-10-19). 지속 목표는 active다. 설치·실사용 수용은 별도 증거로 판단한다.

## Global Constraints

- 일반 Access Token 최대 300초, 연결된 verifier 회수 최대 30초. D-789의 미디어 60초 자격/lease·1초 원본 재검사·단절 확인 후 5초 실제 종료 및 기존 더 짧은 업무 제한이 우선한다.
- 기본 로그아웃은 현재 family 전체, 정지·초기화·전체 회수는 모든 기기다. 중앙 실패 시 로컬 삭제와 중앙 회수 대기를 구분한다.
- 사람·장치·기계·외부 제공자·업무 위임 자격을 혼용하지 않는다. 관리 권한은 조작 권한을 상속하지 않는다.
- 기존 보호 설정 parser·발급/검증 라이브러리·원격 runner를 사용한다. 새 IdP·provisioning API·범용 비밀 저장소·생성 CLI는 추가하지 않는다.
- 실제 주소·계정·서명 키·채워진 설정은 공개 문서에 넣지 않는다. 기존 비밀번호·프로필·회수 상태를 보존한다.
- 제품 파일은 주제별 비-main worktree에서만 변경한다. main 병합·push·서명 배포·운영 계정 변경은 각 현행 관문과 해당 권한 범위에 따른다.
- pytest는 커밋된 SHA를 원격 시험 PC에서 실행하고 known_failures와 비교한다. 노트북 pytest와 실패 기준선 추가로 우회하지 않는다.
- 인증 확인을 위해 운동 명령이나 E-Stop 해제를 실행하지 않는다. 사용자 본인의 로그인·동의·단말 확인은 에이전트가 대신 통과 처리하지 않는다.

## Review Focus

1. 중앙 회수 실패 뒤 로컬 쿠키가 남거나 UI가 전 앱 로그아웃 완료로 오인시키는 경우: Task 1·2의 HTTP/브라우저 검사.
2. receiver 재시작으로 암호화된 회수 대기열이 사라지거나 다른 사용자에게 재사용되는 경우: Task 1의 재개 검사.
3. 일반 API의 캐시가 유효하다는 이유로 미디어가 중앙 단절 뒤 계속 갱신되는 경우: Task 2의 미디어 endpoint 검사.
4. 다른 앱·로봇·프로젝트의 자격 또는 관리자 역할로 조작을 허용하는 경우: Task 3의 기존 deny 시험과 Task 5의 배포본 인수.
5. 과거 DB·키 복원으로 옛 비밀번호·회수 family·소비한 refresh가 살아나는 경우: Task 5의 격리 복구 readback. 운영 DB에 실험하지 않는다.

## 조사 기준과 적용 목록

출발 커밋 SHA `d1b8daf243f0b2575a3ec7f8c533d05290bd9678`을 기준으로 조사했다. 공통 로그아웃 대기열·CORE 20초 재시도, refresh 회전/replay 회수, media strict online, 웹의 회수 미완료 메시지는 코드에 있다. 이번 조사에서 구현 결함을 확정하지 않았다. 이전 시험 수치는 이번 SHA의 시험 증거가 아니다.

| 표면/서비스 | 기존 연결·owner | 이번 목표 |
|---|---|---|
| console / Account | `operations/fleet/fleet/server/auth`, `operations/site_ui/console` | 관리자·원장·등록 앱·권한 회수 검증, 실제 authority 활성화 |
| robot / pilot web | `middleware/core/api/core_api_web/api/account_sessions.py`, 기존 AccountClient | 로그인 복귀·권한 분리·회수 대기·WS 차단 |
| pilot-shell / cam | 기존 native Account·Gradle 설정·Keystore | 설정 포함 빌드와 실제 단말 callback/회수 구분 |
| pinky-review / Learning | `learning/curation/perception/learning_rosy_accounts.py`, collaboration receiver | subject 매핑·provider 소유·worker 재검증 |
| game-board | `operations/apps/games/games/host/account.py`, `preview.py` | HTTPS 쿠키·Origin·games.operate·회수 재시도 |
| 미디어 서비스 | CORE `media_binding.py`, `operations/site_ui/media` | 원본 권한 strict online과 실제 세션 종료 |
| lane-live-view / Face / web-common / control-diagnostic | 기존 surface 정의 유지 | 읽기 전용·LCD·라이브러리·PARKED 사유 기록. 새 로그인 앱으로 확대하지 않음 |

## Task 1: 공통 receiver의 영속 회수 검사

**Files:** `contracts/foundation/test/test_account_client.py`; 결함이 재현될 때만 `contracts/foundation/core_common/protocol/account_client.py`.

**Interfaces:** 기존 `AccountClient.logout(cookie)`, `retry_revocations()`, 같은 session DB·암호화 키로 receiver 재생성. 새 public API 없음.

- [x] 기존 `test_logout_retries_revocation_after_outage`와 fixture를 읽고 `test_pending_revocation_survives_receiver_reopen`을 추가했다: 중앙 중단→로컬 거부→receiver 재생성→중앙 복구→회수·큐 소진 확인.
- [x] `c22ee485ad`의 원격 suite 15개 통과, skip 0, NEW 0. 기존 구현은 수정하지 않았다.
- [x] 기존 refresh replay·revision·계정 정지 시험은 Task 3에서 재사용해 통과했다.
- [x] 최종 독립 리뷰와 SHA·실행/skip/NEW·로그를 [결과표](../validation/account-service-2026-10-19/results.md)에 기록했다. foundation 변경의 FULL CI/착지 범위는 축소하지 않는다.

## Task 2: CORE HTTP·미디어·브라우저 연결 검증

**Files:** `middleware/core/gateway/test/test_account_pipeline.py`, `test_media_grant_api.py`; 재현한 결함이 있을 때만 `middleware/core/api/core_api_web/api/account_sessions.py`, `media_binding.py` 또는 해당 웹 caller.

**Interfaces:** 기존 `/api/account/logout`, `/api/account/session`, media issue/validate/renew endpoint 및 lifespan. 경로·응답 필드는 Account protocol과 기존 API만 사용한다.

- [x] `test_logout_outage_returns_pending_and_clears_cookie`: 실제 중앙 실패의 503/pending·쿠키 삭제·접근 거부 확인.
- [x] `test_core_lifespan_retries_pending_revocation`: 실제 lifespan 시작이 영속 큐를 재시도하는지 Event로 확인했다. 수동 retry 호출이나 20초 sleep으로 대신하지 않았다.
- [x] `test_account_media_revalidation_denies_authority_outage_and_revocation`: 실제 pipeline에서 일반 캐시와 미디어 strict online 차이를 확인했다. 기존 Authority fixture가 있는 `test_account_pipeline.py`에 두었다.
- [x] 기존 HTTPS browser 시험을 정상/회수 대기 매개변수로 확장했다. 실제 Chromium에서 미완료 안내·프로필 제거·세션 해제를 확인했다.
- [x] 조회 전용 Pilot 차단 화면에 로그아웃이 없음을 RED로 재현하고 수정했다. `41e03f029e`에서 pipeline/media 14개 통과, skip 0, NEW 0. PWA 캐시도 갱신했다.

## Task 3: 앱별 기존 통합 회귀와 결과표

**Files:** 결과는 `docs/validation/account-service-2026-10-19/results.md`에 기록. 앱 코드는 실패가 확인된 owner만 수정한다.

**Interfaces:** `shared/web/surfaces.yaml` 적용 목록과 기존 권한/세션 계약. 결과표는 표면별 `SOURCE / REMOTE TEST / CI / INSTALLED / RUNTIME / USER ACCEPTANCE` 여섯 칸과 명령·host 역할·SHA·로그·skip/NEW를 가진다.

- [x] Fleet: 명시한 단위/원장/설정/관리자·프로필 Chromium 시험을 `41e03f029e`에서 검증했다.
- [x] CORE: Task 1·2와 `test_account_sessions.py`로 자원·권한·WS 경계를 검증했다.
- [x] Games의 기존 preview/권한 시험과 Learning의 명시한 연결/worker·browser 시험을 실행했다. Fleet·Learning·Games·Access 묶음 170개 통과, skip 0, NEW 0. 실제 설치 인수는 별도다.
- [ ] native: 기본 debug 설정으로 Cam JVM 440개·APK, Pilot JVM 111개 중 skip 1개·실패 0·APK를 확인했다. opt-in proxy/Chromium은 별도 실행 통과다. 기존 native fixture 결함 3개를 같은 호스트 기준선에서 재현하고 별도 브랜치로 수정했다. 보호 운영 설정을 포함한 `-Prosy.accountConfig=<protected-public-config>` 빌드·서명·단말 인수는 입력 확인 뒤 Task 4–5에서 수행한다.
- [x] 결과표에 앱별 여섯 관문과 미실행을 구분했다. 한 앱의 성공으로 전 앱 완료를 선언하지 않는다. 기존 변경을 되돌리지 않았다.

## Task 4: 설치 입력과 전환 절차 준비

**Files:** 기존 `deploy/site/README.md`, `docs/reference/rosy-account-protocol.md`의 설치 절차를 참조. 누락된 실행 안내만 같은 owner 문서에 보충한다. 실제 입력·계정 목록은 기존 gitignored private 영역에 둔다.

**Interfaces:** Authority는 기존 `--account-config`, site `ROSY_ACCOUNT_CONFIG`; CORE는 `auth.account_client_file`; Review는 `account_client_file/account_subjects`; Games는 `--preview-account-config`.

- [ ] issuer/TLS 이름·기존 bootstrap 계정·영속 DB·기계 자격·정확한 client/callback/resource·receiver 공개키·세션 암호화 키의 비밀 비노출 설치 목록을 준비한다. 실제 값이 없는 항목은 임의 생성하지 않는다.
  - 현장 보호 폴더에 실제 tailnet issuer·새 site namespace·확인한 기존 관리자·Cam client/callback/resource를 명시한 후보와 키를 준비했다. 기존 parser UID10001 검증과 Caddy adapt, 설정 포함 Cam debug APK/asset 대조는 PASS. private 안내에 실제 관리자 명령을 작성했다. 인증서 발급은 daemon 권한 거부, 정확한 나머지 앱 등록·운영 승인/설치는 대기다. [후속 증거](../validation/account-service-2026-10-19/prepared-activation-candidate.md).
- [x] 기존 `load_account_config`와 `load_account_client`의 시작 시 검증을 재사용하도록 설치 절차에 기록했다. site_preflight는 Account 일관성을 검사하지 않는다고 명시했다. 새 validator/생성 CLI는 추가하지 않았다.
- [ ] 동일 시점 DB/설정 백업과 현재 비밀번호·프로필 보존을 준비하고 verifier 호환 배포→authority→앱 receiver→기존 사람 경로 종료 순서로 전환안을 만든다.
- [ ] 기존 서명 candidate·서비스 관문에 넣을 구체적 변경·readback·복구 절차가 준비된 뒤에만 운영 전환을 수행한다. source 검증만으로 운영 재시작을 실행하지 않는다.

## Task 5: 배포본 인수와 최종 판정

**Files:** Task 3의 결과표에 배포 SHA·설치/runtime·실사용 결과를 추가한다. 기존 배포·장치 절차를 따른다.

**Interfaces:** 운영자는 기존 배포 경로, 사용자/관리자는 본인의 인증·동의·단말을 사용한다. 업무 완료는 해당 owner의 영속 결과로 확인한다.

- [ ] 실제 관리자·사용자로 로그인→앱 자동 복귀→허용/거부→영속 결과 재조회→로그아웃/정지를 수행한다. 본인 비밀번호·provider 동의·native callback 검증을 대신 완료하지 않는다.
- [ ] 열린 REST/WS/native/worker의 회수와 일반 30초·5분 경계, D-789의 더 엄격한 미디어 경계를 별도 계측한다. 실제 미디어 연결 종료를 HTTP 시험으로 대체하지 않는다.
- [ ] 격리한 DB·키 복사본에서 재시작·키 교체·복구를 검증한다. 정지 계정·옛 비밀번호·family·소비한 refresh가 살아나지 않는지 readback한다. 운영 DB를 옛 백업으로 덮어쓰지 않는다.
- [ ] 모든 적용 행의 미완료/skip과 운영 의존 조건을 정리한다. source와 원격 검증이 끝나도 설치·실사용 미확인 행이 남으면 지속 목표를 완료로 바꾸지 않는다.

## 원격 검증 명령과 완료 조건

각 task는 먼저 자기 파일을 커밋한다. 아래 `<task-sha>`, `<external-log-dir>`, `<owned-test-paths>`는 해당 task의 실제 값으로 바꾼다. 예제에 실주소·계정을 넣지 않는다.

```powershell
python tools/harness/rosy_harness.py affected --base <task-base-sha>
python tools/remote/remote_pytest.py --sha <task-sha> --log-dir <external-log-dir> -- <owned-test-paths> -q
python test/known_failures.py <external-log-dir>/run-1.txt
python tools/remote/remote_pytest.py --sha <task-sha> --log-dir <browser-log-dir> -- ROSY_RUN_BROWSER_TESTS=1 middleware/core/gateway/test/test_account_pipeline.py -q
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
```

Task 1의 owned paths는 `contracts/foundation/test/test_account_client.py`, Task 2는 `middleware/core/gateway/test/test_account_pipeline.py middleware/core/gateway/test/test_media_grant_api.py`다. Task 3은 위 앱별 경로를 owner별 invocation으로 분리한다. 동명 basename suite를 한 invocation에 섞지 않는다. 명령 exit 0·실제 수집/실행·NEW 0을 확인하고 skip 사유를 함께 기록한다.

## 실행 순서와 상태

`계획 검토 → Task 1 → Task 2 → Task 3 → Task 4의 구체적 전환안 → Task 5`.
구현은 현재 세션에서 직접 수행하고 마지막에 독립 계약·증거 리뷰를 받는 방식을 권장한다.
공통 기능은 이미 있어 모듈마다 새 구현 에이전트를 돌리기보다 검증과 실제 누락 수정에 집중한다.
계획을 읽고 확인하는 절차가 끝나기 전에는 제품 구현을 시작하지 않는다.

- [x] 지속 목표 등록, D-807·기존 코드·적용 목록 조사.
- [x] 계약 검토와 운영 증거 검토 의견을 반영해 실행 계획 작성.
- [x] 작성된 계획 검토 및 실행 방식 확정: 사용자 승인, 현재 세션 직접 실행.
- [ ] Task 1–3 소스/원격 시험과 독립 리뷰는 기록했다. 운영 설정 포함 native 빌드는 입력 확인 대기다.
- [ ] Task 4–5 설치·전환·실사용 수용. 실제 배포 입력과 운영 권한이 필요한 부분은 별도 증거로 추적.
