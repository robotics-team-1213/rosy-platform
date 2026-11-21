## D-1068 Account 로그인 화면만 LAN 별칭으로 연다: issuer는 하나, 8443 호스트 블록과 경로 허용 목록

**Status:** Accepted (2026-11-21 14:3x, 사용자 요청 "테일스케일 없이도 콘솔 로그인 되게". 패널 8 판정 14:37, 안 (d))

잇는 결정: [D-962](D-962-independent-account-and-authenticated-development.md)(Account가 자격·세션·grant 소유) · [D-1021](D-1021-one-owner-per-value-identity-in-account-placement-in-site-map.md)(R 변경 규칙).

### Context

- Fleet 콘솔 문서는 LAN(`<site>.local:8443`)에서 열리지만 로그인은 issuer(tailnet 이름) 443으로 보낸다. LAN PC는 tailnet 이름을 풀지 못하고, 443은 방화벽이 `lo`·`tailscale0`만 받는다. callback도 tailnet 8443 하나다.
- Account는 로그인 전 `authorize`를 상대 경로 `/console/login`으로 보내고, 로그인 화면의 복귀 검사는 `location.origin` 기준이다. 토큰 `iss`는 언제나 설정된 issuer다. 그래서 브라우저가 닿는 Account 앞단 이름은 issuer와 달라도 된다.

### Decision

1. **issuer는 tailnet 이름 하나로 둔다.** 두 번째 issuer를 만들지 않고, 모든 receiver의 `iss`·`aud` 검증을 그대로 둔다. 서버 간 호출(`token`·`introspect`·`revoke`)은 기존 issuer 경로를 쓴다.
2. **Account 브라우저 로그인만 LAN 별칭 호스트로 연다.** 옵트인 `deploy/site/compose.account-lan.yaml`이 proxy에 `Caddyfile.account-lan` 호스트 블록(예: `rosy-fleet-r-account.local`)을 기존 `ROSY_SITE_HTTPS_PORT` 리스너 위에 더한다. 새 포트가 없고 `site-firewall.py`와 LAN 443 정책은 바뀌지 않는다.
3. **경로 허용 목록.** 별칭 호스트는 다음만 Account로 넘기고 나머지는 404다.
   - GET: `/console/login`, 그 화면이 불러오는 `/console/assets` 여섯 파일, `/common/*`(Account가 `shared-assets.json` 목록만 내주는 공개 정적 파일), `/api/fleet/auth/connection`·`session`(로그인 폼이 읽음), `/api/fleet/auth/authorize`.
   - POST: `/api/fleet/auth/login`, `/api/fleet/auth/change-password`(첫 로그인 강제 변경이 같은 폼에서 일어남).
   - 열지 않음: 관리 화면과 API(`/console/accounts`, `accounts`, `clients`, `setup`, `device-clients`), 백채널(`token`, `introspect`, `userinfo`, `apps`, `revoke`, `keys`), 인증 없이 관리자 큐에 쓰는 `access-requests`, 프로필·로그아웃.
4. **인증서와 이름.** 별칭은 site CA로 발급한 전용 leaf(`/etc/rosy/account-lan-tls`)를 쓴다. 기존 site leaf는 다시 발급하지 않는다(핀 유지). mDNS 별칭은 저장소 템플릿 `rosy-mdns-alias@.service`로 광고한다(손 설치 유닛을 대체).
5. **Fleet receiver(별도 조각 S1).** 설정에 명시한 LAN origin·callback·Account 브라우저 origin만 받고, 요청 Host와 정확히 일치할 때만 고른다. 고른 callback은 flow에 결속한다. 설정이 없으면 지금과 같다.

### 기각한 안

- **(a) Fleet 8443 아래 `/account` 경로 접두사(와 LAN issuer).** Account와 Fleet 화면이 같은 origin이 되어 세션 경계가 사라진다. 쿠키 이름이나 `Path`로는 나눌 수 없고, 두 앱이 같은 경로(`/console/login`, `/api/fleet/auth/login`)를 써서 Account 화면·라우트도 고쳐야 한다. 두 번째 issuer는 모든 receiver의 신뢰 계약을 바꾼다.
- **(b) LAN 443 열기.** LAN PC는 tailnet 이름을 여전히 풀지 못하고, Account 앞단 인증서 SAN도 tailnet 이름뿐이다. 방화벽 코드를 바꾸면 주기 검사가 실패할 때 fail-closed가 proxy를 멈춰 8443·443 전체가 중단될 위험이 있다. Account 443 전체가 LAN에 열린다.
- **(c) Fleet 지역 로그인.** D-962의 소유권(자격·세션·회수·감사는 Account)을 어긴다. Fleet receiver 모드의 비밀번호 POST는 409로 막혀 있다.

### Consequences

- Account 로그인 화면이 LAN 인터페이스에 새로 노출된다(보안 경계 변경). 무차별 대입은 기존 로그인 속도 제한(주소당)이 막고, Caddy가 `X-Forwarded-For`를 클라이언트 주소로 덮어쓴다.
- tailnet 호스트와 LAN 호스트의 Account·Fleet 세션은 호스트별로 따로다. 중앙 회수는 둘 다 끊는다.
- LAN PC는 ROSY site CA를 신뢰해야 경고가 없다. 공개 CA가 아니므로 Android 앱 링크에는 쓰지 않는다.
- 다른 앱(Calibration, Learning)의 callback은 여전히 tailnet 이름이라 LAN 전용 PC에서는 안 된다(범위 밖).
- 30분 로그인 점검은 issuer 주소로 시작하므로 LAN 경로의 증거가 아니다.

### Evidence

- 2026-11-21 로컬: Caddy 2.10.2로 기본 `Caddyfile`과 `Caddyfile.account-lan`을 함께 띄워 확인. 허용 경로 9개는 Account 대역으로 가고 Host 유지·`X-Rosy-Lan-Camera` 제거·`X-Forwarded-For` 덮어쓰기. 관리·백채널·로그아웃·프로필·`/`·경로 우회(`..`, `%2e%2e`) 23개는 404. 다른 Host는 Fleet 블록으로 간다.
- 정적 시험 `test/test_site_account_lan.py`: 허용 목록, overlay가 방화벽 계획을 바꾸지 않음, 로그인 화면 import 닫힘, 후보 묶음, 자동 갱신 overlay 순서.
- 패널 8(Claude·Codex 안 (d), agy 안 (a)) 판정 2026-11-21 14:37.
