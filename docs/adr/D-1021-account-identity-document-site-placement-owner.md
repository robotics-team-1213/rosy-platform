## D-1021 Account는 신원 문서 하나만 내주고, 배치 정보는 현장 배치 소유자가 갖는다

**Status:** Proposed (2026-11-13, 사용자 요청 "시계 어긋남 사건의 재발 방지 구조". 구현 없음, 승인 전에는 아무 앱도 바꾸지 않는다)

잇는 결정: [D-987](D-987-common-services-catalog.md)(공통 서비스 분류) · [D-1001](D-1001-common-logic-placement-on-r.md)(R의 공통 서비스 배치) · [D-992](D-992-device-enrollment-account-link.md)(로봇의 `auth.account_trust`) · [D-859](D-859-shared-utc-time-synchronization.md)·[D-861](D-861-one-identical-ntp-endpoint-for-all-devices.md)(현장 시간 서버 하나)

### Context

2026-11-13 모델 PC의 Learning 웹 앱(9444–9448) 로그인이 `/accounts?error=account_callback_failed`로 돌아왔다. Account는 토큰을 정상 발급했다. 원인은 둘이 겹친 것이다.

1. 모델 PC 시계가 R 호스트보다 약 4초 늦었다. `verify_access`는 `iat <= now < exp`를 여유 없이 검사해 "미래에 발급된" 토큰을 거부했다. 실패는 `ValueError`로 삼켜져 로그에 남지 않았다.
2. 모델 PC의 chrony 클라이언트는 `robttt-15z95n-gp7ql.tailb4b84d.ts.net`을 시간원으로 가리켰다. 2026-11-09 호스트 이름 변경으로 이 이름이 사라져 시간원이 0개였고, R 호스트에는 D-859의 현장 시간 서버 역할이 설치된 적이 없었다.

같은 사실(발급자 주소, 서명 키, 앱 목록, 시간 서버 이름, 공통 서비스 위치)의 사본이 앱마다 따로 있고, 호스트 이름이 바뀌어도 이 사본들을 한곳에서 고칠 수 없다. 확인한 사본은 다음과 같다.

| 사본 | 위치 | 담는 사실 |
|---|---|---|
| 수신 설정 `receiver.json` | 모델 PC의 웹 앱 5개 각각 | 발급자, 콜백, 공개 키 |
| `ROSY_FLEET_ACCOUNT_CLIENT_CONFIG` | Fleet 환경 변수가 가리키는 수신 JSON | 발급자, 콜백, 공개 키 |
| `auth.account_client_file`, `auth.account_trust` | CORE 설정과 SD 묶음의 `fleet.account_trust`(D-992) | 발급자, 공개 키 해시 |
| `--preview-account-config` | Games | 발급자, 키 |
| `account-config.json` | Android APK에 구워 넣음 | 발급자, 앱 목록 |
| chrony `server` 줄 | 호스트마다, Pinky는 SD 묶음의 `fleet.time_source` | 시간 서버 이름 |

### Decision (제안)

패널 검토(Codex·Claude 2라운드, 2026-11-13)로 처음 제안을 둘로 나눴다. Account는 신원만, 배치 정보는 현장 배치 소유자가 가진다.

