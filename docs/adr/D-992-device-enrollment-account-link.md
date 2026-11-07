## D-992 장비 등록과 Rosy Account 연동

**Status:** Accepted (2026-11-07, 사용자 지시: 모든 앱과 장비를 공통 코어로 연동, 2단계부터 진행). 소스와 시험의 수용이며 현장 활성화와 실물 수용을 뜻하지 않는다. D-955 결정 5의 범위를 아래처럼 좁힌다.

**관련:** D-427 · D-429 · D-430 · D-555 · D-757 · D-807 · D-955 · D-962 · D-987

### Context

D-955 결정 5는 장비 등록이 끝나면 같은 transaction에서 등록부 줄을 만들고 수신 설정을 TLS 등록 경로로 보내며, OMX 팔·Cam·학습 서비스도 같은 등록부에 기계 신원으로 올린다고 정했다. 그 뒤 D-962가 Account를 Fleet에서 분리해 다음이 생겼다.

- Fleet과 Account의 DB가 달라 하나의 transaction이 될 수 없다.
- Fleet이 Account 등록부에 쓸 경로와 자격이 없다.
- D-807과 D-962는 Account가 기계·장치·서비스 자격을 소유하지 못하게 하고 공통 자격 저장소를 금지한다. 기계 신원을 같은 등록부에 올리면 이 결정과 충돌한다.

### Decision

1. **등록부에는 사람이 로그인해 쓰는 곳만 적는다. 기계 자격은 넣지 않는다.** 로봇·OMX CORE는 사람 로그인을 받는 client로 올라가며, 기계 자격은 D-807대로 기존 owner(`robot_enrollments`, `device_credentials`, `camera_peer_relationships`, OMX 설정, Learning의 Fleet bearer)에 남는다. D-955 결정 5의 "기계 신원을 같은 등록부에"는 이 결정으로 대체한다. 어떤 장비가 살아 있는지는 Monitoring이 본다(D-876).
2. **Fleet은 로봇 줄 하나만 쓸 수 있는 좁은 등록 자격을 갖는다.** `PUT /api/fleet/auth/device-clients/{robot_id}`는 `Authorization: Bearer`의 등록 키를 Account 설정 `registrar_token_sha256`과 비교한다. 설정이 없으면 이 경로는 닫혀 있다. client는 `robot-<robot_id>`, 자원은 `robot:<robot_id>`로 서버가 정하고, 복귀 주소는 `/api/account/callback` 경로의 HTTPS여야 한다. 사람이 등록한 다른 줄이나 계정, 토큰은 건드릴 수 없다. Account는 키 원문이 아니라 digest만 갖는다.
3. **관리자의 결정이 이긴다.** 등록 경로는 주소와 표시 이름만 고치고 `enabled`를 바꾸지 않는다. 계정 관리자가 정지한 로봇은 다시 등록해도 정지 상태다.
4. **순서는 등록부 다음 로봇이고, 하나의 transaction이 아니다.** D-555 허브 연결이 성공한 뒤 Fleet이 Account에 줄을 쓰고, 그다음 TLS로 로봇에 수신 설정을 보낸다. 어느 쪽이 실패해도 이미 끝난 허브 연결을 되돌리지 않는다. 사람 로그인 연결 실패가 로봇 운용 연결을 끊으면 안 되기 때문이다. 결과는 감사 기록과 등록 목록의 `account_link`에 남고, 허브 연결을 다시 하면 같은 값으로 다시 시도한다.
5. **로봇은 `PUT /api/v1/account/receiver`로 수신 설정을 받는다.** 권한은 D-555의 `PUT /fleet/link`와 같다(CORE TLS 리스너, 관리자 또는 사이트 등록 토큰). 암호화 키는 로봇에서 만들어 로봇 밖으로 나가지 않고, 자원은 CORE가 자기 identity로 정한다. 비밀이 아닌 issuer, client, callback, 공개 키만 전송한다.
6. **CORE를 재시작하지 않는다.** 수신 설정은 `app.state.account_client`에 바로 적용된다. 운용 중인 로봇의 주행 경로와 FleetAgent를 건드리지 않는다.
7. **운영자가 정한 설정이 우선한다.** `auth.account_client_file`이 있으면 CORE는 409 `ACCOUNT_RECEIVER_MANAGED`로 거절한다. 받은 파일이 손상되면 CORE는 기동을 멈추지 않고 Account 없이 뜬다. 이 경로의 오류로 로봇 기동이 막히면 안 된다. 운영자 파일이 잘못되면 시작을 거부하는 기존 규칙은 그대로다.

### 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-427 · D-429 | 새 part와 최상위 폴더가 없다. 관심사 분류와 source manifest를 바꾸지 않는다. |
| D-430 | safety 태그 경로를 바꾸지 않는다. 수신 설정은 사람 로그인만 다루고 CORE 가드, SAF-003, 비상정지, 최종 `cmd_vel` writer는 그대로다. |
| D-555 | 허브 연결의 TLS 강제와 권한을 재사용한다. 허브 연결의 성공 조건과 롤백은 바꾸지 않는다. |
| D-757 | 수신 계약과 권한 모델을 그대로 쓴다. 등록부 줄은 권한을 주지 않으며 사람의 grant가 따로 있어야 로그인된다. |
| D-807 · D-962 | 기계 자격을 Account로 옮기지 않는다. 등록 키 digest 하나는 예외로, 호출자 확인에만 쓰고 계정·토큰·다른 줄에 닿지 못한다. |
| D-955 | 결정 5를 위와 같이 대체한다. "같은 transaction"은 결정 4의 순서로 바꾼다. |
| D-987 | 카탈로그의 "Account는 기계 자격을 맡지 않는다"를 유지한다. |

### Consequences

- 활성화에는 Account 설정의 `registrar_token_sha256`, Fleet 환경 변수 `ROSY_ACCOUNT_LINK_CONFIG`가 가리키는 JSON(issuer, 등록 키 파일, 공개 키 파일)가 필요하다. 없으면 지금처럼 동작한다.
- 로봇을 빼도 등록부 줄은 자동으로 정지되지 않는다. 계정 관리자가 화면에서 정지한다. 재발급 없이 허브 연결만 끊는 경우와 구분할 근거가 없어 자동 정지를 넣지 않았다.
- `account_link` 상태는 Fleet 메모리에만 있어 재시작하면 `unknown`이다. 등록부와 로봇 readback이 정본이다.
- Cam과 학습 서비스의 수신 설정은 이 경로로 배달하지 않는다. Cam은 앱 설정, Learning은 자기 배포 설정을 쓰며 등록부에는 관리 화면으로 올린다.

### 확인하지 못한 것

실물 로봇과 현장 Account 사이의 전체 흐름은 실행하지 않았다. 시험은 CORE와 Account의 실제 라우트를 각각 돌리고 Fleet의 호출을 대역으로 잇는다.
