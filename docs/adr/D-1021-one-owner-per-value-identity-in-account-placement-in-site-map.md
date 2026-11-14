## D-1021 ROSY 공통: 값마다 소유자 하나, 신원은 Account, 배치는 비공개 현장 배치 지도

**Status:** Accepted (2026-11-13, 사용자 승인; 패널 3인 검토 결과를 반영한 공통 구조 결정)

잇는 결정: [D-987](D-987-common-services-catalog.md)(공통 서비스 분류) · [D-1001](D-1001-common-logic-placement-on-r.md)(R의 공통 서비스 배치) · [D-992](D-992-device-enrollment-account-link.md)(로봇의 `auth.account_trust`) · [D-859](D-859-shared-utc-time-synchronization.md)·[D-861](D-861-one-identical-ntp-endpoint-for-all-devices.md)(현장 시간 서버 하나) · [D-805](D-805-host-update-channels-and-site-freeze.md)(업데이트 채널) · [D-852](D-852-lab-pc-user-service-inventory.md)(유닛 목록)

### Context

2026-11-13 모델 PC의 Learning 앱 로그인이 `account_callback_failed`로 돌아왔다. 원인은 둘이 겹쳤다. 모델 PC 시계가 R보다 약 4초 늦어 `iat` 검사에서 토큰이 거부됐고, 모델 PC의 chrony가 2026-11-09 호스트 이름 변경으로 사라진 옛 tailnet 이름을 시간원으로 가리켜 시간원이 0개였다. 같은 날 옛 이름을 가리키는 설정 때문에 장애가 네 번 났다. 같은 사실(발급자, 키, 앱 목록, 시간 서버, 서비스 위치)의 사본이 앱마다 따로 있고, 바뀌었는지 보는 곳이 없었다. 상세와 직접 수정은 [교훈 기록](../solutions/runtime-errors/clock-skew-rejected-account-tokens-after-time-source-name-vanished-2026-11-13.md)이다.

처음에는 Account가 신원 문서 하나를 내주는 안(Proposed)이었다. 패널 검토에서 새 문서·새 신뢰 뿌리는 이득보다 부담이 크고, 기존 `GET /api/fleet/auth/keys`와 `/apps`가 이미 같은 일을 한다는 결론이 나와 구조를 바꿨다.

### Decision

**1. 다섯 층과 구성원.** 값은 아래 한 층에만 산다. 다른 곳의 사본은 배포 단계가 쓰거나 점검이 대조한다.

| 층 | 구성원 |
|---|---|
| 신원 | 발급자, 서명 공개 키, 클라이언트(앱) 등록부, 계약 버전 |
| 배치 | 호스트 이름·별칭, 시간원, 서비스 주소, 은퇴한 이름 |
| 유닛 | 호스트별 systemd 유닛과 코드 출처 |
| 접근 | SSH 목적지·역할 표(`lab-hosts.json`) |
| 기대 버전 | 서명된 후보와 보류(hold) 기록 |

**2. 정본 표.**

| 값 | 정본 | 사본 |
|---|---|---|
| 신원(발급자·키·클라이언트) | Account(`authority.json`의 발급자·키, Account DB의 클라이언트 등록부). JSON 클라이언트 파일은 DB를 처음 채우는 용도뿐 | 앱별 `receiver.json`, Fleet·CORE 수신 설정 |
| 배치(시간원·별칭·은퇴 이름) | `private/site-map.yaml`(공개 저장소에 두지 않는다, D-226) | 호스트의 chrony·`/etc/hosts`·앱 설정 |
| 유닛 | `deploy/hosts/services.yaml` | 호스트에 설치된 유닛 |
| SSH 접근 | `private/lab-hosts.json`은 `site-map.yaml`의 SSH 사본이다 | 도구의 호스트 목록 |
| 기대 버전 | 서명된 후보(`release.json`)와 보류 기록 | 실행 중 컨테이너 |

