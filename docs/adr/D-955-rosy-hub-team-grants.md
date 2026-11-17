## D-955 Rosy를 연동 허브로 두고, 팀원은 로그인하면 기본 권한 묶음으로 바로 쓴다

**Status:** Accepted (2026-11-01, 사용자 결정: "Rosy 플랫폼에 로그인하면 대부분의 기능을 바로 사용할 수 있게", "장비·기타 연동까지 모든 앱이 Rosy와 연동되고 Harbor도 Rosy와 연동", 팀원 기본 묶음 "운용까지"). 1단계(권한 묶음)만 이 변경에서 구현한다. 2–5단계는 각자 별도 변경·검토·수용이다.

잇는 결정: [D-757](D-757-rosy-account-unified-app-sessions.md)(단일 계정·자동 세션) · [D-808](D-808-vault-explicit-site-grants.md)(site grant) · [D-361](D-361-site-console-enrolls-robot-by-screen-code.md)·[D-555](D-555-enrolled-robot-hub-pairing.md)(로봇 등록·허브 페어링) · [D-741](D-741-unified-app-shell-seats.md)(앱 셸) · [D-939](D-939-app-link-shared-sources.md)(연동 코드 한 곳).

### Context

Rosy Account는 소스·현장 배포까지 되어 있다(D-807, 2026-10-20). 그래도 팀원이 로그인 후 바로 쓰지 못한다.

| 막힘 | 원인 |
|---|---|
| 로봇·프로젝트마다 권한을 다시 준다 | grant가 `robot:<id>`·`project:<id>` 하나씩이고 계정당 16개까지다 |
| 새 앱·로봇을 붙이려면 파일을 고치고 재시작한다 | Authority client 목록이 보호 JSON에만 있다 |
| 등록한 로봇이 계정으로 열리지 않는다 | D-361·D-555 등록이 Account client를 만들지 않는다 |
| 바깥 앱은 따로 로그인한다 | Harbor는 자체 계정 + Fleet service 토큰(Harbor ADR 0015) |

### Decision

1. **Rosy가 허브다.** 계정·권한·연동 등록·앱 목록은 Fleet의 Account 원장 하나가 갖는다. 앱과 장비는 표준 수신 계약(사람 세션) 또는 기계 신원으로만 붙는다. 앱 사이에 따로 계정이나 연결을 만들지 않는다.
2. **모든 로봇·모든 프로젝트 grant (1단계).** 저장된 grant의 resource로 `robot:*`·`project:*`를 허용한다. `site:*`는 허용하지 않는다. Authority는 발급할 때 정확한 grant와 같은 종류의 `*` grant를 합쳐 구체적인 resource 하나로 풀어 쓴다(`grants_for`). 접근 토큰의 `aud`·grant는 지금처럼 구체적인 하나라서 CORE·Learning·Cam·Games 수신기는 바뀌지 않는다. `*`는 등록된 client resource에만 닿는다.
3. **팀원 기본 묶음 (1단계).** 현장 `fleet.read`·`fleet.operate`·`games.operate`, `robot:*`의 `robot.read`·`robot.operate`, `project:*`의 `learning.view`·`learning.edit`·`learning.import`. 넣지 않는다: `accounts.manage`, `fleet.policy`, `camera.manage`, `robot.admin`, `learning.approve`·`publish`·`manage`, Vault 권한. 계정 화면은 새 계정을 이 묶음으로 채우고 "팀원 기본 권한으로 채우기"를 제공한다. 정의는 `applications/fleet/web/shared/account-permissions.js`의 `teamGrants` 한 곳이다. 서버는 묶음을 따로 알지 않고 기존 grant 검증만 한다. 2026-11-07 보완: 현장 `harbor.view`·`harbor.operate`·`harbor.field`를 더한다(`harbor.admin`은 넣지 않는다). 조회 역할 묶음에는 `harbor.view`만 더한다.
4. **연동 등록부 (2단계).** client 목록을 Fleet DB로 옮기고 콘솔 "연동" 화면에서 `accounts.manage`가 재시작 없이 추가·정지한다. 보호 JSON의 `clients`는 첫 가져오기 값으로만 남는다.
5. **장비 등록 = 계정 연동 (3단계).** D-361·D-555 등록이 끝나면 같은 transaction에서 그 로봇의 등록부 줄을 만들고 수신 설정을 같은 TLS 등록 경로로 보낸다. OMX 팔·Cam·학습 서비스도 같은 등록부에 기계 신원으로 올린다.
6. **앱 목록 (4단계).** Fleet이 등록부의 앱 목록을 한 API로 주고, 모든 앱의 앱 전환은 그 목록을 읽는다.
7. **바깥 앱 (5단계).** 바깥 앱은 ROSY 코드를 import하지 않고 문서화한 HTTP 수신 계약(code+S256 PKCE, 10초 introspect, 회수·로그아웃)과 앱 이름 site capability(예: `harbor.*`)로 붙는다. 서버 간 연결은 등록부가 발급하는 named service 신원이다. 적용은 각 앱 저장소의 결정이다. 2026-11-07 보완: Harbor용 site capability는 `harbor.view`·`harbor.operate`·`harbor.field`·`harbor.admin` 넷이다. Harbor는 이를 자기 그룹 viewer·operator·field·admin에 그대로 대응시키고, 권한 판단은 Harbor 안에서 한다. 바깥 앱이 따를 계약은 [Rosy Account protocol](../reference/rosy-account-protocol.md)의 「바깥 앱 수신 계약」 절이다. Android 수신기는 모르는 capability가 든 토큰 전체를 거부하므로, site capability를 더할 때는 `shared/android/account`의 허용 목록도 함께 고친다.

### 대체하는 범위

- D-757 §3의 "권한은 자원마다 명시적으로 준다"를 `*` grant까지 넓힌다. 역할 이름으로 권한을 넓히지 않는다는 원칙은 그대로다.
- D-808의 "기존 계정과 bootstrap에 자동 추가하지 않는다"는 유지한다. 팀원 기본 묶음에는 Vault 권한이 없고, 서버가 묶음을 자동 적용하지 않는다. 기존 계정 적용은 관리자 변경(감사 기록)으로 한다.

### Consequences and validation

- 권한이 넓어져도 CORE 가드, SAF-003, 운전석·deadman, 위험 작업 확인, 비상정지는 그대로다(D-757 §4). CORE가 최종 writer다.
- 1단계 시험: `contracts/foundation/test/test_account_access.py`(`*` 허용 범위, 해석, 토큰에 `*` 불가), `operations/fleet/test/test_account_authority.py`(구체 resource 발급, 미등록 대상 거부), `operations/fleet/test/test_account_admin_browser.py`(새 계정 기본 묶음과 저장 결과).
- 2·3단계는 새 자격 경로라 독립 보안 검토 대상이다. 원격 시험 통과는 현장 설치·실사용 수용을 뜻하지 않는다.
- 상세 배경과 단계표: 작업 공간 계획 `Rosy/docs/superpowers/plans/2026-11-01-rosy-hub-integration.md`.
