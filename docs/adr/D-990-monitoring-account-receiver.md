## D-990 Monitoring 화면의 Rosy Account 로그인

**Status:** Accepted (2026-11-07, 사용자 지시: 모든 ROSY 앱은 Account 등 공통 코어로 서로 연동되어야 한다). 소스와 시험의 수용이며 Account client 등록·배포·현장 수용을 뜻하지 않는다.

**관련:** D-427 · D-429 · D-430 · D-757 · D-807 · D-876 · D-936 · D-955 · D-962 · D-987

### Context

D-955 결정 1은 앱 사이에 따로 계정이나 연결을 만들지 않는다고 정했다. Fleet, Robot, Pilot, Games, Learning은 Account로 사람을 확인하지만 Monitoring 화면은 사람이 전용 조회 키를 직접 넣는다. 같은 키를 공유하므로 사람별 권한과 회수가 없다.

### Decision

1. **사람은 Account로 Monitoring을 읽는다.** Monitoring은 D-757 수신 계약(`core_common.protocol.account_client`)으로 로그인·세션·로그아웃을 처리한다. 경로는 `/api/monitoring/v1/account/*`이고 쿠키는 `/api/monitoring` 경로로 한정한다. 같은 origin의 Fleet 쿠키와 섞이지 않는다.
2. **권한은 새 site capability `monitoring.read`다.** 다른 앱의 권한으로 읽지 않는다(D-757). 권한 없는 계정은 403이다. 팀원·조회자 역할 묶음에 넣어 계정 관리 화면이 함께 채우지만, D-955처럼 서버가 기존 계정에 자동으로 주지 않는다.
3. **조회 키는 남기되 사람의 기본 경로가 아니다.** 수집기 사이 `peer` 조회는 기계 자격이라 D-807대로 Account로 옮기지 않는다. 화면의 키 입력은 Account 장애 때 쓰는 "비상 조회 키"로 접어 둔다. `Authorization` 헤더가 있으면 키로만 판정하고 쿠키로 넘어가지 않는다.
4. **설정은 `monitoring.yaml`의 선택 항목 `account_config`다.** 비어 있으면 지금처럼 키로만 동작한다. 수신 설정의 resource는 그 수집기의 `site:<site_id>`여야 하며 아니면 시작을 거부한다. D-936 배치는 바꾸지 않는다. Compose에는 site CA 발급자를 검증하도록 `SSL_CERT_FILE`만 더한다.
5. **Account 세션은 자기 사이트만 읽는다.** 접근 토큰이 resource 하나만 담기 때문이다. 여러 사이트를 함께 보는 통합 집계 화면은 다중 사이트 수신을 정할 때까지 키로 읽는다.

### 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-427 | 새 part와 최상위 폴더가 없다. |
| D-429 | 관심사 분류와 source manifest를 바꾸지 않는다. |
| D-430 | Monitoring에 명령 권한을 주지 않는다. 읽기 인증만 바뀐다. |
| D-757 · D-962 | 수신 계약을 그대로 쓰고 capability 하나를 더한다. |
| D-807 | 수집기 사이 키와 원천 자격은 기계 자격으로 유지한다. |
| D-876 · D-936 | 독립 수집과 Fleet 이미지 동반 배치를 유지한다. Fleet이 멈춰도 독립 Account로 로그인하고, Account도 닿지 않으면 비상 키로 읽는다. |
| D-955 | 결정 1을 Monitoring에 적용한다. 결정 3의 팀원 묶음에 `monitoring.read`를 더한다. 2~5단계는 바꾸지 않는다. |
| D-987 | 카탈로그의 Monitoring 인증 설명을 이 결정으로 고친다. |

### Consequences

- **배포 순서가 중요하다.** `monitoring.read`를 모르는 이전 수신부는 이 권한이 든 site 토큰을 거절한다. Fleet·Games 이미지와 Cam·Pilot Android 앱을 먼저 올린 뒤 계정에 부여한다. 먼저 부여하면 그 사람의 이전 Cam 로그인이 실패한다.
- 활성화에는 Account에 client와 callback을 등록하고 수신 설정과 공개 키를 Monitoring 비밀 폴더에 두는 운영 작업이 필요하다. D-955 2단계 전에는 Account 재시작이 따른다.
- 네이티브 설치 휠은 Account 의존성을 싣지 않으므로 `account_config`를 켤 수 없다. 현장 이미지에서만 켠다.
- 공용 `shared/web/account-session.js`는 경로 인자를 받는다. 기본값이 그대로라 기존 앱은 달라지지 않는다.

### 확인하지 못한 것

실제 Account와 연결한 로그인, 실제 site proxy 경유 callback, Android 앱의 새 권한 수용은 실물로 확인하지 않았다.
