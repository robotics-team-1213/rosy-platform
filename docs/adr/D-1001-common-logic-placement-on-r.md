## D-1001 공통 로직은 R의 서명된 rosy-site 스택에서 서비스별 독립 컨테이너로 돌리고, 기계 자격·안전 권한은 Fleet에 남긴다

**Status:** Accepted (2026-11-09, 사용자 승인: 초안 그대로 수락; 내장 Account 모드는 연동 브랜치가 착지하고 R에 배포된 뒤 제거; 알림 전달기는 Monitoring 전용 이미지 분리 뒤 나중에 전달 전용·자기 이미지로). Architect·Critic 토론을 거쳤다. 이 변경은 문서와 구조 시험만 바꾼다. 배포·이미지·compose·DB·자격·장치 수용은 바꾸지 않는다.

잇는 결정: [D-987](D-987-common-services-catalog.md)(분류) · [D-997](D-997-common-function-ownership-and-failure-contracts.md)(기능별 소유·장애 계약) · [D-994](D-994-n100-integrated-control-host-and-owner-boundaries.md)(R 호스트) · [D-807](D-807-account-service-credential-ownership-and-acceptance.md)(사람·기계 자격 분리) · [D-955](D-955-rosy-hub-team-grants.md)(Account 연동)

### Context

D-997은 공통 기능을 실행 서비스·공용 코드·owner 어댑터로 나누고 기능별 소유자를 정했다. 그러나 "어느 호스트의 어느 컨테이너에서 도는가"와 "Fleet 안에 남는 것은 무엇이고 왜인가"는 기능마다 흩어져 있어, 새 공통 기능이 Fleet 프로세스에 들어가도 막는 곳이 없다. 2026-11-09 R(`rosy-fleet-r`)의 실제 구성은 다음이다.

- 서명 release의 compose 프로젝트 `rosy-site`: `proxy`, `fleet`, `account`, `monitoring`, `postgres`, `vision`, `control-unit-peer`. Fleet은 Account 수신기(receiver) 모드이고 Account는 자기 이미지(`rosy-site-account`)·상태 볼륨·메모리 256m의 독립 컨테이너다.
- `monitoring`은 독립 프로세스·상태이지만 Fleet 이미지(`rosy-site-fleet`)를 쓴다. `fleet`·`vision`·`postgres`에는 `mem_limit`가 없다.
- Media(`rosy-media` 별도 프로젝트)는 R에서 돌지 않는다.
- Fleet 소스 안에 남은 공통 성격 코드: Account 호환 껍데기 8개(`fleet/server/auth/{account_authority,account_authority_routes,account_config,account_ledger,account_routes,password_routes,password_session,site_users}.py`, 각 4–6줄 재수출), 내장 Account 모드 조립(`account_runtime.py`), 카메라 페어링(`pairing*.py`)·로봇 등록(`enrollment*.py`), 비전 미리보기 grant 서명 연결(`tracking/vision_preview_routes.py`), host-control(`host_control.py`), 알림 outbox(`incidents/notifications.py`).

### 토론 요약

| 쟁점 | Architect | Critic | 결론 |
|---|---|---|---|
| Monitoring이 Fleet 이미지 | 그대로 둔다 | Fleet 이미지 결함이 관측자까지 함께 죽이므로 전용 이미지 | Critic 채택. 한시 예외로 적고 새 예외를 시험으로 막는다 |
| 알림 전달 컨테이너 | Fleet 이미지로 먼저 | outbox·판단이 Fleet에 남으면 분리해도 격리가 없다 | D-997 계약(전달기만 분리, owner 확인)대로 가되 Fleet 이미지 금지. 착수는 Monitoring 전용 이미지 뒤, 사용자 결정 |
| 내장 Account 모드 | 나중에 제거 | 껍데기가 이미 얇으니 지금 제거 | 운영 모드는 receiver뿐으로 확정. 제거 변경은 별도 단계(아래 3). 수신기와 내장 동시 설정 거부는 이미 있다(`account_runtime.py`) |
| 별도 core 프로젝트·호스트(B) | 측정된 계기가 있을 때 | 비용이 낮으니 지금 | 지금은 채택하지 않는다. 계기를 수치로 정한다(결정 2) |
| 페어링·등록·미리보기 서명 | Fleet 유지 | 페어링 흐름만은 쪼갤 수 있다 | Fleet 유지. 흐름 끝이 Fleet DB의 기계 자격 digest 발급이라 쪼개면 발급 권한이 둘이 된다 |
| Fleet·Vision 자원 한도 | (언급 없음) | 한도가 없어 256m 컨테이너를 밀어낼 수 있다 | 규칙은 지금 확정, 값은 D-994 §5의 24시간 측정 뒤. 그동안 부채 목록으로 고정 |