**3. 런타임 전달.** 시간원과 서비스 주소는 배포 단계가 쓰고 `update_status`가 대조한다. 키와 앱 목록은 기존 `GET /api/fleet/auth/keys`와 `/apps`가 이미 전한다. **신원 문서, 새 PKI, 푸시 데몬, 중앙 설정 DB, mDNS 자동 재설정은 만들지 않는다.** APK에 구운 발급자(Cam·Pilot)는 갱신할 수 없으므로 발급자 이름 변경에는 재빌드 표시가 있어야 한다.

**4. 변경 절차.** R 변경의 최종 책임자는 현장 배포 소유자이며 지금은 사용자(GitHub `livsbittt`)다. 에이전트 세션은 실행만 한다. R에 직접 바꾸는 모든 변경은 만료가 있는 보류 하나, 또는 날짜가 있는 변경 기록 하나를 갖는다. 기록은 소유자·세션·대상·만료·후보 SHA·수용 기준을 적고 소유자가 닫는다. 닫는 조건은 옛 값이 모든 호스트에서 0개임을 `update_status`가 보이는 것이다.

**5. 완료 정의: 착지(landed) · 게시(published) · 실행(running) · 수용(accepted).** 착지만 된 것을 완료로 보고하지 않는다. 실행과 드리프트는 `tools/remote/update_status.py`에서 본다.

**6. 책임표.**

| 구성원 | 책임자 | 실패 계약 | 가장 싼 시험 | 감시 |
|---|---|---|---|---|
| 발급자·키·앱 | Account 소유자 | 키가 바뀌면 옛 키만 가진 수신기가 로그인 실패 | Account 30분 로그인 점검 | `account-login-check`, `account-key-drift` |
| 시간원 | 현장 배포 소유자 | 시간원 0개면 시계가 어긋남 | `chronyc sources` | `update_status` chrony FAIL |
| 은퇴한 이름 | 현장 배포 소유자 | 옛 이름이 설정에 남으면 서비스 중단 | 설정 파일 검색 | `retired-name` |
| 유닛 | 호스트 소유자 | 선언과 설치 불일치 | `update_status` | DRIFT·MISSING·DOWN |
| 실행 이미지 | 현장 배포 소유자 | 기록 없는 이미지가 R에서 돈다 | R 자동 갱신의 설치 검증기가 실행 이미지를 서명 후보와 대조(갱신 주기마다) | `site-autoupdate: last run refused` |
| 보류 | 현장 배포 소유자 | 만료 없는 보류가 갱신을 막는다 | `until` 검사 | `site-autoupdate` FAIL |
| R 감시자 | 현장 배포 소유자 | R의 guard가 멈추면 아무도 모른다 | 타이머·status.json 시각 | `host-guard` |

### 이 브랜치에서 구현한 것

- `tools/remote/update_drift.py`와 `update_status.py`: 은퇴 이름을 공개 저장소가 아니라 비공개 지도(`retired_hostnames:`)에서 읽음, 수신기·Fleet `client.json` 키 `FAIL account-key-drift <경로>`(이름만, 키 자료는 출력하지 않음; https가 아닌 issuer와 키를 받아 오지 못한 경우도 FAIL), R guard 타이머·status.json 시각 `FAIL host-guard`.
- 보류 만료, 거부 사유, 30분 Account 로그인 점검 유닛, chrony 시간원 점검, 10초 시계 여유와 `clock_skew` 로그는 별도 변경이다(교훈 기록).
- 구현하지 않은 것: 모델 PC 쪽의 R guard 감시자(역방향 guard, 아래), APK 재빌드 표시, 변경 기록 양식 자동 검사.

### Consequences

- 키 회전·앱 추가는 Account 한 곳, 호스트 이름 변경은 지도 한 곳의 변경이고 나머지는 점검이 어긋남을 잡는다.
- 이 결정은 새 서비스·새 신뢰 뿌리를 만들지 않아 D-987·D-997 구조를 그대로 둔다.
- R guard 감시는 `update_status` 실행 시점에만 보인다. 모델 PC가 스스로 R의 guard 정지를 알리는 역방향 감시자는 아직 없다(후속).
- `update_status`는 비공개 지도가 이 노트북에 있어야 은퇴 이름을 검사한다. 없으면 검사를 건너뛴다고 한 줄 알린다.
