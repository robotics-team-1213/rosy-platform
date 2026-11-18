## D-1034 원격·분리 제어 유닛의 중앙 Rosy Account 연동, 터널 브리지, 기계 토큰 분리 및 공용 브라우저 세션

**Status:** Accepted (2026-11-15, 사용자 결정 "당연히 모두 중앙 통합해" / "교훈이나 ADR로 정확하게 적어나야지"). `rosy-arm-cell`(`cell-a-fleet-1`) ↔ `rosy-fleet-r`(`rosy-site-account-1`) 실물 연동 경로 검증 및 `shared/web`/`learning` 공용 세션 통합 구현까지 반영. 서명 compose 템플릿 편입과 `rosy-site-fleet-1` 보류 해제는 후속 배포 과제.

잇는 결정: [D-960](D-960-control-unit-per-arm-set-under-integrated-r.md)(셀 관제 분리) · [D-962](D-962-independent-account-and-authenticated-development.md)(Account 독립 서비스·기계 토큰) · [D-1001](D-1001-common-logic-placement-on-r.md)(공통 서비스 배치) · [D-1021](D-1021-one-owner-per-value-identity-in-account-placement-in-site-map.md)(값 소유자와 Account 단일 신원)

### Context

1. 통합관제 R(`rosy-fleet-r`)에서는 Docker 서비스 `rosy-site-account`와 `rosy-site-fleet`이 같은 호스트의 `site_backend` 네트워크 위에서 실행되며, `rosy-site-fleet`은 이미 `ROSY_FLEET_ACCOUNT_CLIENT_CONFIG`를 받아 `/api/fleet/auth/login`이 중앙 Account로 `303` 리다이렉트된다. 다만 업그레이드 보류 중인 구형 Fleet 이미지에서는 `/console/login` 자체가 아직 정적 `login.html`(`200`)을 반환해, 통합이 안 된 것으로 오인되기 쉽다.
2. 반면 별도 물리 호스트(`rosy-arm-cell`)에서 실행되는 서브 제어 유닛(`cell-a-fleet`, `:8543`)은 R의 `site_backend` Docker 네트워크에 직접 붙어 있지 않다. Compose에 `ROSY_FLEET_ACCOUNT_CLIENT_CONFIG`·통합 CA·`extra_hosts`가 빠지거나, 호스트의 `rosy-account-tunnel` SSH 터널이 루프백(`127.0.0.1`)만 바인드하면 컨테이너 내부 Fleet이 중앙 Account에 TLS 접속할 수 없고 로컬 fallback/로그인 실패가 발생한다.
3. 같은 셀 호스트의 `omx-arm-status`, `omx-observation-bridge` 등 비사람 상태 송신기는 사람 계정 로그인이 아닌 `site-users.yaml`의 기계 자격 토큰을 사용한다.
4. 브라우저 코드에서도 `learning/curation/perception/review_app_web/account-session.js`가 `/common/account-session.js`(`shared/web/account-session.js`)의 교차 탭 신원 감시(`storage` 이벤트·주기 폴링·저장소 알림)를 중복 구현해 계약 테스트 불일치를 일으켰다.

### Decision

1. **웹 콘솔을 여는 모든 Fleet 제어 유닛(통합관제 R + 원격 셀/서브 관제 포함)은 R의 중앙 `rosy-site-account`를 단일 사람 인증 발급자로 사용한다.** 각 제어 유닛 Compose는 `ROSY_FLEET_ACCOUNT_CLIENT_CONFIG`를 마운트하고, R의 Account `authority.json`은 해당 제어 유닛의 `client_id`, 정확한 HTTPS `/api/fleet/auth/callback` redirect URI, site resource를 등록한다.
2. **원격 호스트의 컨테이너 ↔ 중앙 Account 연결은 TLS 검증을 끄지 않고 터널 브리지 + 통합 CA로 구성한다.**
   - 호스트 SSH 터널(`rosy-account-tunnel`)은 루프백과 Docker 브리지 게이트웨이 주소를 함께 바인드하고(`After=docker.service` 순서 보장),
   - 원격 Fleet 컨테이너는 `extra_hosts`로 Account issuer 호스트명을 브리지 게이트웨이에 연결하며,
   - `SSL_CERT_FILE`은 컨테이너 시스템 루트 CA와 `control-peers-ca`를 결합한 읽기 전용 번들(`0644`/`0400`, UID/GID `10001`)을 사용한다.
3. **사람 신원과 기계 베어러 토큰을 혼용하지 않는다(D-962 준수).** 운영자 사람 로그인은 중앙 Rosy Account에서만 관리하고, `omx-arm-status`·`omx-observation-bridge` 등 셀 데몬은 `site-users.yaml`에 `machine: true, role: viewer`로 분리 유지한다.
4. **보류 이미지 환경의 연동 점검은 `/console/login`과 `/api/fleet/auth/login`을 함께 본다.** `/api/fleet/auth/connection` 응답의 `mode`가 `paired`이고 `password_login` 플래그가 `true`이며 `/api/fleet/auth/login?return=%2Fconsole`이 R Account `/api/fleet/auth/authorize`로 `303` 이동하면 중앙 Account 연동은 활성 상태다. `/console/login` 직접 리다이렉트는 이미지 갱신 시 해소된다.
5. **브라우저 교차 탭 신원 감시는 `shared/web/account-session.js`가 단일 소유한다.** `shared/web/account-session.js`가 `announceIdentity`·`watchIdentity` 공용 프리미티브를 제공하고, 도메인별 `/api/accounts/*` 래퍼가 필요한 앱(`learning/curation/perception`)도 `storage` 리스너와 폴링 로직을 복사하지 않고 `/common/account-session.js`를 직접 사용한다.

### Consequences

- 원격 셀 콘솔(`rosy-arm-cell:8543/console/login`) 접속 시에도 R의 중앙 Rosy Account로 PKCE 리다이렉트되며, 운영자 계정을 셀마다 따로 복제하지 않는다.
- 터널 서비스가 Docker 브리지 생성 전에 먼저 시작되면 바인드 실패할 수 있으므로 systemd `After=docker.service`와 브리지 게이트웨이 바인드를 유지해야 한다.
- 셀 호스트 Compose를 서명 릴리스 템플릿으로 전환할 때 `ROSY_FLEET_ACCOUNT_CLIENT_CONFIG`, `SSL_CERT_FILE`, `extra_hosts`를 함께 이관해야 회귀를 막는다.

### 관계

| 결정 | 관계 |
|---|---|
| D-960 · D-1011 | 셀 관제(`ARM-CELL`)의 업무·원장 독립성은 유지하고 사람 인증 발급만 중앙 Account에 위임한다 |
| D-962 · D-1021 | 중앙 `rosy-site-account` 단일 신원 정본과 `machine: true` 기계 토큰 분리 규칙을 원격 제어 유닛까지 확장 적용한다 |
| D-1001 · D-939 | `shared/web/account-session.js` 공용 브라우저 도구 단일 소유 원칙을 Learning 세션 래퍼까지 관철한다 |