### Decision

1. **기본 배치.** 공통 실행 서비스(Account·Monitoring·알림 전달기·TLS 입구)는 R 호스트의 서명된 `rosy-site` 프로젝트 안에서 서비스마다 자기 컨테이너·이미지·상태 볼륨·메모리 한도를 갖는다. Fleet 프로세스 안으로 들이지 않고, Fleet 이미지를 빌려 쓰지 않는다. R 호스트에 둔다고 R이나 Fleet이 공통 서비스의 owner가 되지 않는다(D-994 §4).
2. **별도 core 프로젝트·호스트(B)는 지금 두지 않는다.** 한 호스트·한 프로젝트라는 같은 장애 영역이 비용이다. 이를 더 쪼갤 계기는 다음 중 하나가 측정될 때다: Fleet 배포·재시작 중 Account 로그인 불가가 60초를 넘는다 / R 호스트 단절 시에도 로그인이 필요하다는 운영 요구가 생긴다. 계기가 생기면 새 ADR로 `rosy-core` 프로젝트(전용 유닛·갱신·롤백·방화벽)를 정한다. Media는 이미 D-789 T5의 별도 프로젝트 `rosy-media`이며 R 배치는 D-994 §5 부하 관측과 방화벽 단계 뒤에 한다.
3. **Fleet은 공통 사람 신원의 소비자뿐이다.** 운영 모드는 Account 수신기이며 내장 Account(`PasswordSessions`·`AccountAuthority` 조립)는 새 사이트에 쓰지 않는다. 내장 모드와 껍데기의 제거는 (a) 연동 브랜치(D-990·D-992·등록부·앱 목록)가 main에 들어가고 (b) 모든 운영 호스트가 receiver로 확인된 뒤 별도 변경으로 한다. 이는 D-955·목표 파일이 "범위 밖"으로 둔 항목을 재결정한 것으로, 이유는 껍데기가 이미 재수출뿐이고 수신기와 내장 동시 설정이 거부돼 되돌림 위험이 작기 때문이다. Account DB 이전 잠금은 그대로다.
4. **Fleet에 남는 것과 이유.**

   | 기능 | 위치 | 이유 |
   |---|---|---|
   | 카메라 페어링·로봇 등록·기계 자격 digest | Fleet | 끝이 admission(D-302)이며 사람 자격과 합치지 않는다(D-807). 발급 권한을 둘로 나누지 않는다 |
   | 비전 미리보기 grant 서명 사용 | Fleet | 서명 코드는 `core_common`의 공용이다. 비밀은 다른 모든 자격과 달라야 해 발급 owner인 Fleet이 쥔다 |
   | host-control 소켓·업데이트·host guard | 호스트 systemd와 Fleet | 호스트 권한이다. 공통 컨테이너에 소켓을 주지 않는다 |
   | 알림 outbox·판단·최종 검토 | Fleet | D-661·D-997 §6. 전달기만 분리 대상 |
   | 감사 원본·백업 실행 | 각 owner | D-997 §7·§8 |
   | CORE `/cmd_vel`·OMX joint/action·정지·deadman | 로봇·셀 | D-430. 중앙 서비스는 이 경로에 없다 |

5. **자원.** 공통 컨테이너는 `read_only`, `cap_drop: [ALL]`, `no-new-privileges`, `mem_limit`를 갖는다. 현재 한도가 없는 서비스는 시험의 부채 목록에 고정하고, 값은 D-994 §5의 24시간 관측으로 정한다. 부채 목록은 줄이기만 한다.
6. **서명 이미지.** R에는 서명된 이미지만 올린다(D-994). 새 공통 서비스는 후보 빌드(`build_candidate.py`)에 자기 이미지와 Caddy 해시 표지를 함께 등록한다. 서명되지 않은 overlay를 R에 두지 않는다.

