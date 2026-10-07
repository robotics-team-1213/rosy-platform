## D-519 관제 콘솔 사람은 아이디·비밀번호로 로그인하고 HttpOnly 세션 쿠키를 쓴다. 토큰은 기계 클라이언트에만 남긴다

**Status:** Accepted (2026-10-08, 사용자 결정 "C 지금 + A 다음" 중 A — 토큰 대신 아이디·비번, 이 브라우저 기억. 구현·ARTIFACT·FIELD 별도)

잇는 결정: [D-276](D-276-site-fleet-per-principal-api-authorization.md)(principal별 API 권한) · [D-473](D-473-fleet-console-development-connection-mode.md)(개발 연결 모드) · [D-471](D-471-same-network-auth-free-request-rejected.md)(같은 망 전면 무인증 기각).

### Context

관제 콘솔은 사람에게도 64자 Bearer 토큰을 요구한다. 토큰은 탭마다 `sessionStorage`에 들어가서 새 탭·새 창·브라우저 재시작마다 다시 붙여 넣어야 한다. 원본은 관제 PC의 root 전용 파일에 있어 sudo 없이는 꺼내지도 못한다. 2026-10-08 사용자는 이 절차가 "너무 힘들다"며 토큰을 없애고 아이디·비번으로 바꾸기를 요청했다. 당장은 D-473 개발 연결 모드로 풀었지만(C) 그 모드는 같은 망 누구에게나 운용자 세션을 주므로 운영 현장에는 맞지 않는다.

### Decision

1. **로그인 계정은 기존 `site-users.yaml`에 둔다.** 사용자 항목은 `token_sha256` 대신 또는 함께 `login`과 `password_scrypt`를 가질 수 있다. 둘 중 하나의 자격은 반드시 있다. `login`은 `^[a-z0-9._-]{1,32}$`이고 파일 안에서 유일하다. `password_scrypt`는 `scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>`(표준 라이브러리 `hashlib.scrypt`, n=2^15, r=8, p=1, 솔트 16바이트, 결과 32바이트)다. `service` 역할은 로그인을 가질 수 없다(기계 전용). 평문 비밀번호는 파일에 쓰지 않는다. 해시는 `python -m fleet.server.site_users hash-password`가 표준 입력으로 받아 한 줄을 출력한다.
2. **로그인 경로.** `POST /api/fleet/auth/login` `{login, password, remember}` → 성공 시 204와 `Set-Cookie: rosy_fleet_session=<랜덤 32바이트>; HttpOnly; Secure; SameSite=Strict; Path=/`. `remember`가 참이면 `Max-Age`를 30일로, 아니면 브라우저 세션 쿠키다. 실패는 계정 유무와 관계없이 같은 401 `LOGIN_FAILED`이며, 없는 계정도 더미 해시로 scrypt를 한 번 계산한다. 주소당 분당 실패 5회, 계정당 분당 실패 10회를 넘으면 429 `RATE_LIMITED`다. 성공과 실패는 기존 API 감사 기록에 남는다(실패는 principal 대신 `login:<이름>`).
3. **세션은 서버 DB에 해시로 둔다.** `--tasks-db`(site-users가 이미 요구한다)의 표에 쿠키 값의 SHA-256, principal_id, role, 비밀번호 해시의 SHA-256 지문, 만든 시각, 마지막 사용 시각, remember를 둔다. 유휴 한도는 12시간(쓸 때마다 연장), remember면 30일이다. 만든 지 30일이 지나면 어느 쪽이든 끝난다. 확인할 때마다 `site-users.yaml`의 같은 login이 같은 principal·role·비밀번호 지문을 갖는지 본다. 하나라도 바뀌었거나 계정이 지워졌으면 그 세션은 바로 무효다. 비밀번호를 바꾸면 그 계정의 모든 세션이 끝난다. Fleet을 다시 시작해도 세션은 남는다(D-473 개발 세션과 다르다).
4. **인증 순서.** `Authorization: Bearer`가 있으면 지금과 같다(토큰, 개발 세션). 없으면 세션 쿠키를 본다. 쿠키로 인증한 `GET`·`HEAD` 외 요청은 `Origin`이 있어야 하고 그 authority가 `Host`와 같아야 한다. 아니면 403 `CSRF_REJECTED`다. 쿠키 principal은 이름 있는 운용자이므로 `require_named_operator`를 통과한다.
5. **로그아웃과 조회.** `POST /api/fleet/auth/logout`은 그 세션을 지우고 쿠키를 만료시킨다. `GET /api/fleet/auth/session`은 쿠키·Bearer 어느 쪽이든 `{principal_id, role, via: "cookie"|"bearer"|"development", expires_at}`을 돌려주고, 인증이 없으면 401이다.
6. **콘솔 화면.** 콘솔·설치·셀·사이트 지도 화면은 401을 받으면, 연결 모드가 `development`이면 지금처럼 개발 세션을 받는다. `paired`이면 아이디·비밀번호 입력과 "이 브라우저 기억(30일)" 칸을 보인다. 토큰 입력 칸은 "토큰으로 접속" 접힘 안으로 옮겨 남긴다. 쿠키는 같은 출처 `fetch` 기본값으로 따라가므로 화면 코드는 저장된 토큰이 없을 때 `Authorization`을 붙이지 않기만 하면 된다. 로그인한 화면은 상단에 principal과 로그아웃을 보인다.
7. **기계 클라이언트는 그대로다.** Vision 관측 토큰, 영상 lease, 셀 service principal, CORE 등록 키, 스크립트의 Bearer 토큰은 바뀌지 않는다. 로봇 쪽 자격(D-361)과 비상 정지 경로도 그대로다.

### Alternatives

- **토큰을 `localStorage`에 오래 보관.** 붙여 넣기는 한 번으로 줄지만, 스크립트가 읽을 수 있는 곳에 무기한 운용자 자격이 남는다. 원본 토큰을 얻는 sudo 단계도 그대로라 기각.
- **같은 망 무인증.** D-471로 기각된 상태다. 개발 현장에는 D-473이 이미 있다.
- **별도 사용자 DB와 관리 화면.** 계정은 현장마다 몇 개뿐이다. 이미 root 전용으로 배포되는 `site-users.yaml` 한 곳에 두는 편이 자격 위치를 늘리지 않는다. 화면에서 계정을 관리할 필요가 생기면 그때 정한다.
- **bcrypt/argon2 패키지.** 새 의존성이 생긴다. 표준 라이브러리 scrypt로 충분하다.

### Consequences

- 현장 관리자는 `site-users.yaml`에 login과 password_scrypt를 한 번 넣고 Fleet을 다시 시작한다. 그 뒤 운용자는 어느 PC에서든 아이디·비번으로 들어가고, "기억"을 고르면 30일 동안 다시 묻지 않는다.
- 쿠키는 `Secure`라 https(현장 Caddy) 또는 `localhost`에서만 저장된다. 같은 망 http 직접 접속은 로그인할 수 없다.
- 수용: 단위 시험(해시 형식, 로그인 성공·실패·속도 제한, 유휴·절대 만료, 계정·비번·역할 변경 무효, CSRF Origin, Bearer 우선, 재시작 뒤 유지), 콘솔 브라우저 시험(로그인 → 새로고침·새 탭 유지 → 로그아웃), 관제 PC에서 다른 PC 브라우저로 로그인.

**References:** `operations/fleet/fleet/server/site_auth.py`, `operations/fleet/fleet/server/site_users.py`, `operations/fleet/fleet/server/development_session.py`, `operations/fleet/fleet/server/web/console.js`, `operations/fleet/fleet/server/web/development-auth.js`.
