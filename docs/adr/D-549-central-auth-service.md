## D-549 사람 인증은 현장 하나의 Rosy Auth가 발급한 계정(아이디·비밀번호)으로 하고, 로봇은 그 서명을 검증만 한다

**Status:** Proposed (2026-10-09, 사용자 방향 "추후 auth service로 인증 도입, 발급된 사람이 id·비번으로 간단히 로그인". 구현 전 사용자 결정 필요 항목은 아래 열린 질문)

잇는 결정: [D-193](D-193-login-code-and-credential-lifecycle.md)(로봇 로그인 코드) · [D-276](D-276-site-fleet-per-principal-api-authorization.md)(Fleet principal별 권한) · [D-302](D-302-site-registry-credential-separation.md)(사용자 자격과 등록 자격 분리) · [D-361](D-361-site-console-enrolls-robot-by-screen-code.md)(화면 코드 등록) · [D-519](D-519-fleet-console-password-login-session-cookie.md)(Fleet 아이디·비밀번호 로그인) · D-548(장치 개발 모드 표식).

### Context

2026-10-09 기준 사람 인증은 두 곳에 따로 있다.

| 위치 | 저장소 | 역할 | 사람이 하는 일 |
|---|---|---|---|
| CORE(로봇마다) | 로봇 config의 토큰 해시 | viewer · operator · administrator | 로봇마다 LCD 8자 코드를 입력하거나 토큰을 붙여 넣는다 |
| Fleet(현장) | `site-users.yaml`(D-519 login + scrypt) | viewer · operator · policy-admin · service | 관리자가 해시를 손으로 만들어 YAML을 고치고 Fleet을 재시작한다 |

같은 사람이 콘솔과 로봇 대시보드·Pilot에 따로 들어가야 한다. Fleet 계정은 로봇에서 아무 의미가 없다. Fleet은 로봇마다 따로 받은 토큰으로 로봇을 부른다. 역할 이름도 둘이 다르다.

### Decision (제안)

1. **계정은 한 곳이다.** 현장 PC의 Rosy Auth가 사람 계정(login, scrypt 비밀번호, 역할, 사용 여부)을 가진다. 가입은 없고 관리자가 발급한다(`rosy-auth user add <login> --role operator`, 비밀번호는 표준 입력). 해시 형식과 로그인 규칙은 D-519 1·2를 그대로 쓴다. 계정 추가·정지·비밀번호 변경은 재시작 없이 반영한다.
2. **역할은 셋이다.** viewer < operator < administrator. Fleet의 policy-admin은 administrator로 합친다. 기계용 service는 계정이 아니라 지금처럼 토큰이다(D-519 7).
3. **콘솔은 세션 쿠키다.** D-519의 로그인·쿠키·CSRF 규칙을 Rosy Auth가 소유한다. Fleet은 세션을 Rosy Auth에 묻는다(같은 프로세스면 함수 호출).
4. **로봇은 서명만 검증한다.** 로그인한 사람이 로봇을 쓰려 하면 Rosy Auth가 짧은 접근 토큰을 서명해 준다. Ed25519, 클레임은 `sub`(login) · `role` · `aud`(로봇 device id 또는 `*`) · `exp`(최대 1시간) · `jti`. CORE는 릴리스나 현장 설정으로 받은 Rosy Auth 공개키 하나로 검증한다. 요청마다 네트워크를 쓰지 않으므로 Rosy Auth가 잠깐 죽어도 이미 받은 토큰은 만료까지 쓴다. 감사 기록의 principal은 `sub`다.
5. **로봇 자체 경로는 복구용으로 남긴다.** 카드 관리자 토큰, LCD 로그인 코드(D-193), 비상 정지 경로는 그대로다. Rosy Auth가 없는 AP 모드나 단독 로봇에서도 들어갈 수 있어야 한다.
6. **정지는 짧은 수명으로 한다.** 계정을 정지하면 새 토큰은 즉시 거부되고, 이미 나간 토큰은 `exp`까지 산다. 그보다 빨라야 하면 서명 키를 바꾼다. 폐기 목록은 두지 않는다.
7. **개발 모드는 별개다.** D-548 표식과 D-473 개발 연결 모드는 그대로 둔다. Rosy Auth는 운영 현장의 길이다.

### 단계

| 단계 | 내용 | 새 프로세스 |
|---|---|---|
| A | D-519 계정·세션 코드를 Fleet 안의 `auth` 모듈로 모으고, CLI 발급과 무재시작 반영을 넣는다 | 없음 |
| B | 로봇 접근 토큰 서명(Rosy Auth)과 검증(CORE). 대시보드·Pilot은 콘솔 로그인으로 로봇에 들어간다 | 없음 |
| C | 필요해지면(여러 현장, 외부 SSO) Rosy Auth를 별도 서비스로 꺼낸다 | 있음 |

### Alternatives

- **외부 IdP(Keycloak 등)를 지금 들인다.** 현장마다 계정은 몇 개뿐이고 오프라인 현장도 있다. 운영할 서버 하나가 더 생긴다. 단계 C에서 다시 본다.
- **CORE가 요청마다 Rosy Auth에 묻는다(introspection).** Wi-Fi가 흔들리면 로봇 조작이 멈춘다. 서명 검증은 네트워크가 없어도 된다.
- **Fleet 계정을 로봇마다 복사한다.** 로봇 수만큼 비밀번호 해시가 퍼지고 정지가 늦게 퍼진다.
- **지금 상태를 유지한다.** 사람은 콘솔과 로봇마다 따로 로그인하고, 관리자는 YAML과 재시작으로 계정을 관리한다.

### Consequences

- 사람은 아이디·비밀번호로 한 번 로그인하고 콘솔·로봇 대시보드·Pilot을 같은 신원으로 쓴다.
- CORE에 서명 검증 경로 하나와 공개키 배포가 생긴다. API reference의 인증 절과 D-193·D-276·D-519를 같은 변경에서 고친다.
- 역할 이름이 바뀌므로 Fleet의 policy-admin 사용처를 옮긴다.

### 열린 질문 (Accepted 전에 정한다)

1. Rosy Auth를 어디서 돌리나: 현장 PC(robttt)의 Fleet 프로세스 안(제안), 아니면 별도 컨테이너.
2. 로봇 접근 토큰의 `aud`: 로봇마다(제안) 또는 현장 전체 `*`.
3. 계정 관리 화면이 필요한가, CLI로 충분한가(제안: CLI 먼저).
4. Tailscale 원격 접속(D-477)에서도 같은 계정을 쓰나.