### 이행 순서와 되돌리기

각 단계는 별도 변경이며 문서 수락만으로 통과하지 않는다. 실제 배포는 D-868·D-994의 서명·hold 절차를 따른다.

| # | 단계 | 되돌리기 |
|---|---|---|
| 1 | 이 ADR의 구조 시험(`test/architecture/test_common_placement.py`)과 카탈로그 「배치와 장애 격리」 (이번 변경) | 시험·문서 되돌림 |
| 2 | Monitoring 전용 이미지 `rosy-site-monitoring`(fleet 패키지 없음). 후보 빌드·compose 한 줄·시험의 예외 제거 | compose 이미지를 Fleet 이미지로 되돌림(데이터는 `monitoring_state` 그대로) |
| 3 | 연동 브랜치 착지 뒤 내장 Account 모드·껍데기 제거 | 해당 커밋 revert. receiver 설정은 그대로 |
| 4 | Fleet·Vision·Postgres `mem_limit`: 24시간 측정 뒤 값 결정 | 한도 제거 |
| 5 | 알림 전달기(D-997 §6·D-998): 전용 이미지·발송 꺼짐 상태로 배치 → Fleet 발송 끔 → 전달기 켬. 두 발송기를 동시에 켜지 않고 UNKNOWN을 보존 | 발송 owner를 Fleet으로 되돌림. outbox 그대로 |
| 6 | Media를 R에 `rosy-media`로 배치(부하·방화벽 확인 뒤) | `docker compose -p rosy-media down` |

### 시험으로 강제하는 것

`test/architecture/test_common_placement.py`: 공통 컨테이너의 하드닝, Fleet 상태·소켓 마운트 금지, Fleet 이미지 사용자 목록 고정, `mem_limit` 부채가 줄기만 함, Media 네트워크 분리, Fleet의 Account 껍데기 8개가 재수출뿐임, 페어링·등록 코드가 `rosy_account`를 가져오지 않음(D-807), Account·Monitoring 소스가 `fleet`를 가져오지 않음. 카탈로그 시험(`test_common_services.py`)은 서비스 분류를 계속 확인한다.

### 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-427 | source holder·폴더를 이동하지 않는다. 새 최상위 폴더 없음 |
| D-429 | Fleet 원장·admission, CORE 최종 명령, OMX owner를 유지한다 |
| D-430 | 안전 경로를 중앙 서비스에 두지 않는다. 안전 태그 경로를 바꾸지 않는다 |
| D-807·D-955 | 사람·기계 자격 분리를 시험으로 고정한다. "Fleet 내장 Account 제거"의 범위 밖 지정을 결정 3으로 재결정한다 |
| D-962·D-936 | Account 독립 이미지를 유지하고 Monitoring 동반 배포(Fleet 이미지)를 한시 예외로 낮춘다 |
| D-994·D-997 | R 구성과 기능별 계약을 호스트·컨테이너 수준으로 구체화한다. 설치·부하·현장 수용을 소급 승인하지 않는다 |
| D-789·D-801 | Media의 별도 프로젝트·위임 경계를 유지한다 |

### Consequences and evidence

새 공통 기능이 Fleet 프로세스·Fleet 이미지·Fleet 상태 위에 얹히면 구조 시험이 실패하므로 위치를 먼저 ADR로 정하게 된다. 비용은 Monitoring 전용 이미지와 알림 전달기마다 서명 후보 항목이 늘고 N150(16GB)의 메모리를 쓴다는 점이며, 값은 24시간 관측 전에는 확정하지 않는다. 한 호스트라는 장애 영역은 남는다. Account 로그인은 R 단절과 함께 닫힌다(D-997 §3: 안전 정지·deadman은 중앙 연결에 의존하지 않는다).

근거: `deploy/site/compose*.yaml` 실제 구성, `operations/fleet/fleet/server/auth/` 소스, 카탈로그, 두 에이전트 토론 기록. 구조 시험은 원격 시험 결과를 해당 SHA에 연결한다. 이 ADR은 배포·실물 수용이 아니다.
