## D-473 관제 콘솔도 개발 연결 모드에서는 토큰 없이 같은 망 PC에 운용자 세션을 준다

**Status:** Accepted (2026-10-06, 사용자 방향 결정 "관제pc나 기타 pc에선 토큰없이 동작" → 개발 연결 모드 확장 선택. 구현·ARTIFACT·FIELD 별도)

잇는 결정: [D-432](D-432-common-discovery-and-development-link-mode.md)(개발 연결 모드) · [D-471](D-471-same-network-auth-free-request-rejected.md)(같은 망 전면 무인증 기각) · [D-361](D-361-site-console-enrolls-robot-by-screen-code.md)(콘솔 로봇 등록).

### Context

관제 콘솔(`operations/fleet`)은 운용자에게 Bearer 토큰을 요구한다(`fleet/server/site_auth.py` `build_authorize`). 토큰은 관제 PC의 `/etc/rosy/site-secrets/operator.token`(root 전용) 또는 `site-users.yaml` 해시에 있다. 2026-10-06 실기 점검에서 이 토큰을 얻는 절차가 시험을 막았고, 사용자는 관제 PC와 다른 PC에서 토큰 없이 쓰기를 원했다.

D-471은 같은 망 전면 무인증을 기각하고 무코드 접속은 D-432 개발 연결 모드로만 둔다고 정했다. 그 결정은 CORE와 Pilot에 구현되어 있지만(`POST /api/v1/auth/development-session`) Fleet 콘솔에는 대응 경로가 없다.

### Decision

1. **켜는 조건은 두 개를 함께 명시한 경우뿐이다.** 환경 변수 `ROSY_DEPLOYMENT=development`와 Fleet CLI `--connection-mode development`가 모두 있어야 한다. 하나라도 없으면 지금의 `paired` 동작이다. 인증 실패나 설정 누락이 개발 모드로 강등하지 않는다(D-432 4항).
2. **조회와 발급 두 경로를 둔다.**
   - `GET /api/fleet/auth/connection` → `{"mode": "development" | "paired"}`. 인증 없이 읽는다.
   - `POST /api/fleet/auth/development-session` → 개발 모드일 때만 1시간 운용자 세션 토큰을 한 번 돌려준다. 요청 주소는 loopback·RFC1918·link-local 또는 Tailscale(100.64.0.0/10, 사용자 계정 로그인이 필요한 tailnet — 2026-10-06 사용자 결정)이어야 하고, `Host`/`Origin`은 콘솔 자신의 authority여야 한다. 주소당 분당 6회로 제한하고 살아 있는 세션은 8개까지다. 넘으면 가장 오래된 것을 지운다.
3. **세션은 이름 있는 운용자다.** principal ID는 `development-<8자 hex>`, 역할은 `operator`다. `require_named_operator`를 통과하므로 미션 하달도 된다. 모든 발급과 POST는 기존 API 감사 기록에 그 principal로 남는다. 세션은 메모리에만 두고 Fleet 재시작 시 사라진다.
4. **콘솔 화면은 자동으로 받는다.** 콘솔은 저장된 토큰이 없거나 401을 받으면 `connection`을 조회하고, `development`면 세션을 받아 `sessionStorage`에 넣는다. 화면 상단에 "개발 연결 모드" 표시를 항상 띄운다. `paired`면 지금처럼 토큰 입력 칸을 보인다.
5. **로봇 쪽 자격은 바꾸지 않는다.** Fleet이 로봇 CORE에 쓰는 토큰은 기존 등록(D-361 LCD 코드, `robots.yaml`)을 그대로 쓴다. 비상 정지·안전 정지 경로의 인증도 그대로다.

### Alternatives

- **관제 PC localhost만 면제.** 다른 PC 요구를 못 채워 기각.
- **같은 망 전면 무인증.** D-471로 기각된 상태를 콘솔에서 되살리므로 기각.
- **세션을 디스크에 저장.** 재시작 뒤에도 남는 자격이 생겨 기각. 1시간 뒤나 재시작 뒤에는 다시 자동 발급된다.

### Consequences

- 개발 현장 관제 PC는 `site.env`에 두 설정을 넣어야 무토큰이 된다. 운영 프로필은 상속하지 않는다.
- 같은 망의 누구나 1시간 운용자 세션을 받을 수 있다. 개발 모드는 신뢰한 망에서만 켠다.
- 수용: Fleet 단위 시험(두 조건 조합 4가지, 주소·Origin 거부, 상한·만료), 콘솔 브라우저 시험(자동 발급·배지), 관제 PC에서 다른 PC 브라우저로 접속.

**References:** `operations/fleet/fleet/server/site_auth.py`, `operations/fleet/fleet/cli.py`, `operations/fleet/fleet/server/web/console.js`, `middleware/core/api_web/core_api_web/api/v1/connection.py`.
