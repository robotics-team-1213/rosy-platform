## D-1021 Account가 사이트 설정 문서 하나를 내주고, 앱은 발급자 주소만 갖고 나머지는 갱신한다

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

1. **Account가 사이트 설정 문서 하나를 서명해 내준다.** 내용은 발급자, 서명 공개 키(회전 중이면 둘), 앱 목록, 시간 서버 이름, 공통 서비스 위치(Account·Monitoring·Media), Account 계약 버전이다. 문서는 읽기 전용이고 비밀이 없다. 정본은 Account의 기존 등록부이며 새 원장·서비스를 만들지 않는다(D-987 4항, D-1001).
2. **앱은 발급자 주소만 설치 값으로 갖는다.** 나머지는 문서에서 받아 갱신한다. 키는 발급자 TLS로 받은 문서의 서명 키 사슬로 검증하고, 로봇은 D-992처럼 처음 한 번 해시로 고정한 키로 문서 서명을 검증한다(신뢰 대상을 호출자가 정하지 못하는 D-992 5항 유지).
3. **버전 불일치는 Monitoring과 업데이트 상태에서 빨강으로 보인다.** 각 앱은 자기가 쓰는 문서 버전과 마지막 갱신 시각을 상태에 싣고, Account의 현재 버전과 다르거나 갱신이 오래되면 `tools/remote/update_status.py`와 Monitoring이 빨강으로 표시한다. 조용히 옛 사본으로 도는 일이 없어진다.
4. **시간 서버 이름도 문서의 한 항목이다.** 호스트 시간 설정 도구(`rosy_time_sync.py`)가 문서의 이름을 읽어 chrony를 맞출 수 있게 하되, 시간 동기를 바꾸는 유지보수 규칙(D-859: 작업 중지 후 적용)은 그대로다.

### mDNS만으로 부족한 이유

- 태그 붙은 tailnet 노드(모델·관제 PC)는 R에 SSH 터널과 LAN 경로로만 닿는다. `.local` 이름은 이 경로에서 해석되지 않는다.
- Android 앱은 tailnet을 통해 접속하며 mDNS 응답을 받지 못한다.
- mDNS는 이름 해석일 뿐 키·앱 목록·계약 버전을 전하지 못한다. 이름이 맞아도 사본의 내용이 틀리면 이번 사건이 되풀이된다.

### Migration (순서)

1. 이 ADR 승인 뒤 Account에 읽기 전용 문서 경로와 계약 버전을 추가한다(API 참조 갱신 포함). 기존 설정 파일은 그대로 둔다.
2. `core_common`의 Account 클라이언트가 문서를 받아 캐시하게 한다. 수신 설정 파일이 있으면 문서와 대조만 하고 불일치를 로그와 상태로 남긴다(관찰 단계).
3. 앱을 하나씩 문서 우선으로 바꾼다: Learning(모델 PC), Fleet, CORE·로봇, Games, Android. 앱마다 옛 설정 파일 경로는 한 릴리스 동안 폴백으로 남긴다.
4. 버전 불일치 빨강 표시를 켠다. 그 뒤 앱별 사본(`receiver.json` 5개 등)을 제거한다.
5. 시간 서버 이름을 문서에서 읽는 경로는 마지막에 켠다. 그전까지 현장 시간 서버는 R 호스트이고 클라이언트 이름은 `rosy-fleet-r.local`이다(2026-11-13 적용).

### Consequences

- 호스트 이름 변경·키 회전·앱 추가가 한 곳 변경이 된다. 사본마다 손으로 고치다 빠뜨리는 일이 줄어든다.
- Account 장애 때 앱은 마지막으로 받은 문서로 계속 동작해야 한다(캐시 만료 규칙이 필요하고, 키 만료 뒤 갱신 실패는 빨강으로 보인다).
- 문서 서명 키가 새 신뢰 뿌리가 된다. 키 회전·고정 절차가 D-992보다 가볍지 않다.
- 이 사건의 직접 수정(60초 시계 여유, 실패 사유 로그, R의 시간 서버, Pinky `-TimeSource`)은 이 결정과 독립이며 이미 별도 변경이다. 이 결정이 없어도 그 수정은 유효하다.

### 검증 (제안)

- 호스트 시험: 문서 서명 검증, 버전 불일치 빨강, Account 정지 시 캐시 사용, 키 회전 중 두 키 수용.
- 실물: 모델 PC 웹 앱 5개와 Fleet이 같은 문서 버전을 쓰는지 Monitoring에서 읽고, R 이름 변경 모의 시 한 곳 수정으로 끝나는지 확인한다.
