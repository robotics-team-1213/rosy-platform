# 공통 서비스 카탈로그

새 기능을 어디에 둘지 정할 때 이 문서를 먼저 본다. 공통 서비스는 여러 제품 앱이나 현장 전체에 같은 기능을 제공하고, 특정 앱의 업무 원장을 소유하지 않으며, 장치 명령 권한이 없다([D-987](../adr/D-987-common-services-catalog.md)).

여기 적혔다고 배포되거나 수용된 것은 아니다. 현재 상태는 각 모듈의 `progress.md`와 [STATUS](../../STATUS.md)에서 확인한다.

통합관제 R과 같은 호스트에서 실행해도 공통 서비스는 R이나 장치 owner가 되지 않는다. R·셀 관제·CORE·OMX owner·기명 운영자의 책임 구분은 [D-994](../adr/D-994-n100-integrated-control-host-and-owner-boundaries.md), 현재·목표 호스트는 [관제 단위 배치표](../deployment/control-units.md#현장-배치표)를 따른다.

## 실행 서비스

자기 프로세스로 돌고 현장 Compose 서비스로 배치된다.

| 이름 | 소스 | Compose 서비스 | 맡는 것 | 맡지 않는 것 | 계약 | 결정 |
|---|---|---|---|---|---|---|
| Account | `operations/account` | `account`, `account-backup`, `account-backup-check` | 사람 신원·로그인 수단·권한·세션·회수·프로필 | 기계·장치·서비스 자격, 장치 admission, 조종 좌석, 앱별 허용 판단 | [Account 프로토콜](rosy-account-protocol.md) | D-757, D-807, D-962 |
| Monitoring | `operations/monitoring` | `monitoring` | 상태 수집·집계·읽기 API | 명령, host 복구 | [Monitoring API](rosy-monitoring-api.md) | D-876, D-936 |
| Media | `operations/site_ui/media` | `media`, `media-gateway` | 영상 세션 권한, 시청 요청, 미디어 프로세스 관리 | Fleet 영상 중계, 로봇 제어, CORE 장기 자격 수신 | [D-789](../adr/D-789-six-robot-webrtc-camera-transport.md) | D-789, D-801 |
| 현장 입구 | `deploy/site` | `proxy` | TLS 입구와 경로 전달 | 업무 판단, 계정 원장 | [site 배포 안내](../../deploy/site/README.md) | D-301, D-441 |

Account의 로그인·프로필·관리 화면 소스는 `applications/fleet/web`에, Monitoring 화면 소스는 `applications/monitoring`에 있다.

## 공용 코드

자기 프로세스가 없다. 소비자와 함께 설치·컴파일되고, 수용은 그것을 싣는 런타임 모듈이 판정한다.

| 이름 | 소스 | 맡는 것 | 맡지 않는 것 | 결정 |
|---|---|---|---|---|
| Foundation | `contracts/foundation` | 프로토콜 스키마, 공유 계약, Account 클라이언트, 설정 불러오기 | 업무 절차, 산출물 저장 정책 | D-18, D-757, D-841 |
| 웹 공용 | `shared/web` | 디자인·컨트롤·통신 도구, 브라우저 세션 도구 | 사용자 업무, 전역 인증 상태 | D-939 |
| Android 공용 | `shared/android` | 피어 서명·TLS 고정·키 보관 도구, Account 세션 | 승인·자격 발급·명령 권한, 앱별 운전 세션, 카메라 자격 | D-939, D-987 |

## 공통 서비스가 아닌 현장 서비스

| Compose 서비스 | 이유 |
|---|---|
| `fleet` | 현장 조정과 Mission 원장을 소유한다 |
| `fleet-backup` | Fleet 상태의 백업이다 |
| `postgres` | Fleet만 쓰는 파생 문맥·로그 저장소다 |
| `vision` | 천장 영상에서 현장 관측을 만드는 업무 생산자다 |
| `control-unit-peer` | 관제 계층 연결에만 쓰는 peer 프록시다(D-850, D-960) |

## 기능별 공통화 결정

아래는 [D-997](../adr/D-997-common-function-ownership-and-failure-contracts.md)의 확정 설계다. 위 실행 서비스·Compose 목록과 달리 구현·배포 목록이 아니다. 기존 owner·프로세스·DB·폴더·자격·API는 실제 전환 검증 전까지 유지한다. 현재 소스는 이 저장소의 실제 경로를 기능별 대표로 적는다. `(목표, 미생성)`은 D-997이 정한 전환 뒤 경로가 아직 만들어지지 않았다는 뜻이다. `test/architecture/test_common_services.py`가 경로 존재와 목표 표시를 확인한다.

| 기능 | 확정한 형태 | 현재 소스 | 책임 경계 |
|---|---|---|---|
| 계정·권한 | 독립 Account | `operations/account`(Account) | 사람 신원·세션·회수, 기계 자격·업무 admission은 별도 |
| 등록·앱 목록 | 기존 Account 연동 등록부·장치/서비스 owner + 공통 조회 | `operations/account/rosy_account/account_authority.py`(Account 연동 등록부), `operations/fleet/fleet/server/auth`(Fleet 장치·서비스 등록), `contracts/foundation/core_common/protocol/account_client.py`(공통 조회 client) | 발견·접속 정보와 신뢰·기계 자격·장치 역할을 구별. 범용 Registry 서버 신설 없음 |
| 설정 | 공용 검증/transaction 코드 + owner 저장·적용 | `contracts/foundation/core_common/config.py`, `contracts/foundation/core_common/config_transaction.py`(공용 코드) | 중앙 Config DB·쓰기 서비스 신설 없음 |
| 알림 | 독립 알림 전달 서비스로 추출하는 목표 | `operations/fleet/fleet/incidents/notifications.py`(현재 발송 owner: Fleet), `operations/notifications`(목표, 미생성) | 현재 발송은 Fleet 소유. 첫 생산자는 Fleet 사건·Harbor 업무 HOLD. 원본 outbox·발송 직전 owner 확인·중복·UNKNOWN·단일 발송자 검증 뒤 전환 |
| 감사 | owner 원본 + 공통 사건/수집·조회 | `operations/account/rosy_account/audit.py`(Account 원본 감사) | 중앙 Audit DB를 모든 쓰기의 필수 경로로 만들지 않음 |
| 백업·복원 | 공통 도구·검증/receipt + owner 실행 어댑터 | `deploy/site/site_db.py`(공용 스크립트, 기본은 Fleet data volume; account 백업도 같은 스크립트를 자기 DB로 실행), `deploy/site/compose.account-backup.yaml`(Account 백업·검증 서비스 owner) | 모든 볼륨·키·임의 경로를 가진 중앙 복구 서비스 신설 없음 |
| 업데이트 | 공통 상태·검증 규약 + 배포 계열별 실행 | `deploy/site/rosy_site_autoupdate.py`(site), `deploy/robot/pinky_pro/release/updater.py`(Pinky payload), `deploy/robot/omx/omx_autoupdate.py`(OMX) | 서명·hold·활성화·재기동·rollback 권한은 기존 owner |

Monitoring은 허용된 상태·읽기 사본, Media는 영상 세션·위임·프로세스 관리를 유지한다. Fleet·World·Decision·CORE·OMX와 Harbor의 원장·판단·실행은 공통화 대상이 아니다. 기능별 실패·복구·전환·검증 조건은 D-997이 정본이다.

## 기계 처리 공용화 조사

후속 추출은 아래 실제 구현을 먼저 대조한다. 동일한 이름보다 입력·오류·수명과 설치 묶음이 같은지 확인한다.

| 후보 | 확인한 구현과 처리 |
|---|---|
| 감사·기록의 비밀 필드 | `fleet/observe/events.py`와 `fleet/server/ledger/task_payloads.py`의 동일한 필드 이름 정규식만 `core_common.audit_fields.is_credential_field`로 추출했다. 재귀 범위·PEM 값 검사·오류·JSON 인코딩·보관은 각 owner에 남는다. `learning/curation/pinky/fleet_observations.py`는 CLI에서 파일로 직접 실행되고 별도 설치 패키지가 아니며 foundation 경로를 설정하지 않으므로 자체 검사식을 유지한다. 완전한 마스킹이나 새 사건 schema가 아니다 |
| Account·admission 감사 | `rosy_account/audit.py`는 HTTP 요청 메타데이터, `policy_admission_audit.py`는 정책 판정·scope revision을 기록한다. actor·correlation·revision 의미가 달라 사건 형식을 합치지 않았다 |
| 백업·복원 | Account와 Fleet은 이미 `deploy/site/site_db.py`의 무결성·해시·결과 형식을 함께 쓴다. 검수의 `qwen_review_completion.py`는 병합 전 DB 사본과 mask 버전 receipt이고 Account `migration.py`는 자격 이관 검증이다. 같은 백업·복원 계약으로 합치지 않았다 |
| 업데이트 | site updater는 candidate commit·switch journal·건강/rollback, Pinky `auto_update_records.py`는 release identity·hold·적용 결과를 소유한다. `tools/remote/update_status.py`는 설치 unit·이미지·파일 drift 조회다. 서로 다른 상태를 공통 updater나 성공 enum으로 바꾸지 않았다 |
| 설정 | `core_common.config`는 기존 transaction을 쓴다. overhead `track/tuning.py`의 실패 시 경고하는 이력과 `background_blob.py`의 fsync·실패 전파 snapshot은 설정 revision transaction과 의미가 달라 원자적 교체를 합치지 않았다 |

새 foundation 모듈은 기존 `setup.py`의 패키지 자동 검색에 포함되며 Fleet은 이미 `core_common`을 의존한다. 새 프로세스·DB·HTTP 계약·배포 변경은 없다.

## 새 기능을 넣을 때

1. 한 앱만 쓰면 그 앱에 둔다. 나중에 쓸지도 모른다는 이유로 옮기지 않는다.
2. 둘 이상의 앱이 같은 코드를 쓰면 공용 코드 위치에 둔다. 전역 utils 패키지는 만들지 않는다.
3. 자기 데이터와 수명이 필요하면 실행 서비스로 제안하고 ADR을 쓴다.
4. 현장 Compose에 서비스를 더하면 위 표 중 하나에 적는다. `test/architecture/test_common_services.py`가 확인한다.
5. 이름이 같아도 의미가 다르면 합치지 않는다. 사람 자격과 기계 자격을 합치지 않는다.