1. **Account는 신원 문서 하나만 내준다.** 내용은 발급자, 서명 공개 키(회전 중이면 둘), 클라이언트 등록부(앱 목록), Account 계약 버전이다. 읽기 전용이고 비밀이 없다. 정본은 Account의 기존 등록부이며 새 원장·서비스는 없다(D-987, D-997).
2. **배치 정보는 Account에 넣지 않는다.** 시간 서버 이름, 공통 서비스 위치, 호스트 별칭은 현장 배치 소유자가 갖고, 단일 원본은 기존 `private/site-map.yaml`(`tools/remote/site_map.py`)이다. 새 배치 파일을 Account에 만들지 않는다. 각 호스트의 실제 설정(예: chrony의 시간원)이 이 원본과 같은지 `tools/remote/update_status.py` 같은 기존 점검이 대조한다.
3. **앱은 발급자 주소만 설치 값으로 갖고 나머지 신원 사실은 문서에서 갱신한다.** 로봇은 D-992처럼 처음 고정한 키 해시로 문서 서명을 검증한다(신뢰 대상을 호출자가 정하지 못한다).
4. **계약 버전 불일치는 Monitoring과 업데이트 상태에서 빨강이다.** 앱은 쓰는 문서 버전과 갱신 시각을 상태에 싣는다.
5. **완료 정의는 네 상태다: 착지(landed) · 게시(published) · 실행(running) · 수용(accepted).** 산문이 아니라 `tools/remote/update_status.py` 출력으로 강제한다: 드리프트 나이, 보류 사유와 나이를 보이고, 72시간을 넘기면 0이 아닌 종료 코드를 낸다.
6. **보류(hold)는 만료를 가진다.** R 이전 보류는 24시간 관측 단계 뒤 4일을 그대로 있었다. 13단계 "타이머 켜고 보류 해제"가 실행되지 않았기 때문이다. 만료 없는 보류는 허용하지 않는다.
7. **감시자의 감시자:** 모델 PC의 `rosy-host-guard`를 확장해 R의 `/monitoring-health`와 마지막 수집 신선도를 확인한다.
8. **APK에 구운 발급자(Cam·Pilot)는 갱신할 수 없다.** 발급자 이름 변경은 재빌드 표시(rebuild flag)가 있어야 하며, 없으면 빨강이다.

### 이번 사건의 근거 사본 목록과 mDNS

위 사본 표가 정리 대상이다. `.local`(mDNS)만으로 부족한 이유: 태그 붙은 tailnet 노드(모델·관제 PC)는 R에 SSH 터널과 LAN 경로로만 닿고, Android 앱은 tailnet으로 접속해 mDNS 응답을 받지 못하며, mDNS는 이름 해석일 뿐 키·앱 목록·계약 버전을 전하지 못한다.

### Migration (순서)

1. 승인 뒤 Account에 읽기 전용 신원 문서와 계약 버전을 추가한다(API 참조 갱신 포함). 기존 설정 파일은 그대로 둔다.
2. `core_common` Account 클라이언트가 문서를 받아 캐시한다. 수신 설정 파일이 있으면 대조만 하고 불일치를 로그와 상태에 남긴다(관찰 단계).
3. 앱을 하나씩 문서 우선으로 바꾼다: Learning(모델 PC), Fleet, CORE·로봇, Games, Android. 옛 설정 파일은 한 릴리스 폴백이다.
4. 불일치 빨강을 켜고 앱별 사본(`receiver.json` 5개 등)을 제거한다.
5. 배치 정보는 `site-map.yaml` 대조 점검(2번 항목)을 `update_status.py`에 더하는 별도 단계다. 그전까지 현장 시간 서버는 R 호스트, 클라이언트 이름은 `rosy-fleet-r.local`이다(2026-11-13 적용).
6. 네 상태 완료 정의·보류 만료·감시자의 감시자는 각각 별도 변경으로 구현한다. 이 ADR은 구현하지 않는다.

### Consequences

- 키 회전·앱 추가가 한 곳 변경이 된다. 호스트 이름 변경은 `site-map.yaml` 한 곳과 실제 설정의 대조가 된다.
- Account 장애 때 앱은 마지막으로 받은 문서로 계속 동작해야 한다(캐시 만료 규칙이 필요하고, 키 만료 뒤 갱신 실패는 빨강으로 보인다).
- 문서 서명 키가 새 신뢰 뿌리가 된다. 키 회전·고정 절차가 D-992보다 가볍지 않다.
- 이 사건의 직접 수정(10초 시계 여유와 `clock_skew` 로그, 실패 사유 로그, R의 시간 서버, Pinky `-TimeSource`)은 이 결정과 독립이며 이미 별도 변경이다. 이 결정이 없어도 그 수정은 유효하다.

### 검증 (제안)

- 호스트 시험: 문서 서명 검증, 버전 불일치 빨강, Account 정지 시 캐시 사용, 키 회전 중 두 키 수용.
- 실물: 모델 PC 웹 앱 5개와 Fleet이 같은 문서 버전을 쓰는지 Monitoring에서 읽고, R 이름 변경 모의 시 한 곳 수정으로 끝나는지 확인한다.
